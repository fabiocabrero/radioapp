"""Decodificação de FST4, Q65, JT65, JT9 e WSPR usando o jt9.exe e o wsprd.exe de um WSJT-X instalado.

Os programas do WSJT-X (GPL) são chamados como processos externos; nada deles é copiado para este projeto.
Só recepção: não há gerador de áudio para esses modos nas ferramentas de linha de comando.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from .ftengine import Decimator4

SAMPLE_RATE = 12000
BIN_CANDIDATES = [r"C:\WSJT\wsjtx\bin", r"C:\Program Files\wsjtx\bin", r"C:\Program Files (x86)\wsjtx\bin",
                  r"C:\Program Files\WSJT-X\bin", r"C:\WSJT\bin"]

# flag do jt9, períodos aceitos (s), período padrão
MODES = {
    "FST4": ("-7", [15, 30, 60, 120, 300], 60),
    "Q65": ("--q65", [15, 30, 60, 120, 300], 60),
    "JT65": ("-6", [60], 60),
    "JT9": ("-9", [60], 60),
    "WSPR": ("", [120], 120),
}
VALIDATED = {"FST4": True, "Q65": True, "JT65": False, "JT9": False, "WSPR": False}

_JT9_LINE = re.compile(r"^(\d{4,6})\s+(-?\d+)\s+(-?\d+\.\d)\s+(\d+)\s+(\S)\s+(.+?)\s*$")
_WSPR_LINE = re.compile(r"^\s*(\d{4,6})\s+(-?\d+)\s+(-?\d+\.\d+)\s+(\d+\.\d+)\s+(-?\d+)\s+(\S+)\s+([A-R]{2}\d{2}(?:[A-X]{2})?)\s+(\d+)\s*$")


@dataclass
class Decode:
    snr: int
    dt: float
    freq: int      # Hz de áudio (jt9) ou Hz absolutos (WSPR)
    text: str
    extra: str = ""
    mode: str = ""
    start: float = 0.0  # época UTC do início do slot


def find_bin(custom: str = "") -> Optional[Path]:
    for cand in ([custom] if custom else []) + BIN_CANDIDATES:
        p = Path(cand)
        if (p / "jt9.exe").exists():
            return p
    return None


def write_wav(path: Path, samples: np.ndarray, rate: int = SAMPLE_RATE) -> None:
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def parse_jt9(output: str, mode: str = "", start: float = 0.0) -> list[Decode]:
    out = []
    for line in output.splitlines():
        if line.startswith("<"):
            continue
        m = _JT9_LINE.match(line)
        if not m:
            continue
        parts = re.split(r"\s{2,}", m.group(6))
        out.append(Decode(int(m.group(2)), float(m.group(3)), int(m.group(4)), parts[0].strip(),
                          " ".join(parts[1:]).strip(), mode, start))
    return out


def parse_wsprd(output: str, start: float = 0.0) -> list[Decode]:
    out = []
    for line in output.splitlines():
        m = _WSPR_LINE.match(line)
        if m:
            out.append(Decode(int(m.group(2)), float(m.group(3)), int(round(float(m.group(4)) * 1e6)),
                              f"{m.group(6)} {m.group(7)} {m.group(8)}", f"deriva {m.group(5)} Hz/min", "WSPR", start))
    return out


def _run(cmd: list[str], cwd: str, timeout: float) -> str:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, creationflags=flags)
    return proc.stdout


def decode(mode: str, samples: np.ndarray, start_epoch: float, period: int, bin_dir: Path, rx_freq: int = 1500,
           tolerance: int = 100, depth: int = 3, dial_mhz: float = 0.0, q65_submode: str = "A",
           timeout: float = 180.0) -> list[Decode]:
    """Decodifica um slot completo (mono 12 kHz) com o programa do WSJT-X correspondente ao modo."""
    when = datetime.fromtimestamp(start_epoch, timezone.utc)
    with tempfile.TemporaryDirectory(prefix="ic7300_jt_") as tmp:
        wav = Path(tmp) / f"{when:%y%m%d_%H%M}.wav"
        write_wav(wav, samples)
        if mode == "WSPR":
            out = _run([str(bin_dir / "wsprd.exe"), "-f", f"{dial_mhz:.6f}", "-a", tmp, str(wav)], tmp, timeout)
            return parse_wsprd(out, start_epoch)
        flag = MODES[mode][0]
        cmd = [str(bin_dir / "jt9.exe"), flag, "-p", str(period), "-f", str(rx_freq), "-F", str(tolerance),
               "-d", str(depth), "-L", "200", "-H", "3000", "-a", tmp, "-t", tmp]
        if mode == "Q65":
            cmd += ["-b", q65_submode]
        out = _run(cmd + [str(wav)], tmp, timeout)
        return parse_jt9(out, mode, start_epoch)


class SlotEngine:
    """Captura o áudio em slots alinhados ao relógio UTC e decodifica cada slot em segundo plano."""

    def __init__(self, on_decodes: Callable[[list[Decode]], None], on_status: Callable[[str], None],
                 clock: Callable[[], float] = time.time) -> None:
        self.on_decodes, self.on_status, self.clock = on_decodes, on_status, clock
        self.enabled = False
        self.mode = "FST4"
        self.period = 60
        self.rx_freq = 1500
        self.tolerance = 100
        self.q65_submode = "A"
        self.dial_mhz = 0.0
        self.bin_dir: Optional[Path] = None
        self._dec = Decimator4()
        self._buf: list[np.ndarray] = []
        self._slot = -1
        self._busy = threading.Lock()

    def set_mode(self, mode: str, period: int) -> None:
        self.mode, self.period = mode, period
        self._buf.clear()
        self._slot = -1

    def seconds_into_slot(self) -> float:
        return self.clock() % self.period

    def feed(self, samples48: np.ndarray) -> None:
        if not self.enabled:
            self._buf.clear()
            self._slot = -1
            return
        slot = int(self.clock() // self.period)
        if self._slot == -1:
            self._slot = slot
        if slot != self._slot:
            audio = np.concatenate(self._buf) if self._buf else np.zeros(0, dtype=np.float32)
            start = self._slot * self.period
            self._buf, self._slot = [], slot
            if len(audio) >= SAMPLE_RATE * self.period * 0.8:
                threading.Thread(target=self._decode, args=(audio, start, self.mode, self.period), daemon=True).start()
            else:
                self.on_status("Slot incompleto ignorado (o app começou a ouvir no meio do período).")
        self._buf.append(self._dec.process(samples48))

    def _decode(self, audio: np.ndarray, start: float, mode: str, period: int) -> None:
        if self.bin_dir is None:
            self.on_status("WSJT-X não encontrado: informe a pasta com jt9.exe.")
            return
        if not self._busy.acquire(blocking=False):
            self.on_status("Decodificador ainda ocupado com o slot anterior.")
            return
        try:
            self.on_status(f"Decodificando {mode}…")
            found = decode(mode, audio, start, period, self.bin_dir, self.rx_freq, self.tolerance,
                           dial_mhz=self.dial_mhz, q65_submode=self.q65_submode)
            self.on_status(f"{mode}: {len(found)} decodificações")
            self.on_decodes(found)
        except Exception as exc:
            self.on_status(f"Erro no decodificador: {exc}")
        finally:
            self._busy.release()
