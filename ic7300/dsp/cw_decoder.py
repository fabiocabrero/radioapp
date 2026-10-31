"""Decodificador de CW: detecta o tom, extrai o envelope e converte pontos/traços em texto."""
from __future__ import annotations

import numpy as np

MORSE = {
    ".-": "A", "-...": "B", "-.-.": "C", "-..": "D", ".": "E", "..-.": "F", "--.": "G", "....": "H", "..": "I",
    ".---": "J", "-.-": "K", ".-..": "L", "--": "M", "-.": "N", "---": "O", ".--.": "P", "--.-": "Q", ".-.": "R",
    "...": "S", "-": "T", "..-": "U", "...-": "V", ".--": "W", "-..-": "X", "-.--": "Y", "--..": "Z",
    "-----": "0", ".----": "1", "..---": "2", "...--": "3", "....-": "4", ".....": "5", "-....": "6", "--...": "7",
    "---..": "8", "----.": "9", ".-.-.-": ".", "--..--": ",", "..--..": "?", "-..-.": "/", "-...-": "=",
    "-....-": "-", ".-.-.": "+", "-.--.": "(", "-.--.-": ")", ".----.": "'", "---...": ":", ".-..-.": '"',
    "...-.-": "<SK>", ".-.-": "<AA>", "-.-.-": "<KA>", "...-.": "<SN>", "........": "<ERR>",
}
TEXT_TO_MORSE = {v: k for k, v in MORSE.items() if len(v) == 1}


