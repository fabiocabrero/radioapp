"""Aba Mapa / Propagação: mapa-múndi com dia/noite, estações e relatos, mais índices solares por banda."""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from .. import geo, mapdata, propagation
from ..bands import BandPlan
from ..dxcc import Cty

_GRID_WORD = re.compile(r"^[A-R]{2}[0-9]{2}([A-X]{2})?$", re.I)
COND_COLORS = {"Good": "#2e7d32", "Fair": "#f9a825", "Poor": "#c62828"}
LAYERS = {
    "spots": ("Spots (DX Cluster / POTA)", (255, 213, 74)),
    "ft8": ("Estações FT8/FT4 decodificadas", (120, 200, 255)),
    "psk_tx": ("PSK Reporter: quem me ouve", (90, 220, 120)),
    "psk_rx": ("PSK Reporter: quem eu ouço", (255, 140, 60)),
}


@dataclass
class Point:
    lat: float
    lon: float
    label: str
    stamp: float


class MapTab(QtWidgets.QWidget):
    _solar_ready = QtCore.Signal(object)
    _psk_ready = QtCore.Signal(object, bool)
    _status = QtCore.Signal(str)

    def __init__(self, plan: BandPlan, cty: Cty) -> None:
        super().__init__()
        self.plan, self.cty = plan, cty
        self.home: Optional[tuple[float, float]] = None
        self.call = ""
        self.solar: Optional[propagation.SolarData] = None
        self.points: dict[str, list[Point]] = {k: [] for k in LAYERS}
        self.target: Optional[tuple[float, float]] = None
        self._psk_last = 0.0

        lay = QtWidgets.QHBoxLayout(self)
        self.plot = pg.PlotWidget(background="#0b1220")
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        self.plot.setAspectLocked(True)
        self.plot.showAxis("left", False)
        self.plot.showAxis("bottom", False)
        vb = self.plot.getPlotItem().vb
        vb.setLimits(xMin=-180, xMax=180, yMin=-90, yMax=90)
        vb.disableAutoRange()
        self._zoomed = False
        vb.sigRangeChangedManually.connect(lambda *_: setattr(self, "_zoomed", True))
        self.fit_world()
        lay.addWidget(self.plot, 4)

        self.night = pg.ImageItem()
        self.night.setZValue(-20)
        self.plot.addItem(self.night)
        self._grid_curve = self._line_item(self._graticule(), "#22304a", 1, -15)
        self._coast = self._line_item(mapdata.load_lines("coast"), "#6b7a90", 1, -10)
        self._borders = self._line_item(mapdata.load_lines("borders"), "#2e3b50", 1, -12)
        self._routes = pg.PlotDataItem(pen=pg.mkPen((255, 255, 255, 70), width=1), connect="finite")
        self._routes.setZValue(5)
        self.plot.addItem(self._routes)
        self._gc = pg.PlotDataItem(pen=pg.mkPen("#ff5252", width=2), connect="finite")
        self._gc.setZValue(8)
        self.plot.addItem(self._gc)
        self.scatter: dict[str, pg.ScatterPlotItem] = {}
        for key, (_, color) in LAYERS.items():
            s = pg.ScatterPlotItem(size=9, pen=pg.mkPen("#0b1220"), brush=pg.mkBrush(*color), hoverable=True,
                                   tip=lambda x, y, data, **_: data)
            s.setZValue(10)
            self.plot.addItem(s)
            self.scatter[key] = s
        self.home_item = pg.ScatterPlotItem(size=16, symbol="star", pen=pg.mkPen("w"), brush=pg.mkBrush("#ff5252"))
        self.home_item.setZValue(12)
        self.plot.addItem(self.home_item)
        self.plot.scene().sigMouseClicked.connect(self._on_click)

        side = QtWidgets.QVBoxLayout()
        lay.addLayout(side, 1)
        self.lbl_solar = QtWidgets.QLabel("Índices solares: carregando…")
        self.lbl_solar.setWordWrap(True)
        self.lbl_solar.setStyleSheet("font: 600 10pt")
        side.addWidget(self.lbl_solar)
        self.tbl_cond = QtWidgets.QTableWidget(4, 3)
        self.tbl_cond.setHorizontalHeaderLabels(["Bandas", "Dia", "Noite"])
        self.tbl_cond.verticalHeader().setVisible(False)
        self.tbl_cond.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_cond.setMaximumHeight(150)
        self.tbl_cond.horizontalHeader().setStretchLastSection(True)
        for r, group in enumerate(propagation.BAND_GROUPS):
            self.tbl_cond.setItem(r, 0, QtWidgets.QTableWidgetItem(group))
        side.addWidget(self.tbl_cond)
        self.lbl_now = QtWidgets.QLabel("")
        self.lbl_now.setWordWrap(True)
        side.addWidget(self.lbl_now)

        self.checks: dict[str, QtWidgets.QCheckBox] = {}
        for key, (name, color) in LAYERS.items():
            cb = QtWidgets.QCheckBox(name)
            cb.setChecked(True)
            cb.setStyleSheet(f"QCheckBox{{color: rgb{color}}}")
            cb.toggled.connect(lambda _=False: self._refresh_layers())
            side.addWidget(cb)
            self.checks[key] = cb
        self.chk_night = QtWidgets.QCheckBox("Dia / noite (terminador)")
        self.chk_night.setChecked(True)
        self.chk_night.toggled.connect(self._update_night)
        side.addWidget(self.chk_night)

        row = QtWidgets.QHBoxLayout()
        self.btn_fit = QtWidgets.QPushButton("Reenquadrar")
        self.btn_solar = QtWidgets.QPushButton("Atualizar índices")
        self.btn_psk = QtWidgets.QPushButton("Atualizar PSK Reporter")
        row.addWidget(self.btn_fit)
        row.addWidget(self.btn_solar)
        row.addWidget(self.btn_psk)
        side.addLayout(row)
        self.tbl_psk = QtWidgets.QTableWidget(0, 3)
        self.tbl_psk.setHorizontalHeaderLabels(["Banda", "Relatos", "Mais longe"])
        self.tbl_psk.verticalHeader().setVisible(False)
        self.tbl_psk.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_psk.horizontalHeader().setStretchLastSection(True)
        side.addWidget(self.tbl_psk, 1)
        self.lbl_target = QtWidgets.QLabel("Clique no mapa: distância e azimute a partir do seu local.")
        self.lbl_target.setWordWrap(True)
        side.addWidget(self.lbl_target)
        self.lbl_info = QtWidgets.QLabel("Fontes: N0NBH/HamQSL (índices), PSK Reporter (relatos), Natural Earth (mapa).")
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setStyleSheet("color:#8a97a8; font-size:8pt")
        side.addWidget(self.lbl_info)

        self.btn_fit.clicked.connect(self.fit_world)
        self.btn_solar.clicked.connect(self.refresh_solar)
        self.btn_psk.clicked.connect(self.refresh_psk)
        self._solar_ready.connect(self._on_solar)
        self._psk_ready.connect(self._on_psk)
        self._status.connect(self.lbl_info.setText)
        self.timer = QtCore.QTimer(self, interval=60_000, timeout=self._minute)
        self.timer.start()
        self._ticks = 0
        self._update_night()
        QtCore.QTimer.singleShot(500, self.refresh_solar)

    # ---------------------------------------------------------------- vista
    def fit_world(self) -> None:
        self._zoomed = False
        vb = self.plot.getPlotItem().vb
        vb.setLimits(xMin=None, xMax=None, yMin=None, yMax=None)
        vb.setRange(xRange=(-180, 180), yRange=(-90, 90), padding=0)
        vb.setLimits(xMin=-180, xMax=180, yMin=-90, yMax=90)
        self._zoomed = False

    def showEvent(self, e: QtGui.QShowEvent) -> None:
        super().showEvent(e)
        QtCore.QTimer.singleShot(0, self.fit_world)

    def resizeEvent(self, e: QtGui.QResizeEvent) -> None:
        super().resizeEvent(e)
        if not self._zoomed:
            QtCore.QTimer.singleShot(0, self.fit_world)

    # ---------------------------------------------------------------- desenho
    def _line_item(self, xy: tuple[np.ndarray, np.ndarray], color: str, width: int, z: int) -> pg.PlotDataItem:
        item = pg.PlotDataItem(xy[0], xy[1], pen=pg.mkPen(color, width=width), connect="finite")
        item.setZValue(z)
        self.plot.addItem(item)
        return item

    @staticmethod
    def _graticule() -> tuple[np.ndarray, np.ndarray]:
        xs: list[float] = []
        ys: list[float] = []
        for lon in range(-180, 181, 30):
            xs += [lon, lon, np.nan]
            ys += [-90, 90, np.nan]
        for lat in range(-60, 61, 30):
            xs += [-180, 180, np.nan]
            ys += [lat, lat, np.nan]
        return np.array(xs), np.array(ys)

    def _update_night(self) -> None:
        self.night.setVisible(self.chk_night.isChecked())
        dark = mapdata.darkness_grid(datetime.now(timezone.utc))
        rgba = np.zeros(dark.shape + (4,), dtype=np.uint8)
        rgba[..., 0], rgba[..., 1], rgba[..., 2] = 0, 0, 20
        rgba[..., 3] = (dark * 170).astype(np.uint8)
        self.night.setImage(np.transpose(rgba, (1, 0, 2))[:, ::-1], autoLevels=False)
        self.night.setRect(QtCore.QRectF(-181, -91, 362, 182))  # pixel de 2° centrado em cada grau par
        self._update_now_label()

    def _minute(self) -> None:
        self._ticks += 1
        self._update_night()
        cutoff = time.time() - 3600
        for pts in self.points.values():
            pts[:] = [p for p in pts if p.stamp > cutoff]
        self._refresh_layers()
        if self._ticks % 15 == 0:
            self.refresh_solar()

    def _refresh_layers(self) -> None:
        routes_x: list[float] = []
        routes_y: list[float] = []
        for key, s in self.scatter.items():
            on = self.checks[key].isChecked()
            pts = self.points[key] if on else []
            s.setData(x=[p.lon for p in pts], y=[p.lat for p in pts], data=[p.label for p in pts])
            if on and key.startswith("psk") and self.home:
                for p in pts:
                    lon, lat = mapdata.great_circle(self.home[0], self.home[1], p.lat, p.lon, 40)
                    routes_x += list(lon) + [np.nan]
                    routes_y += list(lat) + [np.nan]
        self._routes.setData(routes_x, routes_y)
        if self.home:
            self.home_item.setData(x=[self.home[1]], y=[self.home[0]])

    # ---------------------------------------------------------------- API
    def set_home(self, lat: float, lon: float, call: str) -> None:
        self.home = (lat, lon) if (lat or lon) else None
        self.call = call
        self.home_item.setData(x=[lon] if self.home else [], y=[lat] if self.home else [])
        self._update_now_label()
        self._refresh_layers()

    def add_point(self, layer: str, lat: float, lon: float, label: str) -> None:
        pts = self.points[layer]
        pts[:] = [p for p in pts if p.label != label]
        pts.append(Point(lat, lon, label, time.time()))
        del pts[:-400]
        self._refresh_layers()

    def add_spot(self, call: str, freq: int, info: str, lat: Optional[float] = None, lon: Optional[float] = None) -> None:
        if lat is None or lon is None:
            ent = self.cty.lookup(call)
            if not ent:
                return
            lat, lon = ent.lat, ent.lon
        self.add_point("spots", lat, lon, f"{call}  {freq / 1e3:.1f} kHz  {info}".strip())

    def add_ft_message(self, text: str, snr: int, freq: int) -> None:
        words = text.replace("<", "").replace(">", "").split()
        calls = [w for w in words if any(c.isdigit() for c in w) and any(c.isalpha() for c in w) and not _GRID_WORD.match(w)
                 and w not in ("RR73", "RRR", "73") and not re.match(r"^R?[+-]\d{2}$", w)]
        if not calls:
            return
        # "CQ [DX] CALL GRID" -> quem chama é o último indicativo; "PARA DE ..." -> quem fala é o segundo
        sender = calls[-1] if words[0] == "CQ" or len(calls) < 2 else calls[1]
        grid = next((w for w in reversed(words) if _GRID_WORD.match(w) and w.upper() != "RR73"), None)
        try:
            lat, lon = geo.grid_to_latlon(grid) if grid else (None, None)
        except ValueError:
            lat = lon = None
        if lat is None:
            ent = self.cty.lookup(sender)
            if not ent:
                return
            lat, lon = ent.lat, ent.lon
        self.add_point("ft8", lat, lon, f"{sender}  {snr:+d} dB  {text}")

    # ---------------------------------------------------------------- propagação
    def refresh_solar(self) -> None:
        def work() -> None:
            try:
                self._solar_ready.emit(propagation.fetch_solar())
            except Exception as exc:
                self._status.emit(f"Índices solares: {exc}")

        threading.Thread(target=work, daemon=True).start()

    def _on_solar(self, s: propagation.SolarData) -> None:
        self.solar = s
        self.lbl_solar.setText(f"SFI {s.sfi} · A {s.a_index} · K {s.k_index} · Manchas {s.sunspots}\n"
                               f"Raios-X {s.xray} · Vento solar {s.solar_wind:.0f} km/s · Geomag: {s.geomag}\n"
                               f"Atualizado: {s.updated}")
        for r, group in enumerate(propagation.BAND_GROUPS):
            for c, period in ((1, "day"), (2, "night")):
                cond = s.bands.get((group, period), "")
                item = QtWidgets.QTableWidgetItem(propagation.CONDITION_PT.get(cond, cond))
                item.setBackground(QtGui.QColor(COND_COLORS.get(cond, "#444")))
                self.tbl_cond.setItem(r, c, item)
        self._update_now_label()

    def _update_now_label(self) -> None:
        if not self.home:
            self.lbl_now.setText("Defina seu local (aba Local / GPS) para ver se é dia ou noite aí.")
            return
        day = propagation.is_daytime(*self.home)
        txt = f"No seu local agora: {'DIA' if day else 'NOITE'}."
        if self.solar:
            good = [b for b in self.plan.band_names() if self.solar.condition_for(b, day) == "Good"]
            fair = [b for b in self.plan.band_names() if self.solar.condition_for(b, day) == "Fair"]
            txt += f"\nBoas: {', '.join(good) or '—'}\nRegulares: {', '.join(fair) or '—'}"
        self.lbl_now.setText(txt)

    def refresh_psk(self) -> None:
        if not self.call:
            self._status.emit("Informe seu indicativo na aba Local / GPS para usar o PSK Reporter.")
            return
        if time.time() - self._psk_last < 300:
            self._status.emit("PSK Reporter: aguarde 5 min entre consultas (limite do serviço).")
            return
        self._psk_last = time.time()
        call = self.call

        def work() -> None:
            try:
                self._psk_ready.emit(propagation.fetch_psk(call, True), True)
                self._psk_ready.emit(propagation.fetch_psk(call, False), False)
            except Exception as exc:
                self._status.emit(f"PSK Reporter: {exc}")

        threading.Thread(target=work, daemon=True).start()

    def _on_psk(self, reports: list[propagation.Report], heard_me: bool) -> None:
        layer = "psk_tx" if heard_me else "psk_rx"
        self.points[layer].clear()
        stats: dict[str, list[float]] = getattr(self, "_stats", {})
        stats = {k: v for k, v in stats.items() if not k.endswith("|" + layer)}
        for rep in reports:
            pos = propagation.report_endpoint(rep, self.call)
            if not pos:
                continue
            other = rep.receiver if heard_me else rep.sender
            self.points[layer].append(Point(pos[0], pos[1], f"{other}  {rep.snr:+d} dB  {rep.freq / 1e6:.3f} MHz {rep.mode}", time.time()))
            band = self.plan.band_for(rep.freq) or f"{rep.freq / 1e6:.1f} MHz"
            dist = geo.distance_bearing(self.home[0], self.home[1], pos[0], pos[1])[0] if self.home else 0.0
            stats.setdefault(f"{band}|{layer}", []).append(dist)
        self._stats = stats
        bands: dict[str, list[float]] = {}
        for k, v in stats.items():
            bands.setdefault(k.split("|")[0], []).extend(v)
        self.tbl_psk.setRowCount(len(bands))
        for r, (band, dists) in enumerate(sorted(bands.items(), key=lambda kv: -len(kv[1]))):
            for c, v in enumerate((band, str(len(dists)), f"{max(dists):.0f} km" if max(dists) else "—")):
                self.tbl_psk.setItem(r, c, QtWidgets.QTableWidgetItem(v))
        self._refresh_layers()

    # ---------------------------------------------------------------- interação
    def _on_click(self, ev) -> None:
        pos = self.plot.getPlotItem().vb.mapSceneToView(ev.scenePos())
        lon, lat = pos.x(), pos.y()
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            return
        self.target = (lat, lon)
        grid = geo.latlon_to_grid(lat, lon)
        if self.home:
            d, b = geo.distance_bearing(self.home[0], self.home[1], lat, lon)
            glon, glat = mapdata.great_circle(self.home[0], self.home[1], lat, lon)
            self._gc.setData(glon, glat)
            self.lbl_target.setText(f"Alvo {grid} ({lat:.1f}°, {lon:.1f}°): {d:.0f} km · azimute {b:.0f}° · "
                                    f"azimute reverso {(b + 180) % 360:.0f}°")
        else:
            self.lbl_target.setText(f"Alvo {grid} ({lat:.1f}°, {lon:.1f}°). Defina seu local para ver distância e azimute.")
