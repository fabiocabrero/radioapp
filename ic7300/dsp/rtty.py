"""RTTY (Baudot ITA2) em AFSK: gerador de áudio e decodificador de FSK de dois tons."""
from __future__ import annotations

import numpy as np

LTRS = {0x01: "E", 0x02: "\n", 0x03: "A", 0x04: " ", 0x05: "S", 0x06: "I", 0x07: "U", 0x08: "\r", 0x09: "D", 0x0A: "R",
        0x0B: "J", 0x0C: "N", 0x0D: "F", 0x0E: "C", 0x0F: "K", 0x10: "T", 0x11: "Z", 0x12: "L", 0x13: "W", 0x14: "H",
        0x15: "Y", 0x16: "P", 0x17: "Q", 0x18: "O", 0x19: "B", 0x1A: "G", 0x1C: "M", 0x1D: "X", 0x1E: "V"}
FIGS = {0x01: "3", 0x02: "\n", 0x03: "-", 0x04: " ", 0x05: "'", 0x06: "8", 0x07: "7", 0x08: "\r", 0x09: "$", 0x0A: "4",
        0x0C: ",", 0x0D: "!", 0x0E: ":", 0x0F: "(", 0x10: "5", 0x11: "+", 0x12: ")", 0x13: "2", 0x14: "#", 0x15: "6",
        0x16: "0", 0x17: "1", 0x18: "9", 0x19: "?", 0x1A: "&", 0x1C: ".", 0x1D: "/", 0x1E: ";"}
SHIFT_FIGS, SHIFT_LTRS = 0x1B, 0x1F
_ENC_LTRS = {c: k for k, c in LTRS.items()}
_ENC_FIGS = {c: k for k, c in FIGS.items()}


def text_to_codes(text: str, uos: bool = True) -> list[int]:
    """Texto -> códigos Baudot de 5 bits, com LTRS/FIGS inseridos quando preciso.

    Com `uos` (unshift on space) o espaço devolve o receptor a letras, então figuras depois de um espaço
    repetem o código FIGS; sem `uos` o modo é mantido e LTRS é enviado só quando necessário.
    """
    codes = [SHIFT_LTRS]
    figs = False
    for ch in text.upper().replace("\r\n", "\n"):
        if ch in (" ", "\n", "\r"):
            codes.append(_ENC_LTRS[ch])
            if uos and ch == " ":
                figs = False
            continue
        if ch in _ENC_LTRS:
            if figs:
                codes.append(SHIFT_LTRS)
                figs = False
            codes.append(_ENC_LTRS[ch])
        elif ch in _ENC_FIGS:
            if not figs:
                codes.append(SHIFT_FIGS)
                figs = True
            codes.append(_ENC_FIGS[ch])
    return codes


def encode(text: str, baud: float = 45.45, mark: float = 2125.0, shift: float = 170.0, fs: int = 48000,
           reverse: bool = False, amp: float = 0.5, lead_s: float = 0.3, uos: bool = True) -> np.ndarray:
    """Áudio AFSK de fase contínua: marca em `mark` Hz e espaço em `mark + shift` Hz (invertido com reverse).

    Cada caractere é start (espaço), 5 bits LSB primeiro e stop de 1,5 bit (marca). Com `uos`, depois de um
    espaço o transmissor volta a letras, como na recepção com "unshift on space".
    """
    f_mark, f_space = (mark + shift, mark) if reverse else (mark, mark + shift)
    plan: list[tuple[int, float]] = [(1, lead_s * baud)]
    for code in text_to_codes(text, uos) + [SHIFT_LTRS]:
        plan += [(0, 1.0)] + [((code >> i) & 1, 1.0) for i in range(5)] + [(1, 1.5)]
    out: list[np.ndarray] = []
    phase = 0.0
    carry = 0.0
    for bit, bits_long in plan:
        dur = bits_long * fs / baud + carry
        n = max(0, int(round(dur)))
        carry = dur - n
        f = f_mark if bit else f_space
        out.append(np.sin(phase + 2 * np.pi * f * np.arange(n) / fs))
        phase = (phase + 2 * np.pi * f * n / fs) % (2 * np.pi)
    return (amp * np.concatenate(out)).astype(np.float32)


