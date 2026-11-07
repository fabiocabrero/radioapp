"""Rádios de qualquer marca e modelo pelo Hamlib (rigctld): Icom, Yaesu, Kenwood e centenas de outros.

O Hamlib fala o protocolo de cada rádio; este módulo só conversa com o `rigctld` por TCP (texto simples) e oferece a mesma
interface de `radio.Radio`, então o resto do app não muda. O `rigctld` acompanha o WSJT-X; o app o encontra, lista os
modelos (`rigctld -l`) e o inicia sozinho. Também conecta a um `rigctld` que já esteja rodando.

Sem scope pelo Hamlib: o espectro vem do áudio recebido. Só o IC-7300 nativo (CI-V) traz o scope do rádio.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Optional

from . import applog
from .radio import RadioState

# Modos do app <-> Hamlib. Com DATA ligado o app usa o modo "pacote" do Hamlib (PKTUSB etc.).
_TO_HAMLIB = {"LSB": "LSB", "USB": "USB", "AM": "AM", "FM": "FM", "CW": "CW", "CW-R": "CWR", "RTTY": "RTTY", "RTTY-R": "RTTYR"}
_FROM_HAMLIB = {"LSB": ("LSB", False), "USB": ("USB", False), "AM": ("AM", False), "FM": ("FM", False), "CW": ("CW", False),
                "CWR": ("CW-R", False), "RTTY": ("RTTY", False), "RTTYR": ("RTTY-R", False), "PKTUSB": ("USB", True),
                "PKTLSB": ("LSB", True), "PKTFM": ("FM", True), "PKTAM": ("AM", True), "AMS": ("AM", False), "WFM": ("FM", False),
                "FMN": ("FM", False), "ECSSUSB": ("USB", False), "ECSSLSB": ("LSB", False)}
_PACKET = {"USB": "PKTUSB", "LSB": "PKTLSB", "FM": "PKTFM", "AM": "PKTAM"}
_LEVEL = {"af": "AF", "rf": "RF", "sql": "SQL", "power": "RFPOWER", "nr": "NR"}
CREATE_NO_WINDOW = 0x08000000


@dataclass(frozen=True)
class RigModel:
    number: int
    brand: str
    name: str

    @property
    def label(self) -> str:
        return f"{self.brand} {self.name}"


BRANDS = ("Icom", "Yaesu", "Kenwood")


def find_rigctld(extra: tuple[str, ...] = ()) -> Optional[Path]:
    """Procura o rigctld do Hamlib (o do WSJT-X serve), em pastas conhecidas e no PATH."""
    names = ("rigctld.exe", "rigctld-wsjtx.exe", "rigctld")
    dirs = list(extra) + ["C:/WSJT/wsjtx/bin", "C:/Program Files*/wsjt*/wsjtx/bin", "C:/Program Files*/WSJT-X/bin",
                          "C:/Program Files*/Hamlib*/bin", "C:/Hamlib*/bin", "C:/Program Files*/JS8Call/bin",
                          "C:/Program Files*/Fldigi*", "C:/Program Files*/FreeDV*/bin"]
    for d in dirs:
        for folder in glob.glob(d):
            for n in names:
                p = Path(folder) / n
                if p.exists():
                    return p
    for n in names:
        found = shutil.which(n)
        if found:
            return Path(found)
    return None


def list_models(rigctld: Path) -> list[RigModel]:
    """Modelos que o rigctld conhece (`rigctld -l`)."""
    try:
        out = subprocess.run([str(rigctld), "-l"], capture_output=True, text=True, timeout=20,
                             creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0, encoding="utf-8", errors="replace").stdout
    except (OSError, subprocess.SubprocessError) as exc:
        applog.log.error("rigctld -l: %s", exc)
        return []
    models = []
    for line in out.splitlines():
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) >= 3 and parts[0].isdigit():
            models.append(RigModel(int(parts[0]), parts[1], parts[2]))
    return sorted(models, key=lambda m: (m.brand, m.name))


def s_raw_from_db(db: float) -> int:
    """dB em relação a S9 (STRENGTH do Hamlib) para a escala de 0 a 255 usada pelo app (S9 = 120, S9+60 = 241)."""
    raw = 120 + db * (120 / 54) if db < 0 else 120 + db * (121 / 60)
    return int(max(0, min(255, raw)))


class RigctldProcess:
    """Inicia e para o rigctld (sem janela)."""

    def __init__(self, exe: Path, model: int, port: str, baud: int, tcp_port: int = 4533, extra: str = "") -> None:
        self.exe, self.model, self.serial, self.baud, self.tcp_port, self.extra = exe, model, port, baud, tcp_port, extra
        self.proc: Optional[subprocess.Popen] = None

    def start(self, timeout: float = 8.0) -> None:
        args = [str(self.exe), "-m", str(self.model), "-t", str(self.tcp_port), "-T", "127.0.0.1"]
        if self.serial:
            args += ["-r", self.serial, "-s", str(self.baud)]
        if self.extra.strip():
            args += self.extra.split()
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                     creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
        end = time.time() + timeout
        while time.time() < end:
            if self.proc.poll() is not None:
                err = (self.proc.stderr.read() or b"").decode("utf-8", "replace").strip().splitlines()
                raise RuntimeError("O rigctld não iniciou: " + (err[-1] if err else f"código {self.proc.returncode}"))
            try:
                socket.create_connection(("127.0.0.1", self.tcp_port), timeout=0.3).close()
                return
            except OSError:
                time.sleep(0.15)
        self.stop()
        raise RuntimeError("O rigctld não respondeu a tempo (confira a porta serial, a velocidade e o modelo).")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


class HamlibRig:
    """Mesma interface de `radio.Radio`, sobre o rigctld."""

    has_scope = False

    def __init__(self, host: str = "127.0.0.1", port: int = 4533, process: Optional[RigctldProcess] = None) -> None:
        self.host, self.port, self.process = host, port, process
        self.state = RadioState()
        self.on_state: Callable[[RadioState], None] = lambda s: None
        self.on_scope: Callable = lambda s: None
        self.on_message: Callable[[str], None] = lambda m: None
        self.restore_on_exit = False
        self.saved_scope: dict = {}
        self._sock: Optional[socket.socket] = None
        self._file = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._baseline: Optional[tuple] = None
        self._fails = 0

    # ---- ciclo de vida ----
    def start(self) -> None:
        if self.process:
            self.process.start()
        self._connect()
        self._stop.clear()
        self.snapshot()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def _connect(self) -> None:
        self._sock = socket.create_connection((self.host, self.port), timeout=3)
        self._sock.settimeout(4)
        self._file = self._sock.makefile("rb")

    def stop(self) -> None:
        try:
            if self.restore_on_exit:
                self.restore_basic()
        except Exception:  # noqa: BLE001
            pass
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        for closer in (lambda: self._sock and self._sock.close(),):
            try:
                closer()
            except OSError:
                pass
        self._sock = self._file = None
        if self.process:
            self.process.stop()
        self.state.connected = False
        self.on_state(replace(self.state))

    # ---- protocolo ----
    def _cmd(self, text: str, lines: int = 1) -> list[str]:
        """Envia um comando e lê `lines` linhas de resposta (os comandos de ajuste respondem 'RPRT n')."""
        with self._lock:
            if not self._sock:
                raise ConnectionError("sem conexão")
            self._sock.sendall((text + "\n").encode("utf-8"))
            out = []
            for _ in range(lines):
                raw = self._file.readline()
                if not raw:
                    raise ConnectionError("o rigctld fechou a conexão")
                line = raw.decode("utf-8", "replace").strip()
                out.append(line)
                if line.startswith("RPRT") and not line.endswith(" 0"):
                    break
            return out

    def _set(self, text: str) -> bool:
        try:
            r = self._cmd(text)[0]
        except (OSError, ConnectionError) as exc:
            self.on_message(f"Rádio: {exc}")
            return False
        if not r.startswith("RPRT 0"):
            self.on_message(f"O rádio recusou '{text.split()[0]}' ({r}).")
            return False
        return True

    # ---- comandos ----
    def set_freq(self, hz: int) -> None:
        if self._set(f"F {int(hz)}"):
            self.state.freq = int(hz)
            self.on_state(replace(self.state))

    def set_mode(self, mode: str, data: bool = False, filt: int = 1) -> None:
        name = _PACKET.get(mode) if data else None
        if name is None:
            name = _TO_HAMLIB.get(mode, "USB")
        if self._set(f"M {name} 0"):  # passband 0 = o padrão do rádio para o modo
            self.state.mode, self.state.data_mode = mode, bool(data and mode in _PACKET)
            self.on_state(replace(self.state))

    def set_ptt(self, on: bool) -> None:
        if self._set(f"T {1 if on else 0}"):
            self.state.ptt = bool(on)
            self.on_state(replace(self.state))

    def set_level(self, name: str, value: int) -> None:
        hl = _LEVEL.get(name)
        if hl:
            self._set(f"L {hl} {value / 255:.3f}")
            self.state.levels[name] = int(value)
        elif name == "key_speed":
            wpm = int(6 + value / 255 * 42)
            self._set(f"L KEYSPD {wpm}")
            self.state.levels[name] = int(value)

    def set_func(self, name: str, value: int) -> None:
        self._set(f"U {name.upper()} {1 if value else 0}")

    def send_cw(self, text: str) -> None:
        self._set("b " + text.upper())

    def stop_cw(self) -> None:
        try:
            self._cmd("\\stop_morse")
        except (OSError, ConnectionError):
            pass

    def set_scope(self, on: bool, span_hz: Optional[int] = None) -> None:
        """O Hamlib não traz o scope do rádio: o app usa o espectro do áudio."""

    def set_scope_span(self, span_hz: int) -> None:
        """Sem scope pelo Hamlib."""

    def snapshot(self, timeout: float = 1.5) -> None:
        self._read_basic()
        st = self.state
        self._baseline = (st.freq, st.mode, st.data_mode, st.filter) if st.connected else None

    def restore_scope(self) -> None:
        """Nada a restaurar: o app não mexe no scope do rádio por aqui."""

    def restore_basic(self) -> None:
        if self._baseline:
            freq, mode, data, filt = self._baseline
            self.set_mode(mode, data, filt)
            self.set_freq(freq)

    # ---- leitura ----
    def _read_basic(self) -> None:
        st = self.state
        st.freq = int(float(self._cmd("f")[0]))
        mode, _pb = self._cmd("m", 2)
        st.mode, st.data_mode = _FROM_HAMLIB.get(mode.upper(), ("USB", False))
        st.ptt = self._cmd("t")[0].strip() == "1"
        st.connected = True

    def _read_meters(self, slow: bool) -> None:
        st = self.state
        try:
            st.s_meter = s_raw_from_db(float(self._cmd("l STRENGTH")[0])) if not st.ptt else 0
        except ValueError:
            pass
        if st.ptt:
            for key, attr, scale in (("RFPOWER_METER", "power", 255), ("SWR", "swr", 0)):
                try:
                    v = float(self._cmd(f"l {key}")[0])
                    if attr == "power":
                        st.power = int(max(0, min(255, v * scale)))
                    else:
                        st.swr = int(max(0, min(255, (v - 1) / 5 * 255))) if v >= 1 else 0
                except ValueError:
                    pass
        else:
            st.power = st.swr = 0
        if slow:
            for key, hl in (("af", "AF"), ("rf", "RF"), ("sql", "SQL"), ("power", "RFPOWER")):
                try:
                    st.levels[key] = int(max(0.0, min(1.0, float(self._cmd(f"l {hl}")[0]))) * 255)
                except ValueError:
                    pass

    def _poll_loop(self) -> None:
        tick = 0
        while not self._stop.is_set():
            try:
                self._read_basic()
                self._read_meters(tick % 8 == 0)
                self._fails = 0
                self.on_state(replace(self.state, levels=dict(self.state.levels)))
            except (OSError, ConnectionError, ValueError) as exc:
                self._fails += 1
                if self._fails == 3:
                    self.state.connected = False
                    self.on_state(replace(self.state))
                    self.on_message(f"Perdi a conexão com o rádio: {exc}")
                    applog.log.error("Hamlib: %s", exc)
            tick += 1
            self._stop.wait(0.25)
