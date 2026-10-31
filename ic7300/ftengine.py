"""Motor FT8/FT4: temporização de slots, decodificação contínua, transmissão e sugestão de resposta."""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from . import ft8

_GRID = re.compile(r"^[A-R]{2}[0-9]{2}$")
_REPORT = re.compile(r"^R?[+-]\d{2}$")


class Decimator4:
    """48 kHz -> 12 kHz com filtro FIR passa-baixas (janela de Blackman)."""

    def __init__(self, taps: int = 63) -> None:
        n = np.arange(taps) - (taps - 1) / 2
        h = np.sinc(2 * 4900 / 48000 * n) * np.blackman(taps)
        self.h = h / h.sum()
        self._tail = np.zeros(taps - 1)

    def process(self, x: np.ndarray) -> np.ndarray:
        buf = np.concatenate([self._tail, np.asarray(x, dtype=np.float64)])
        self._tail = buf[-(len(self.h) - 1):]
        return np.convolve(buf, self.h, mode="valid")[::4].astype(np.float32)


def upsample4(x: np.ndarray) -> np.ndarray:
    taps = 63
    n = np.arange(taps) - (taps - 1) / 2
    h = np.sinc(2 * 4900 / 48000 * n) * np.blackman(taps)
    h /= h.sum()
    return np.convolve(np.repeat(x, 4), h, mode="same").astype(np.float32)


@dataclass
class RxLine:
    slot_start: float  # época UTC do início do slot
    mode: str
    decode: ft8.Decode


def suggest_reply(my_call: str, text: str, my_grid: str = "", snr: int = 0) -> Optional[tuple[str, str]]:
    """Dada uma mensagem recebida, devolve (indicativo do outro, próxima mensagem a enviar)."""
    words = text.replace("<", "").replace(">", "").split()
    my = my_call.upper()
    if len(words) >= 3 and words[0] == "CQ":
        call = words[-2] if _GRID.match(words[-1]) else words[-1]
        if call == my:
            return None
        return call, f"{call} {my} {my_grid[:4].upper()}".strip()
    if len(words) < 3 or words[0] != my:
        return None
    them, last = words[1], words[2]
    rep = f"{snr:+03d}"
    if last in ("RR73", "RRR", "73"):
        return them, f"{them} {my} 73"
    if last.startswith("R") and _REPORT.match(last):
        return them, f"{them} {my} RR73"
    if _REPORT.match(last):
        return them, f"{them} {my} R{rep}"
    if _GRID.match(last):
        return them, f"{them} {my} {rep}"
    return None


class FtEngine:
    def __init__(self, on_decodes: Callable[[list[RxLine]], None], on_tx: Callable[[str], None],
                 set_ptt: Callable[[bool], None], play: Callable[[np.ndarray], None],
                 clock: Callable[[], float] = time.time) -> None:
        self.on_decodes, self.on_tx, self.set_ptt, self.play = on_decodes, on_tx, set_ptt, play
        self.clock = clock
        self.mode = "FT8"
        self.tx_even = True       # transmite em slots pares (0, 30 s) ou ímpares (15, 45 s)
        self.tx_freq = 1500.0
        self.tx_level = 0.5
        self.tx_enabled = False
        self.tx_text = ""
        self._dec = Decimator4()
        self._buf: list[np.ndarray] = []
        self._slot = -1
        self._tx_busy = threading.Event()
        self._halt = threading.Event()

    @property
    def slot_len(self) -> float:
        return ft8.SLOT_SECONDS[self.mode]

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self._buf.clear()
        self._slot = -1

    def seconds_into_slot(self) -> float:
        return self.clock() % self.slot_len

    # ---- recepção ----
    def feed(self, samples48: np.ndarray) -> None:
        now = self.clock()
        slot = int(now // self.slot_len)
        if self._slot == -1:
            self._slot = slot
        if slot != self._slot:
            audio = np.concatenate(self._buf) if self._buf else np.zeros(0, dtype=np.float32)
            start = self._slot * self.slot_len
            self._buf, self._slot = [], slot
            if len(audio) > ft8.SAMPLE_RATE * 5 and ft8.available():
                threading.Thread(target=self._decode, args=(audio, start, self.mode), daemon=True).start()
            self._maybe_tx(slot)
        self._buf.append(self._dec.process(samples48))

    def _decode(self, audio: np.ndarray, start: float, mode: str) -> None:
        try:
            lines = [RxLine(start, mode, d) for d in ft8.decode_slot(audio, mode)]
        except Exception:
            return
        self.on_decodes(sorted(lines, key=lambda l: -l.decode.snr))

    # ---- transmissão ----
    def _maybe_tx(self, slot: int) -> None:
        if not (self.tx_enabled and self.tx_text) or self._tx_busy.is_set():
            return
        if (slot % 2 == 0) != self.tx_even:
            return
        threading.Thread(target=self._transmit, args=(self.tx_text, self.mode), daemon=True).start()

    def _transmit(self, text: str, mode: str) -> None:
        self._tx_busy.set()
        self._halt.clear()
        try:
            audio = ft8.encode_message(text, mode, self.tx_freq) * self.tx_level
            self.on_tx(f"TX {mode}: {text}")
            self.set_ptt(True)
            time.sleep(0.15)
            self.play(upsample4(audio))
            time.sleep(0.1)
        except Exception as exc:
            self.on_tx(f"Falha no TX: {exc}")
        finally:
            self.set_ptt(False)
            self._tx_busy.clear()

    def halt(self) -> None:
        self.tx_enabled = False
        self._halt.set()
        self.set_ptt(False)
