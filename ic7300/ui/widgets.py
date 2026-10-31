"""Widgets de visualização: display de frequência, espectro, plano de bandas e waterfall."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from ..bands import USE_COLORS, USE_LABELS, BandPlan

pg.setConfigOptions(antialias=False, background="#10151c", foreground="#c8d0da")


class FrequencyDisplay(QtWidgets.QLabel):
    """Mostra a frequência em MHz; roda do mouse sintoniza; duplo clique digita."""
    tuned = QtCore.Signal(int)

    def __init__(self) -> None:
        super().__init__("14.074.000")
        self.freq = 14_074_000
        self.step = 500
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("font: 700 44pt 'Consolas'; color: #7CFC9A; background: #0a0f14; "
                           "border: 2px solid #26323f; border-radius: 8px; padding: 2px 14px;")
        self.setToolTip("Roda do mouse: sintonizar · Duplo clique: digitar a frequência (MHz)")

    def set_freq(self, hz: int) -> None:
        self.freq = hz
        s = f"{hz:,}".replace(",", ".")
        self.setText(s)

    def wheelEvent(self, e: QtGui.QWheelEvent) -> None:
        steps = 1 if e.angleDelta().y() > 0 else -1
        self.tuned.emit(self.freq + steps * self.step)

    def mouseDoubleClickEvent(self, e: QtGui.QMouseEvent) -> None:
        text, ok = QtWidgets.QInputDialog.getText(self, "Frequência", "Frequência em MHz (ex.: 7.074):",
                                                  text=f"{self.freq / 1e6:.6f}")
        if ok:
            try:
                self.tuned.emit(int(round(float(text.replace(",", ".")) * 1e6)))
            except ValueError:
                pass


class SpectrumView(pg.GraphicsLayoutWidget):
    """Espectro + faixa do plano de bandas + waterfall. Clique sintoniza."""
    clicked_freq = QtCore.Signal(int)
    WF_ROWS = 220

    def __init__(self, plan: BandPlan) -> None:
        super().__init__()
        self.plan = plan
        self.low, self.high = 14_049_000, 14_099_000
        self.audio_mode = False
        self._n = 475
        self._wf = np.zeros((self.WF_ROWS, self._n), dtype=np.float32)
        self._regions: list = []
        self._range_drawn: tuple[int, int] | None = None
        self.freq = 0

        self.p_spec = self.addPlot(row=0, col=0)
        self.p_spec.setMenuEnabled(False)
        self.p_spec.hideButtons()
        self.p_spec.setMouseEnabled(False, False)
        self.p_spec.showGrid(x=True, y=True, alpha=0.15)
        self.p_spec.setYRange(0, 160, padding=0)
        self.curve = self.p_spec.plot(pen=pg.mkPen("#ffd54a", width=1))
        self.curve.setFillLevel(0)
        self.curve.setBrush(pg.mkBrush(255, 213, 74, 40))
        self.marker = pg.InfiniteLine(angle=90, pen=pg.mkPen("#ff5252", width=1))
        self.p_spec.addItem(self.marker)

        self.p_band = self.addPlot(row=1, col=0)
        self.p_band.setMenuEnabled(False)
        self.p_band.hideButtons()
        self.p_band.setMouseEnabled(False, False)
        self.p_band.hideAxis("left")
        self.p_band.hideAxis("bottom")
        self.p_band.setYRange(0, 1, padding=0)
        self.p_band.setMaximumHeight(34)
        self.p_band.setXLink(self.p_spec)

        self.p_wf = self.addPlot(row=2, col=0)
        self.p_wf.setMenuEnabled(False)
        self.p_wf.hideButtons()
        self.p_wf.setMouseEnabled(False, False)
        self.p_wf.hideAxis("left")
        self.p_wf.setXLink(self.p_spec)
        self.img = pg.ImageItem()
        self.p_wf.addItem(self.img)
        cmap = pg.ColorMap([0, 0.25, 0.5, 0.75, 1.0],
                           [(0, 0, 20), (0, 40, 140), (0, 190, 190), (255, 230, 60), (255, 255, 255)])
        self.img.setLookupTable(cmap.getLookupTable(0.0, 1.0, 256))
        self.img.setLevels((0, 120))
        self.ci.layout.setRowStretchFactor(0, 4)
        self.ci.layout.setRowStretchFactor(2, 5)
        self.scene().sigMouseClicked.connect(self._on_click)
        self.set_range(self.low, self.high)

    def set_freq(self, hz: int) -> None:
        self.freq = hz
        if not self.audio_mode:
            self.marker.setPos(hz)

    def set_range(self, low: float, high: float, n: int | None = None) -> None:
        if n and n != self._n:
            self._n = n
            self._wf = np.zeros((self.WF_ROWS, n), dtype=np.float32)
        self.low, self.high = low, high
        self.p_spec.setXRange(low, high, padding=0)
        self.img.setRect(QtCore.QRectF(low, 0, high - low, self.WF_ROWS))
        self.p_wf.setYRange(0, self.WF_ROWS, padding=0)
        self._draw_bandplan()
        axis = self.p_spec.getAxis("bottom")
        axis.setTickSpacing(*self._tick_spacing(high - low))
        axis.setLabel("MHz" if not self.audio_mode else "Hz")
        axis.setScale(1e-6 if not self.audio_mode else 1.0)

    @staticmethod
    def _tick_spacing(span: float) -> tuple[float, float]:
        for major in (500, 1000, 2500, 5000, 10000, 25000, 50000, 100000, 250000):
            if span / major <= 8:
                return major, major / 5
        return 500000, 100000

    def set_audio_mode(self, on: bool) -> None:
        if on == self.audio_mode:
            return
        self.audio_mode = on
        self.marker.setVisible(not on)
        self.p_spec.setYRange(-100, 0, padding=0) if on else self.p_spec.setYRange(0, 160, padding=0)
        self.img.setLevels((-90, -30) if on else (0, 120))
        self._range_drawn = None

    def push_scope(self, values: bytes, low: int, high: int) -> None:
        arr = np.frombuffer(values, dtype=np.uint8).astype(np.float32)
        if (low, high, len(arr)) != (self.low, self.high, self._n):
            self.set_range(low, high, len(arr))
        self._push(arr, np.linspace(low, high, len(arr)))
        self.marker.setPos(self.freq)

    def push_audio(self, db: np.ndarray, freqs: np.ndarray) -> None:
        if (self.low, self.high) != (0, float(freqs[-1])) or len(db) != self._n:
            self.set_range(0, float(freqs[-1]), len(db))
        self._push(db.astype(np.float32), freqs)

    def _push(self, arr: np.ndarray, xs: np.ndarray) -> None:
        self.curve.setData(xs, arr)
        self._wf = np.roll(self._wf, -1, axis=0)
        self._wf[-1] = arr
        self.img.setImage(self._wf.T, autoLevels=False)

    def _draw_bandplan(self) -> None:
        if self._range_drawn == (self.low, self.high) and not self.audio_mode:
            return
        for r in self._regions:
            self.p_band.removeItem(r)
        self._regions.clear()
        self._range_drawn = (self.low, self.high)
        if self.audio_mode:
            return
        segs = [(s.start, s.stop, s.use, "") for s in self.plan.segments_in(int(self.low), int(self.high))]
        segs += [(o["start"], o["stop"], "BC", o["name"]) for o in self.plan.other_in(int(self.low), int(self.high))]
        for start, stop, use, name in segs:
            color = USE_COLORS.get(use, (110, 110, 110))
            reg = pg.LinearRegionItem((max(start, self.low), min(stop, self.high)), movable=False,
                                      brush=pg.mkBrush(*color, 170), pen=pg.mkPen(None))
            reg.setZValue(-5)
            self.p_band.addItem(reg)
            self._regions.append(reg)
            label = pg.TextItem(name or USE_LABELS.get(use, use), color="#0b0f14", anchor=(0.5, 0.5))
            label.setPos((max(start, self.low) + min(stop, self.high)) / 2, 0.5)
            self.p_band.addItem(label)
            self._regions.append(label)

    def _on_click(self, ev) -> None:
        pos = ev.scenePos()
        for p in (self.p_spec, self.p_wf, self.p_band):
            if p.sceneBoundingRect().contains(pos):
                x = p.vb.mapSceneToView(pos).x()
                if not self.audio_mode and self.low <= x <= self.high:
                    self.clicked_freq.emit(int(x))
                return
