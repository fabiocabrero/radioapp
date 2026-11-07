"""Detector de voz para o canal de recepção: energia na faixa de voz acima do ruído de fundo e modulação típica de fala.

Uma portadora ou um tom constante têm energia estável e não contam como voz; ruído estável também não. A fala oscila
(sílabas, 3 a 8 vezes por segundo), então a variação de nível entre quadros de 20 ms é grande; num degrau (portadora que
surge) só um quadro varia, e a mediana ignora isso.
"""
from __future__ import annotations

from collections import deque

import numpy as np

FS = 48000
FRAME = 960  # 20 ms


class VoiceDetector:
    def __init__(self, margin_db: float = 9.0, hang_s: float = 1.0, min_modulation: float = 2.0, sr: int = FS) -> None:
        self.margin_db = margin_db
        self.hang_s = hang_s
        self.min_modulation = min_modulation
        self.sr = sr
        self.frame = int(sr * 0.02)
        freqs = np.fft.rfftfreq(self.frame, 1 / sr)
        self._band = (freqs >= 300) & (freqs <= 3000)
        self._win = np.hanning(self.frame).astype(np.float32)
        self._buf = np.zeros(0, dtype=np.float32)
        self._levels: deque[float] = deque(maxlen=25)  # 0,5 s, em dB
        self._flags: deque[bool] = deque(maxlen=10)    # 0,2 s
        self.floor_db: float | None = None
        self.level_db = -90.0
        self.active = False
        self._last_voice = -1e9
        self._t = 0.0

    def reset(self) -> None:
        self._buf = np.zeros(0, dtype=np.float32)
        self._levels.clear()
        self._flags.clear()
        self.floor_db = None
        self.active = False
        self._last_voice = -1e9

    def feed(self, samples: np.ndarray) -> bool:
        self._buf = np.concatenate([self._buf, np.asarray(samples, dtype=np.float32)])
        while len(self._buf) >= self.frame:
            self._frame(self._buf[:self.frame])
            self._buf = self._buf[self.frame:]
            self._t += self.frame / self.sr
        return self.active

    def _frame(self, x: np.ndarray) -> None:
        spec = np.abs(np.fft.rfft(x * self._win)) ** 2
        e = float(np.sum(spec[self._band])) / self.frame + 1e-14
        db = 10 * np.log10(e)
        self.level_db = db
        if self.floor_db is None:
            self.floor_db = db
        if db < self.floor_db + 3:
            self.floor_db = 0.9 * self.floor_db + 0.1 * db  # acompanha o ruído quando cai
        else:
            self.floor_db += 0.004  # sobe devagar: sinal estável vira "fundo"
        self._levels.append(db)
        loud = db > self.floor_db + self.margin_db
        speechlike = False
        if len(self._levels) >= 12:  # mediana da variação entre quadros: fala ~3 a 6 dB, ruído ~0,8, portadora ~0
            speechlike = float(np.median(np.abs(np.diff(self._levels)))) > self.min_modulation
        self._flags.append(loud and speechlike)
        if sum(self._flags) >= 4:
            self._last_voice = self._t
        self.active = (self._t - self._last_voice) < self.hang_s