class RttyDecoder:
    """Decodificador contínuo: energia de marca vs espaço, depois um UART sincronizado pelo bit de start."""

    def __init__(self, fs: int = 48000, baud: float = 45.45, mark: float = 2125.0, shift: float = 170.0,
                 reverse: bool = False, unshift_on_space: bool = True, squelch: float = 0.03) -> None:
        self.fs, self.baud, self.mark, self.shift = fs, baud, mark, shift
        self.reverse, self.uos, self.squelch = reverse, unshift_on_space, squelch
        self._decim = max(1, int(fs / baud / 16))
        self._n = 0                                    # amostras já processadas (continuidade de fase)
        self._tails = [np.zeros(0, dtype=complex), np.zeros(0, dtype=complex)]
        self._decim_phase = 0
        self.level = 0.0                               # nível médio de sinal (para exibir/ajustar)
        self._state = "idle"
        self._count = 0.0
        self._codes_bits: list[int] = []
        self._figs = False

    @property
    def rate(self) -> float:
        return self.fs / self._decim

    @property
    def spb(self) -> float:
        return self.rate / self.baud

    def configure(self, mark: float | None = None, shift: float | None = None, reverse: bool | None = None,
                  baud: float | None = None) -> None:
        if mark is not None:
            self.mark = mark
        if shift is not None:
            self.shift = shift
        if reverse is not None:
            self.reverse = reverse
        if baud is not None:
            self.baud = baud
            self._tails = [np.zeros(0, dtype=complex), np.zeros(0, dtype=complex)]
            self._state = "idle"

    def process(self, samples: np.ndarray) -> str:
        x = np.asarray(samples, dtype=np.float64)
        n = len(x)
        if n == 0:
            return ""
        f_mark, f_space = (self.mark + self.shift, self.mark) if self.reverse else (self.mark, self.mark + self.shift)
        t = (np.arange(n) + self._n) / self.fs
        self._n += n
        window = max(2, int(0.7 * self.fs / self.baud))
        env = []
        for i, f in enumerate((f_mark, f_space)):
            z = x * np.exp(-2j * np.pi * f * t)
            tail = self._tails[i]
            if len(tail) != window - 1:
                tail = np.zeros(window - 1, dtype=complex)
            ext = np.concatenate([tail, z])
            cs = np.concatenate([[0], np.cumsum(ext)])
            env.append(np.abs(cs[window:window + n] - cs[:n]) / window)
            self._tails[i] = ext[-(window - 1):] if window > 1 else ext[:0]
        idx = np.arange(self._decim_phase, n, self._decim)
        self._decim_phase = int((idx[-1] + self._decim) - n) if len(idx) else max(0, self._decim_phase - n)
        em, es = env[0][idx], env[1][idx]
        total = em + es
        if len(total):
            self.level = 0.95 * self.level + 0.05 * float(total.mean())
        bits = np.where(total > self.squelch, (em > es).astype(np.int8), 1)
        return self._uart(bits)

    def _uart(self, bits: np.ndarray) -> str:
        out: list[str] = []
        spb = self.spb
        for b in bits:
            if self._state == "idle":
                if b == 0:
                    self._state, self._count, self._codes_bits = "start", 0.0, []
                continue
            self._count += 1
            if self._state == "start":
                if self._count >= spb / 2:               # meio do bit de start
                    if b != 0:
                        self._state = "idle"             # falso início (ruído)
                    else:
                        self._state, self._count = "data", 0.0
                continue
            if self._count >= spb:                       # centro do próximo bit
                self._count -= spb
                if self._state == "data":
                    self._codes_bits.append(int(b))
                    if len(self._codes_bits) == 5:
                        self._state = "stop"
                elif self._state == "stop":
                    if b == 1:                           # stop válido: entrega o caractere
                        code = sum(bit << i for i, bit in enumerate(self._codes_bits))
                        out.append(self._char(code))
                    self._state = "idle"
        return "".join(out)

    def _char(self, code: int) -> str:
        if code == SHIFT_FIGS:
            self._figs = True
            return ""
        if code == SHIFT_LTRS:
            self._figs = False
            return ""
        ch = (FIGS if self._figs else LTRS).get(code, "")
        if self.uos and code == 0x04:
            self._figs = False
        return ch


def decode_codes(codes: list[int], uos: bool = True) -> str:
    dec = RttyDecoder(unshift_on_space=uos)
    return "".join(dec._char(c) for c in codes)
