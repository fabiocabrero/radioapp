"""Espectro de áudio (fallback quando o scope do rádio não está disponível)."""
from __future__ import annotations

import numpy as np


class AudioSpectrum:
    def __init__(self, fs: int = 48000, size: int = 4096, max_hz: float = 4000) -> None:
        self.fs, self.size = fs, size
        self._win = np.hanning(size)
        self._buf = np.zeros(0)
        self._bins = int(max_hz / (fs / size))
        self.freqs = np.arange(self._bins) * fs / size

    def push(self, samples: np.ndarray) -> np.ndarray | None:
        """Devolve uma linha em dB (0..4 kHz) quando há amostras suficientes."""
        self._buf = np.concatenate([self._buf, samples])[-self.size * 2:]
        if len(self._buf) < self.size:
            return None
        seg = self._buf[-self.size:] * self._win
        mag = np.abs(np.fft.rfft(seg))[: self._bins] / self.size
        return 20 * np.log10(mag + 1e-9)