def text_to_morse_audio(text: str, wpm: float = 20, tone: float = 600, fs: int = 48000, amp: float = 0.5) -> np.ndarray:
    """Sintetiza CW (usado no simulador e nos testes)."""
    dit = 1.2 / wpm
    ramp = int(0.004 * fs)
    chunks: list[np.ndarray] = []

    def tone_for(units: float) -> np.ndarray:
        n = int(units * dit * fs)
        t = np.arange(n) / fs
        env = np.ones(n)
        r = min(ramp, n // 2)
        env[:r] = np.linspace(0, 1, r)
        env[n - r:] = np.linspace(1, 0, r)
        return amp * env * np.sin(2 * np.pi * tone * t)

    def silence(units: float) -> np.ndarray:
        return np.zeros(int(units * dit * fs))

    for word in text.upper().split():
        for ci, ch in enumerate(word):
            code = TEXT_TO_MORSE.get(ch)
            if not code:
                continue
            for ei, el in enumerate(code):
                chunks.append(tone_for(1 if el == "." else 3))
                if ei < len(code) - 1:
                    chunks.append(silence(1))
            if ci < len(word) - 1:
                chunks.append(silence(3))
        chunks.append(silence(7))
    return np.concatenate(chunks) if chunks else np.zeros(0)


class CwDecoder:
    """Decodificador contínuo. Alimente com `process(samples)`; retorna texto novo."""

    BLOCK_S = 0.005  # resolução do envelope: 5 ms
    HIST = 600       # 3 s de histórico para piso de ruído e pico

    def __init__(self, fs: int = 48000, tone: float | None = 600, auto_tone: bool = True,
                 lo: float = 300, hi: float = 1200) -> None:
        self.fs = fs
        self.block = int(fs * self.BLOCK_S)
        self.tone = tone or 600.0
        self.auto_tone = auto_tone
        self.lo, self.hi = lo, hi
        self.dit_ms = 60.0  # ~20 WPM inicial
        self.snr_ok = False
        self._phase = 0.0
        self._rest = np.zeros(0)
        self._tone_buf = np.zeros(0)
        self._peak = 1e-6
        self._floor = 1e-6
        self._hist: list[float] = []
        self._count = 0
        self._mark = False
        self._run = 0  # blocos no estado atual
        self._cand_state = False
        self._cand_run = 0
        self._symbol = ""
        self._flushed = True

    @property
    def wpm(self) -> float:
        return 1200.0 / self.dit_ms

    def reset(self) -> None:
        self.__init__(self.fs, self.tone, self.auto_tone, self.lo, self.hi)

    # ---- entrada de áudio ----
    def process(self, samples: np.ndarray) -> str:
        x = np.concatenate([self._rest, np.asarray(samples, dtype=np.float64)])
        n_blocks = len(x) // self.block
        self._rest = x[n_blocks * self.block:]
        if n_blocks == 0:
            return ""
        x = x[: n_blocks * self.block]
        if self.auto_tone:
            self._track_tone(x)
        t = (np.arange(len(x)) + 0.0) / self.fs
        w = 2 * np.pi * self.tone
        ph = self._phase
        osc = np.exp(-1j * (w * t + ph))
        self._phase = (ph + w * len(x) / self.fs) % (2 * np.pi)
        env = np.abs((x * osc).reshape(n_blocks, self.block).mean(axis=1)) * 2
        return self._decode_envelope(env)

    def _track_tone(self, x: np.ndarray) -> None:
        self._tone_buf = np.concatenate([self._tone_buf, x])[-int(self.fs * 0.5):]
        if len(self._tone_buf) < self.fs * 0.25:
            return
        buf = self._tone_buf * np.hanning(len(self._tone_buf))
        spec = np.abs(np.fft.rfft(buf, n=1 << 16))
        freqs = np.fft.rfftfreq(1 << 16, 1 / self.fs)
        sel = (freqs >= self.lo) & (freqs <= self.hi)
        band = spec[sel]
        if band.max() > 6 * np.median(band):
            new = float(freqs[sel][band.argmax()])
            self.tone += 0.2 * (new - self.tone) if abs(new - self.tone) < 80 else (new - self.tone)

    # ---- envelope -> texto ----
    def _decode_envelope(self, env: np.ndarray) -> str:
        out = []
        for e in env:
            self._hist.append(e)
            self._count += 1
            if len(self._hist) > self.HIST:
                self._hist.pop(0)
            if self._count % 10 == 0 and len(self._hist) >= 100:
                self._floor, self._peak = np.percentile(self._hist, [25, 98])
            warm = self._count >= 200
            self.snr_ok = warm and self._peak > 5 * max(self._floor, 1e-9)
            thr = self._floor + 0.4 * (self._peak - self._floor)
            out.append(self._step(bool(self.snr_ok and e > thr)))
        return "".join(out)

    def _step(self, state: bool) -> str:
        # Filtro de transições curtas: o novo estado precisa durar 2 blocos (10 ms)
        if state != self._mark:
            if state == self._cand_state:
                self._cand_run += 1
            else:
                self._cand_state, self._cand_run = state, 1
            if self._cand_run >= 2:
                text = self._transition(state, self._run + self._cand_run - 1)
                self._mark, self._run, self._cand_run = state, self._cand_run, 0
                return text
            self._run += 1
            return ""
        self._cand_run = 0
        self._run += 1
        return self._silence_timeout() if not self._mark else ""

    def _transition(self, new_state: bool, run_blocks: int) -> str:
        ms = run_blocks * self.BLOCK_S * 1000
        if self._mark and not new_state:  # fim de marca
            self._classify_mark(ms)
            self._flushed = False
            return ""
        # fim de espaço, começa marca
        return self._classify_gap(ms) if not self._flushed or self._symbol else ""

    def _classify_mark(self, ms: float) -> None:
        if ms < 25:
            return
        if ms < 2 * self.dit_ms:
            self._symbol += "."
            self.dit_ms = float(np.clip(0.75 * self.dit_ms + 0.25 * ms, 20, 240))
        else:
            self._symbol += "-"
            self.dit_ms = float(np.clip(0.75 * self.dit_ms + 0.25 * (ms / 3), 20, 240))

    def _classify_gap(self, ms: float) -> str:
        if ms < 2 * self.dit_ms:
            return ""
        out = self._emit()
        if ms >= 5 * self.dit_ms:
            out += " "
        return out

    def _silence_timeout(self) -> str:
        ms = self._run * self.BLOCK_S * 1000
        if self._symbol and ms >= 2.5 * self.dit_ms:
            return self._emit()
        if not self._symbol and not self._flushed and ms >= 6 * self.dit_ms:
            self._flushed = True
            return " "
        return ""

    def _emit(self) -> str:
        sym, self._symbol = self._symbol, ""
        if not sym:
            return ""
        self._flushed = False
        return MORSE.get(sym, "*")
