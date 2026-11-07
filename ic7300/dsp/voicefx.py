"""Efeitos de voz em tempo real (numpy puro): equalizador, porta de ruído, compressor, limitador, eco e reverb.

Processa blocos mono de 48 kHz. Para SSB o que mais melhora a compreensão é: cortar graves e agudos fora da faixa útil,
realçar a presença (2 a 3 kHz) e comprimir para elevar a potência média. Eco e reverb prejudicam a compreensão em
transmissão: servem para testes e para uso local; os predefinidos de TX não os usam.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields

import numpy as np

FS = 48000
_CHUNK = 128  # menor que qualquer atraso usado abaixo


@dataclass
class FxSettings:
    hp_hz: float = 80.0            # corte de graves
    band_on: bool = False          # limita a faixa de voz (SSB)
    band_lo: float = 300.0
    band_hi: float = 2800.0
    presence_db: float = 0.0       # realce de presença
    presence_hz: float = 2500.0
    gate_db: float = -90.0         # porta de ruído (-90 = desligada)
    comp: float = 0.0              # compressão 0 a 100
    echo_mix: float = 0.0          # 0 a 100
    echo_ms: float = 280.0
    echo_fb: float = 35.0          # realimentação (%)
    reverb_mix: float = 0.0        # 0 a 100
    reverb_size: float = 50.0      # 0 a 100
    out_db: float = 0.0
    ceiling: float = 0.9           # teto do limitador (0 a 1)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FxSettings":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (d or {}).items() if k in names})


PRESETS_TX: dict[str, FxSettings] = {
    "Natural (sem efeitos)": FxSettings(hp_hz=60),
    "Compreensão DX": FxSettings(hp_hz=250, band_on=True, band_lo=300, band_hi=2700, presence_db=5, comp=70, gate_db=-55, out_db=1),
    "Locutor": FxSettings(hp_hz=90, presence_db=3, comp=45, gate_db=-60, reverb_mix=0),
    "Conversa local (leve)": FxSettings(hp_hz=100, presence_db=2, comp=25),
    "Eco divertido": FxSettings(hp_hz=100, comp=25, echo_mix=35, echo_ms=320, echo_fb=40),
    "Estúdio (reverb leve)": FxSettings(hp_hz=90, presence_db=2, comp=35, reverb_mix=18, reverb_size=45),
}
PRESETS_RX: dict[str, FxSettings] = {
    "Natural": FxSettings(hp_hz=40),
    "Voz clara": FxSettings(hp_hz=250, band_on=True, band_lo=250, band_hi=3000, presence_db=4, comp=50, gate_db=-60),
    "Sinal fraco": FxSettings(hp_hz=350, band_on=True, band_lo=400, band_hi=2600, presence_db=6, comp=75, gate_db=-50, out_db=3),
}


def design_eq(s: FxSettings, sr: int = FS, taps: int = 255) -> np.ndarray:
    """FIR de fase linear a partir da resposta desejada (graves, faixa de voz e realce de presença)."""
    n = 2048
    f = np.fft.rfftfreq(n, 1 / sr)
    f[0] = 1e-3
    h = 1.0 / np.sqrt(1.0 + (max(s.hp_hz, 1.0) / f) ** 4)
    if s.band_on:
        h *= 1.0 / np.sqrt(1.0 + (max(s.band_lo, 1.0) / f) ** 8)
        h *= 1.0 / np.sqrt(1.0 + (f / max(s.band_hi, 1.0)) ** 8)
    if s.presence_db:
        peak = 10 ** (s.presence_db / 20.0) - 1.0
        h *= 1.0 + peak * np.exp(-0.5 * (np.log2(f / max(s.presence_hz, 1.0)) / 0.55) ** 2)
    ir = np.fft.fftshift(np.fft.irfft(h, n))
    mid = n // 2
    ir = ir[mid - taps // 2: mid + taps // 2 + 1] * np.hamming(taps)
    return ir.astype(np.float32)


class _Delay:
    """Linha de atraso circular; processa trechos de no máximo `n` amostras."""

    def __init__(self, n: int) -> None:
        self.n = max(int(n), _CHUNK + 1)
        self.buf = np.zeros(self.n, dtype=np.float32)
        self.pos = 0

    def idx(self, m: int) -> np.ndarray:
        i = (self.pos + np.arange(m)) % self.n
        self.pos = (self.pos + m) % self.n
        return i


class VoiceFX:
    def __init__(self, settings: FxSettings | None = None, sr: int = FS) -> None:
        self.sr = sr
        self.s = settings or FxSettings()
        self.in_db = self.out_db = -90.0
        self.gr_db = 0.0
        self._gain_db = 0.0
        self._tail = np.zeros(0, dtype=np.float32)
        self._build()

    def configure(self, settings: FxSettings) -> None:
        self.s = settings
        self._build()

    def _build(self) -> None:
        s = self.s
        self._fir = design_eq(s, self.sr)
        if len(self._tail) != len(self._fir) - 1:
            self._tail = np.zeros(len(self._fir) - 1, dtype=np.float32)
        self._echo = _Delay(s.echo_ms * self.sr / 1000.0)
        k = self.sr / 44100.0
        scale = 0.6 + s.reverb_size / 100.0 * 0.9
        self._combs = [(_Delay(int(d * k * scale)), g) for d, g in ((1557, 0.80), (1617, 0.79), (1491, 0.77), (1422, 0.76))]
        self._aps = [_Delay(int(d * k)) for d in (225, 556)]

    # ---- etapas ----
    def _eq(self, x: np.ndarray) -> np.ndarray:
        ext = np.concatenate([self._tail, x])
        y = np.convolve(ext, self._fir, mode="valid")  # len(x) amostras
        self._tail = ext[-(len(self._fir) - 1):]
        return y.astype(np.float32)  # atraso fixo de 127 amostras (2,6 ms), sem importância para voz

    def _dynamics(self, x: np.ndarray) -> np.ndarray:
        s = self.s
        sub = max(1, int(self.sr * 0.005))
        n_sub = len(x) // sub
        if n_sub == 0:
            return x
        frames = x[: n_sub * sub].reshape(n_sub, sub)
        lvl = 10 * np.log10(np.mean(frames ** 2, axis=1) + 1e-12)
        thr = -12.0 - s.comp * 0.25
        ratio = 1.0 + s.comp * 0.06
        makeup = (-thr) * (1 - 1 / ratio) * 0.55 if s.comp > 0 else 0.0
        att = np.exp(-sub / (0.006 * self.sr))
        rel = np.exp(-sub / (0.18 * self.sr))
        gains = np.empty(n_sub)
        g = self._gain_db
        for i in range(n_sub):
            target = 0.0
            if s.comp > 0 and lvl[i] > thr:
                target = (thr - lvl[i]) * (1 - 1 / ratio)
            if lvl[i] < s.gate_db:
                target = min(target, -25.0)
            coef = att if target < g else rel  # ataque quando precisa reduzir mais
            g = coef * g + (1 - coef) * target
            gains[i] = g
        self._gain_db = g
        self.gr_db = float(-min(gains.min(), 0.0))
        pos = (np.arange(n_sub) + 0.5) * sub
        full = np.interp(np.arange(len(x)), pos, gains + makeup)
        return x * (10 ** (full / 20.0)).astype(np.float32)

    def _echo_fx(self, x: np.ndarray) -> np.ndarray:
        s, d = self.s, self._echo
        out = np.empty_like(x)
        fb = s.echo_fb / 100.0 * 0.85
        for a in range(0, len(x), _CHUNK):
            c = x[a:a + _CHUNK]
            i = d.idx(len(c))
            delayed = d.buf[i]
            d.buf[i] = c + fb * delayed
            out[a:a + len(c)] = c + s.echo_mix / 100.0 * delayed
        return out

    def _reverb_fx(self, x: np.ndarray) -> np.ndarray:
        s = self.s
        wet = np.empty_like(x)
        for a in range(0, len(x), _CHUNK):
            c = x[a:a + _CHUNK]
            acc = np.zeros_like(c)
            for d, g in self._combs:
                i = d.idx(len(c))
                out = d.buf[i]
                d.buf[i] = c + g * out
                acc += out
            acc *= 0.25
            for d in self._aps:
                i = d.idx(len(acc))
                buffered = d.buf[i]
                y = -0.5 * acc + buffered
                d.buf[i] = acc + 0.5 * buffered
                acc = y
            wet[a:a + len(c)] = acc
        return x + s.reverb_mix / 100.0 * 1.6 * wet

    def process(self, block: np.ndarray) -> np.ndarray:
        s = self.s
        x = np.asarray(block, dtype=np.float32)
        if x.size == 0:
            return x
        self.in_db = float(10 * np.log10(np.mean(x ** 2) + 1e-12))
        y = self._eq(x)
        y = self._dynamics(y)
        if s.echo_mix > 0:
            y = self._echo_fx(y)
        if s.reverb_mix > 0:
            y = self._reverb_fx(y)
        y = y * np.float32(10 ** (s.out_db / 20.0))
        ceil = np.float32(max(0.05, min(1.0, s.ceiling)))
        y = ceil * np.tanh(y / ceil)  # limitador suave
        self.out_db = float(10 * np.log10(np.mean(y ** 2) + 1e-12))
        return y.astype(np.float32)

    def reset(self) -> None:
        self._gain_db = 0.0
        self._tail[:] = 0
        self._build()


def process_all(samples: np.ndarray, settings: FxSettings, block: int = 2400) -> np.ndarray:
    """Aplica os efeitos a uma gravação inteira (usado ao enviar mensagens gravadas)."""
    fx = VoiceFX(settings)
    parts = [fx.process(samples[i:i + block]) for i in range(0, len(samples), block)]
    # cauda para o eco e o reverb terminarem
    tail = int((settings.echo_ms * 3 if settings.echo_mix else 0) + (900 if settings.reverb_mix else 0)) * FS // 1000
    if tail:
        parts += [fx.process(np.zeros(block, np.float32)) for _ in range(max(1, tail // block))]
    return np.concatenate(parts) if parts else samples
