"""SSTV: modos Martin M1/M2 e Scottie S1/S2 (gerador de áudio e decodificador contínuo com VIS)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

FS = 12000
F_SYNC, F_BLACK, F_WHITE = 1200.0, 1500.0, 2300.0
F_LEADER, F_VIS1, F_VIS0 = 1900.0, 1100.0, 1300.0


@dataclass(frozen=True)
class Mode:
    name: str
    vis: int
    width: int
    height: int
    scan_ms: float
    kind: str  # "martin" ou "scottie"

    def layout(self) -> list[tuple[str, float, float]]:
        """Segmentos de uma linha: ('tone', Hz, ms) ou ('scan', canal, ms), canais 0=G 1=B 2=R."""
        if self.kind == "martin":
            seg: list[tuple[str, float, float]] = [("tone", F_SYNC, 4.862), ("tone", F_BLACK, 0.572)]
            for ch in range(3):
                seg += [("scan", ch, self.scan_ms), ("tone", F_BLACK, 0.572)]
            return seg
        return [("tone", F_BLACK, 1.5), ("scan", 0, self.scan_ms), ("tone", F_BLACK, 1.5), ("scan", 1, self.scan_ms),
                ("tone", F_SYNC, 9.0), ("tone", F_BLACK, 1.5), ("scan", 2, self.scan_ms)]

    @property
    def line_ms(self) -> float:
        return sum(ms for _, _, ms in self.layout())

    @property
    def sync_ms(self) -> float:
        return 4.862 if self.kind == "martin" else 9.0

    @property
    def sync_offset_ms(self) -> float:
        """Onde está o pulso de sincronismo dentro da linha."""
        t = 0.0
        for kind, val, ms in self.layout():
            if kind == "tone" and val == F_SYNC:
                return t
            t += ms
        return 0.0

    @property
    def head_ms(self) -> float:
        """Scottie: sincronismo e pórtico inicial antes da primeira linha."""
        return 10.5 if self.kind == "scottie" else 0.0


MODES = {m.name: m for m in (
    Mode("Martin M1", 44, 320, 256, 146.432, "martin"),
    Mode("Martin M2", 40, 320, 256, 73.216, "martin"),
    Mode("Scottie S1", 60, 320, 256, 138.240, "scottie"),
    Mode("Scottie S2", 56, 320, 256, 88.064, "scottie"),
)}
_BY_VIS = {m.vis: m for m in MODES.values()}
_CH_TO_RGB = {0: 1, 1: 2, 2: 0}  # canal de varredura (G, B, R) -> índice RGB da imagem


def resize_nearest(img: np.ndarray, width: int, height: int) -> np.ndarray:
    ys = (np.arange(height) * img.shape[0] / height).astype(int)
    xs = (np.arange(width) * img.shape[1] / width).astype(int)
    return img[ys][:, xs]


def _vis_bits(code: int) -> list[float]:
    bits = [(code >> i) & 1 for i in range(7)]
    parity = sum(bits) % 2  # paridade par: o bit completa um número par de uns
    return [F_VIS1 if b else F_VIS0 for b in bits + [parity]]


def encode(image: np.ndarray, mode: Mode, fs: int = FS, amp: float = 0.5) -> np.ndarray:
    """Imagem RGB (uint8, qualquer tamanho) -> áudio SSTV com cabeçalho VIS, de fase contínua."""
    img = resize_nearest(np.asarray(image, dtype=np.uint8), mode.width, mode.height)
    plan: list[tuple[float, float]] = [(F_LEADER, 0.3), (F_SYNC, 0.01), (F_LEADER, 0.3), (F_SYNC, 0.03)]
    plan += [(f, 0.03) for f in _vis_bits(mode.vis)] + [(F_SYNC, 0.03)]
    if mode.kind == "scottie":
        plan += [(F_SYNC, 0.009), (F_BLACK, 0.0015)]
    parts: list[np.ndarray] = []
    t = 0.0
    for f, dur in plan:
        n = round((t + dur) * fs) - round(t * fs)
        parts.append(np.full(n, f))
        t += dur
    layout = mode.layout()
    for y in range(mode.height):
        for kind, val, ms in layout:
            n = round((t + ms / 1000) * fs) - round(t * fs)
            if kind == "tone":
                parts.append(np.full(n, val))
            else:
                px = img[y, :, _CH_TO_RGB[int(val)]].astype(float)
                idx = np.minimum((np.arange(n) * mode.width // max(n, 1)), mode.width - 1)
                parts.append(F_BLACK + (F_WHITE - F_BLACK) * px[idx] / 255)
            t += ms / 1000
    parts.append(np.full(round(0.1 * fs), F_BLACK))
    freq = np.concatenate(parts)
    phase = 2 * np.pi * np.cumsum(freq) / fs
    return (amp * np.sin(phase)).astype(np.float32)


class FmDemod:
    """Frequência instantânea (Hz) por mistura em 1900 Hz, filtro passa-baixas e derivada da fase."""

    def __init__(self, fs: int = FS, center: float = 1900.0, cutoff: float = 1500.0, taps: int = 65) -> None:
        n = np.arange(taps) - (taps - 1) / 2
        h = np.sinc(2 * cutoff / fs * n) * np.blackman(taps)
        self.h = h / h.sum()
        self.fs, self.center = fs, center
        self._tail = np.zeros(taps - 1, dtype=complex)
        self._n = 0
        self._last = 1.0 + 0j

    def process(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=np.float64)
        z = x * np.exp(-2j * np.pi * self.center * (np.arange(len(x)) + self._n) / self.fs)
        self._n += len(x)
        ext = np.concatenate([self._tail, z])
        y = np.convolve(ext, self.h, mode="valid")
        self._tail = ext[-(len(self.h) - 1):]
        prev = np.concatenate([[self._last], y[:-1]])
        self._last = y[-1] if len(y) else self._last
        return self.center + np.angle(y * np.conj(prev)) * self.fs / (2 * np.pi)


def _moving(x: np.ndarray, n: int) -> np.ndarray:
    return np.convolve(x, np.ones(n) / n, mode="same")


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    edges = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return list(zip(np.where(edges == 1)[0], np.where(edges == -1)[0]))


class SstvDecoder:
    """Decodificador contínuo. Inicia ao ouvir um cabeçalho VIS válido e emite linhas à medida que chegam."""

    def __init__(self, fs: int = FS, on_start: Optional[Callable[[Mode], None]] = None,
                 on_line: Optional[Callable[[int, np.ndarray], None]] = None,
                 on_image: Optional[Callable[[Mode, np.ndarray], None]] = None) -> None:
        self.fs = fs
        self.on_start = on_start or (lambda m: None)
        self.on_line = on_line or (lambda y, row: None)
        self.on_image = on_image or (lambda m, img: None)
        self.demod = FmDemod(fs)
        self.mode: Optional[Mode] = None
        self.image: Optional[np.ndarray] = None
        self.line = 0
        self._f = np.zeros(0)
        self._base = 0              # índice absoluto da primeira amostra de _f
        self._t0 = 0                # índice absoluto do início da linha 0
        self._drift = 0.0
        self._since_scan = 0

    def reset(self) -> None:
        self.mode, self.image, self.line = None, None, 0
        self._f, self._base, self._drift = np.zeros(0), self._base + len(self._f), 0.0

    def feed(self, samples: np.ndarray) -> None:
        f = self.demod.process(samples)
        self._f = np.concatenate([self._f, f])
        if self.mode is None:
            self._since_scan += len(f)
            if self._since_scan >= self.fs // 4:
                self._since_scan = 0
                self._scan_vis()
            keep = int(self.fs * 2.0)
            if len(self._f) > keep:
                self._base += len(self._f) - keep
                self._f = self._f[-keep:]
        else:
            self._decode_lines()

    # ---------------------------------------------------------------- VIS
    def _scan_vis(self) -> None:
        fs = self.fs
        s = _moving(self._f, max(3, int(0.002 * fs)))
        near = np.abs(s - F_LEADER) < 100
        long_runs = [r for r in _runs(near) if r[1] - r[0] >= 0.2 * fs]
        for (_a1, b1), (a2, b2) in zip(long_runs, long_runs[1:]):
            gap = (a2 - b1) / fs
            if not 0.004 <= gap <= 0.02:
                continue
            if abs(np.median(s[b1:a2]) - F_SYNC) > 120:
                continue
            need = b2 + int(0.3 * fs) + 2
            if need > len(s):
                return  # espera chegarem os bits
            centers = [b2 + int(fs * (0.03 * (i + 1) + 0.015)) for i in range(9)]
            vals = [float(np.median(s[c - 8:c + 9])) for c in centers]
            bits = [1 if v < 1200 else 0 for v in vals[:8]]
            if sum(bits) % 2 != 0 or abs(vals[8] - F_SYNC) > 120:
                continue
            code = sum(b << i for i, b in enumerate(bits[:7]))
            mode = _BY_VIS.get(code)
            if mode is None:
                continue
            self.mode, self.line, self._drift = mode, 0, 0.0
            self.image = np.zeros((mode.height, mode.width, 3), dtype=np.uint8)
            self._t0 = self._base + b2 + int(0.3 * fs) + int(mode.head_ms / 1000 * fs)
            self.on_start(mode)
            self._decode_lines()
            return

    # ---------------------------------------------------------------- linhas
    def _slice(self, start: int, stop: int) -> Optional[np.ndarray]:
        a, b = start - self._base, stop - self._base
        if a < 0 or b > len(self._f):
            return None
        return self._f[a:b]

    def _decode_lines(self) -> None:
        mode, fs = self.mode, self.fs
        assert mode is not None and self.image is not None
        line_n = mode.line_ms / 1000 * fs
        while self.line < mode.height:
            nominal = self._t0 + self.line * line_n + self._drift
            end = nominal + line_n + 0.012 * fs
            if end - self._base > len(self._f):
                break
            start = self._refine(nominal, mode)
            row = self._read_line(start, mode)
            if row is None:
                self._finish(abort=True)
                return
            self.image[self.line] = row
            self.on_line(self.line, row)
            self.line += 1
        if self.line >= mode.height:
            self._finish()
        else:  # descarta o que já foi usado
            drop = int(self._t0 + self.line * line_n + self._drift - 0.05 * fs) - self._base
            if drop > 0:
                self._f = self._f[drop:]
                self._base += drop

    def _refine(self, nominal: float, mode: Mode) -> float:
        """Procura o pulso de 1200 Hz perto do esperado e devolve o início real da linha (amostras absolutas)."""
        fs = self.fs
        off = mode.sync_offset_ms / 1000 * fs
        sync_n = mode.sync_ms / 1000 * fs
        win = int(0.006 * fs)
        a, b = int(nominal + off - win - sync_n), int(nominal + off + win + 2 * sync_n)
        seg = self._slice(a, b)
        if seg is None or len(seg) < 8:
            return nominal
        s = _moving(seg, max(3, int(0.001 * fs)))
        runs = [r for r in _runs(np.abs(s - F_SYNC) < 110) if r[1] - r[0] >= 0.5 * sync_n]
        if not runs:
            return nominal
        r0, r1 = max(runs, key=lambda r: r[1] - r[0])
        center = a + (r0 + r1) / 2
        start = center - sync_n / 2 - off
        if abs(start - nominal) < 0.004 * fs:
            self._drift += 0.5 * (start - nominal)
            return start
        return nominal

    def _read_line(self, start: float, mode: Mode) -> Optional[np.ndarray]:
        fs = self.fs
        channels: dict[int, np.ndarray] = {}
        t = start
        for kind, val, ms in mode.layout():
            n = ms / 1000 * fs
            if kind == "scan":
                seg = self._slice(int(round(t)), int(round(t + n)))
                if seg is None or len(seg) < mode.width // 2:
                    return None
                edges = np.linspace(0, len(seg), mode.width + 1)
                px = (edges[1] - edges[0])
                lo = np.clip((edges[:-1] + 0.2 * px).astype(int), 0, len(seg) - 1)
                hi = np.clip((edges[1:] - 0.2 * px).astype(int), 0, len(seg))
                hi = np.maximum(hi, lo + 1)
                cs = np.concatenate([[0], np.cumsum(seg)])
                mean = (cs[hi] - cs[lo]) / (hi - lo)
                channels[int(val)] = np.clip((mean - F_BLACK) / (F_WHITE - F_BLACK) * 255, 0, 255)
            t += n
        if len(channels) < 3:
            return None
        return np.stack([channels[2], channels[0], channels[1]], axis=1).astype(np.uint8)  # R, G, B

    def _finish(self, abort: bool = False) -> None:
        mode, image = self.mode, self.image
        self.mode, self.image, self.line = None, None, 0
        self._base += len(self._f)
        self._f = np.zeros(0)
        if not abort and mode is not None and image is not None:
            self.on_image(mode, image)
