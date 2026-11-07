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

from .. import geo, heatmap, mapdata, propagation, satellites, stations
from ..bands import BandPlan
from ..dxcc import Cty
from ..spots import ClusterClient, Spot
from ..stations import Station

_GRID_WORD = re.compile(r"^[A-R]{2}[0-9]{2}([A-X]{2})?$", re.I)
COND_COLORS = {"Good": "#2e7d32", "Fair": "#f9a825", "Poor": "#c62828"}
LAYERS = {
    "spots": ("Spots (DX Cluster / POTA)", (255, 213, 74)),
    "ft8": ("Estações FT8/FT4 decodificadas", (120, 200, 255)),
    "psk_tx": ("PSK Reporter: quem me ouve", (90, 220, 120)),
    "psk_rx": ("PSK Reporter: quem eu ouço", (255, 140, 60)),
    "wwff": ("WWFF: ativações no ar", (110, 220, 110)),
    "psk_band": ("PSK Reporter: atividade na banda", (186, 140, 255)),
    "wspr": ("WSPR (wspr.live)", (255, 105, 180)),
    "rbn": ("Reverse Beacon Network", (255, 90, 90)),
    "lista": ("Lista importada (gateways etc.)", (0, 230, 200)),
    "sat": ("Satélites amadores (aprox.)", (255, 255, 120)),
    "busca": ("Indicativo procurado", (255, 255, 255)),
}


@dataclass
class Point:
    lat: float
    lon: float
    label: str
    stamp: float
    station: Optional[Station] = None


HEAT_LAYERS = (
    ("none", "Sem mapa de calor"),
    ("prop", "Propagação estimada (frequência do rádio)"),
    ("drap", "Absorção da região D (NOAA D-RAP)"),
    ("aurora", "Aurora (NOAA OVATION)"),
    ("cloud", "Nuvens (Open-Meteo)"),
    ("rain", "Precipitação / tempestades (Open-Meteo)"),
)
HEAT_LEGEND = {
    "prop": "Chance estimada de a frequência atual fechar com o seu QTH: vermelho fechada, verde boa. Estimativa simplificada, não é VOACAP.",
    "drap": "Cor forte: a frequência atual está sendo absorvida (apagão de HF) nessa região. Dados do NOAA D-RAP.",
    "aurora": "Probabilidade de aurora (NOAA OVATION, previsão de 30 a 90 min): afeta VHF/HF em altas latitudes.",
    "cloud": "Cobertura de nuvens agora (grade de 10°). Em VHF/UHF, tempo estável e nuvens baixas podem indicar dutos.",
    "rain": "Precipitação agora (grade de 10°): chuva forte e tempestades geram ruído em HF e atenuam bandas altas.",
}


class MapTab(QtWidgets.QWidget):
    _solar_ready = QtCore.Signal(object)
    _psk_ready = QtCore.Signal(object, bool)
    _status = QtCore.Signal(str)
    solar_updated = QtCore.Signal(object)
    _band_ready = QtCore.Signal(object, str)
    _rbn_spot = QtCore.Signal(object)
    station_selected = QtCore.Signal(object)
    _sats_ready = QtCore.Signal(object)
    action_requested = QtCore.Signal(object, str)   # (Station, chave da ação) tratada pela janela principal

    def __init__(self, plan: BandPlan, cty: Cty, space=None) -> None:
        super().__init__()
        self.plan, self.cty = plan, cty
        self.space = space
        self.sats: list = []
        self._sat_by_name: dict = {}
        self.home: Optional[tuple[float, float]] = None
        self.call = ""
        self.solar: Optional[propagation.SolarData] = None
        self.points: dict[str, list[Point]] = {k: [] for k in LAYERS}
        self.target: Optional[tuple[float, float]] = None
        self._psk_last = 0.0
        self.dial = None  # função que devolve a frequência do rádio (Hz); definida pela janela principal
        self._wspr_last = 0.0
        self._wwff_last = 0.0
        self.rbn: Optional[ClusterClient] = None
        self.selected: Optional[Station] = None

        lay = QtWidgets.QHBoxLayout(self)
        self.plot = pg.PlotWidget(background="#0b1220")
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        self.plot.setAspectLocked(True)
        self.plot.showAxis("left", False)
        self.plot.showAxis("bottom", False)
        vb = self.plot.getPlotItem().vb
        vb.setLimits(xMin=-360, xMax=360, yMin=-200, yMax=200)
        vb.disableAutoRange()
        self._zoomed = False
        vb.sigRangeChangedManually.connect(lambda *_: setattr(self, "_zoomed", True))
        self.fit_world()
        left = QtWidgets.QVBoxLayout()
        bar = QtWidgets.QHBoxLayout()
        bar.addWidget(QtWidgets.QLabel("Mapa de calor:"))
        self.cb_heat = QtWidgets.QComboBox()
        for k, name in HEAT_LAYERS:
            self.cb_heat.addItem(name, k)
        bar.addWidget(self.cb_heat)
        self.lbl_heat_legend = QtWidgets.QLabel("")
        self.lbl_heat_legend.setWordWrap(True)
        self.lbl_heat_legend.setStyleSheet("color:#9aa7b6;font-size:8pt")
        bar.addWidget(self.lbl_heat_legend, 1)
        left.addLayout(bar)
        left.addWidget(self.plot, 1)
        lay.addLayout(left, 4)

        self.night = pg.ImageItem()
        self.night.setZValue(-20)
        self.plot.addItem(self.night)
        self.heatimg = pg.ImageItem()
        self.heatimg.setZValue(-19)
        self.plot.addItem(self.heatimg)
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
                                   tip=lambda x, y, data, **_: data.label() if data is not None else "")
            s.setZValue(10)
            s.sigClicked.connect(self._point_clicked)
            self.plot.addItem(s)
            self.scatter[key] = s
        self.home_item = pg.ScatterPlotItem(size=16, symbol="star", pen=pg.mkPen("w"), brush=pg.mkBrush("#ff5252"))
        self.home_item.setZValue(12)
        self.plot.addItem(self.home_item)
        self.plot.scene().sigMouseClicked.connect(self._on_click)

        side_scroll = QtWidgets.QScrollArea()
        side_scroll.setWidgetResizable(True)
        side_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        side_scroll.setMinimumWidth(380)
        side_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side_body = QtWidgets.QWidget()
        side_scroll.setWidget(side_body)
        side = QtWidgets.QVBoxLayout(side_body)
        lay.addWidget(side_scroll, 1)
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
            if key == "busca":
                cb.hide()
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
        side.addWidget(self._build_sources_box())
        side.addWidget(self._build_station_card())
        self.tbl_psk = QtWidgets.QTableWidget(0, 3)
        self.tbl_psk.setHorizontalHeaderLabels(["Banda", "Relatos", "Mais longe"])
        self.tbl_psk.verticalHeader().setVisible(False)
        self.tbl_psk.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_psk.horizontalHeader().setStretchLastSection(True)
        self.tbl_psk.setMinimumHeight(110)
        side.addWidget(self.tbl_psk)
        self.lbl_target = QtWidgets.QLabel("Clique no mapa: distância e azimute a partir do seu local.")
        self.lbl_target.setWordWrap(True)
        side.addWidget(self.lbl_target)
        self.lbl_info = QtWidgets.QLabel("Fontes: N0NBH/HamQSL (índices), PSK Reporter, wspr.live, Reverse Beacon Network, "
                                         "DX Cluster, POTA e Natural Earth (mapa).")
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setStyleSheet("color:#8a97a8; font-size:8pt")
        side.addWidget(self.lbl_info)

        self.btn_fit.clicked.connect(self.fit_world)
        self.btn_solar.clicked.connect(self.refresh_solar)
        self.btn_psk.clicked.connect(self.refresh_psk)
        self._solar_ready.connect(self._on_solar)
        self._sats_ready.connect(self._on_sats)
        self.cb_heat.currentIndexChanged.connect(self._heat_changed)
        if self.space:
            self.space.layer_ready.connect(lambda _k: self._update_heat())
            self.space.changed.connect(self._update_heat)
        self._psk_ready.connect(self._on_psk)
        self._band_ready.connect(self._on_stations)
        self._rbn_spot.connect(self._on_rbn_spot)
        self._status.connect(self.lbl_info.setText)
        self._rbn_dirty = False
        self.rbn_timer = QtCore.QTimer(self, interval=3000, timeout=self._flush_rbn)
        self.rbn_timer.start()
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
        vb.setLimits(xMin=-360, xMax=360, yMin=-200, yMax=200)
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
        self._update_sats()
        self._update_heat()
        if self._ticks % 15 == 0:
            self.refresh_solar()

    def _refresh_layers(self) -> None:
        routes_x: list[float] = []
        routes_y: list[float] = []
        for key, s in self.scatter.items():
            on = self.checks[key].isChecked()
            pts = self.points[key] if on else []
            s.setData(x=[p.lon for p in pts], y=[p.lat for p in pts], data=[p.station for p in pts])
            if on and key in ("psk_tx", "psk_rx") and self.home:
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

    def add_point(self, layer: str, lat: float, lon: float, label: str, station: Optional[Station] = None) -> None:
        station = station or Station(label.split()[0], lat=lat, lon=lon, info=label, source=layer)
        pts = self.points[layer]
        pts[:] = [p for p in pts if p.station is None or p.station.call != station.call]
        pts.append(Point(lat, lon, label, time.time(), station))
        del pts[:-400]
        self._refresh_layers()

    def add_station(self, layer: str, st: Station, refresh: bool = True) -> None:
        if st.lat is None or st.lon is None:
            ent = self.cty.lookup(st.call)
            if not ent:
                return
            st.lat, st.lon = ent.lat, ent.lon
        pts = self.points[layer]
        pts[:] = [p for p in pts if p.station is None or p.station.call != st.call]
        pts.append(Point(st.lat, st.lon, st.label(), st.stamp, st))
        del pts[:-600]
        if refresh:
            self._refresh_layers()

    def add_spot(self, call: str, freq: int, info: str, lat: Optional[float] = None, lon: Optional[float] = None,
                 mode: str = "", source: str = "spots", ref: str = "") -> None:
        if not mode:
            mode, _ = stations.split_cluster_info(info)
        if not mode:  # sem modo no comentário: usa o que o plano de bandas costuma ter naquela frequência
            guess, data = self.plan.suggest_mode(freq)
            mode = "CW" if guess == "CW" else ("" if data else "SSB")
        self.add_station("spots", Station(call, freq, mode, source, lat, lon, info=info.strip(), ref=ref))

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
        dial = self.dial() if self.dial else 0
        self.add_station("ft8", Station(sender, dial + freq if dial else 0, "FT8", "ft8", lat, lon, grid or "",
                                        f"{snr:+d} dB  {text}"))

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
        self.solar_updated.emit(s)
        if self.space:
            self.space.set_solar(s)
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
            st = Station(other, rep.freq, rep.mode, layer, pos[0], pos[1],
                         rep.receiver_grid if heard_me else rep.sender_grid, f"{rep.snr:+d} dB")
            self.points[layer].append(Point(pos[0], pos[1], st.label(), time.time(), st))
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

    # ---------------------------------------------------------------- fontes e estação selecionada
    def _build_sources_box(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Fontes ao vivo")
        g = QtWidgets.QGridLayout(box)
        self.cb_band = QtWidgets.QComboBox()
        for name in self.plan.band_names():
            start, stop = self.plan.band_range(name)
            self.cb_band.addItem(name, (start, stop))
        self.cb_mode = QtWidgets.QComboBox()
        for m in ("FT8", "FT4", "CW", "RTTY", "JS8", "PSK31", "WSPR", "(todos)"):
            self.cb_mode.addItem(m, "" if m == "(todos)" else m)
        self.btn_band = QtWidgets.QPushButton("Atividade na banda (PSK Reporter)")
        self.btn_wspr = QtWidgets.QPushButton("WSPR agora (wspr.live)")
        self.chk_rbn = QtWidgets.QCheckBox("Reverse Beacon Network ao vivo (CW/RTTY)")
        self.chk_rbn.setToolTip("Conecta a telnet.reversebeacon.net:7000 com o seu indicativo. "
                                "Lista o que os receptores automáticos ouvem.")
        g.addWidget(QtWidgets.QLabel("Banda"), 0, 0)
        g.addWidget(self.cb_band, 0, 1)
        g.addWidget(QtWidgets.QLabel("Modo"), 0, 2)
        g.addWidget(self.cb_mode, 0, 3)
        g.addWidget(self.btn_band, 1, 0, 1, 4)
        g.addWidget(self.btn_wspr, 2, 0, 1, 4)
        g.addWidget(self.chk_rbn, 3, 0, 1, 4)
        self.btn_wwff = QtWidgets.QPushButton("WWFF agora (parques e florestas)")
        g.addWidget(self.btn_wwff, 5, 0, 1, 4)
        self.btn_wwff.clicked.connect(self.refresh_wwff)
        self.btn_sat = QtWidgets.QPushButton("Satélites amadores agora (CelesTrak)")
        g.addWidget(self.btn_sat, 6, 0, 1, 4)
        self.btn_sat.clicked.connect(self.refresh_sats)
        self.btn_import = QtWidgets.QPushButton("Importar lista de estações (CSV/TXT)…")
        self.btn_import.setToolTip("Para fontes que você baixa em arquivo, como a lista de gateways do Winlink. "
                                   "Colunas reconhecidas: indicativo, frequência, modo, grid, lat, lon. Texto solto também funciona.")
        g.addWidget(self.btn_import, 4, 0, 1, 4)
        self.btn_import.clicked.connect(self.import_list)
        self.btn_band.clicked.connect(self.refresh_band)
        self.btn_wspr.clicked.connect(self.refresh_wspr)
        self.chk_rbn.toggled.connect(self._toggle_rbn)
        return box

    def _build_station_card(self) -> QtWidgets.QFrame:
        card = QtWidgets.QFrame()
        card.setObjectName("card")
        v = QtWidgets.QVBoxLayout(card)
        search = QtWidgets.QHBoxLayout()
        self.ed_search = QtWidgets.QLineEdit()
        self.ed_search.setPlaceholderText("Procurar indicativo (ex.: PY2XX)")
        btn = QtWidgets.QPushButton("Localizar")
        search.addWidget(self.ed_search, 1)
        search.addWidget(btn)
        v.addLayout(search)
        self.lbl_sel = QtWidgets.QLabel("Clique numa estação do mapa para ver as opções de conexão.")
        self.lbl_sel.setWordWrap(True)
        self.lbl_sel.setObjectName("cardTitle")
        v.addWidget(self.lbl_sel)
        self.lbl_sel_info = QtWidgets.QLabel("")
        self.lbl_sel_info.setWordWrap(True)
        self.lbl_sel_info.setObjectName("cardTips")
        v.addWidget(self.lbl_sel_info)
        self.actions_box = QtWidgets.QVBoxLayout()
        v.addLayout(self.actions_box)
        btn.clicked.connect(self.search_call)
        self.ed_search.returnPressed.connect(self.search_call)
        return card

    def _point_clicked(self, scatter, points, *_) -> None:
        if points:
            st = points[0].data()
            if isinstance(st, Station):
                self.select_station(st)

    def search_call(self) -> None:
        self.search(self.ed_search.text())

    def search(self, text: str) -> None:
        call = text.strip().upper()
        if not call:
            return
        if _GRID_WORD.match(call):
            lat, lon = geo.grid_to_latlon(call[:6] if len(call) >= 6 else call[:4])
            st = Station(f"Grid {call}", 0, "", "busca", lat, lon, grid=call, info="Quadrícula Maidenhead")
            self.points["busca"] = [Point(lat, lon, st.call, time.time(), st)]
            self._refresh_layers()
            self.select_station(st)
            return
        ent = self.cty.lookup(call)
        if not ent:
            self.lbl_sel.setText(f"{call}: indicativo não reconhecido.")
            return
        st = Station(call, 0, "", "busca", ent.lat, ent.lon, info=f"{ent.name} (posição aproximada: centro do país)")
        self.points["busca"] = [Point(ent.lat, ent.lon, call, time.time(), st)]
        self._refresh_layers()
        self.select_station(st)

    def select_station(self, st: Station) -> None:
        self.selected = st
        self.station_selected.emit(st)
        self.lbl_sel.setText(st.label())
        info = [f"Fonte: {stations.SOURCES.get(st.source, st.source)}"]
        if st.spotter:
            info.append(f"ouvido por {st.spotter}")
        if st.grid:
            info.append(f"grid {st.grid}")
        if self.home and st.lat is not None and st.lon is not None:
            d, b = geo.distance_bearing(self.home[0], self.home[1], st.lat, st.lon)
            info.append(f"{d:.0f} km, azimute {b:.0f}°")
            glon, glat = mapdata.great_circle(self.home[0], self.home[1], st.lat, st.lon)
            self._gc.setData(glon, glat)
        if st.freq and self.home and self.solar:
            band = self.plan.band_for(st.freq)
            if band:
                day = propagation.is_daytime(*self.home)
                cond = self.solar.condition_for(band, day)
                info.append(f"propagação agora em {band}: {propagation.CONDITION_PT.get(cond, '—')}")
        if st.source == "sat" and self.home and st.call in self._sat_by_name:
            passes = satellites.next_passes(self._sat_by_name[st.call], self.home[0], self.home[1], hours=24)[:3]
            info.append("próximas passagens (UTC, aproximadas): " + ("; ".join(
                f"{p.aos:%H:%M}-{p.los:%H:%M} máx {p.max_el:.0f}°" for p in passes) or "nenhuma acima de 10° em 24 h"))
        self.lbl_sel_info.setText(" · ".join(info))
        while self.actions_box.count():
            w = self.actions_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        main, other = stations.actions_for(st)
        for i, act in enumerate(main):
            b = QtWidgets.QPushButton(act.label)
            b.setToolTip(act.hint)
            if i == 0:
                b.setStyleSheet("QPushButton{background:#2e7d32;font-weight:700}")
            b.clicked.connect(lambda _=False, a=act: self.action_requested.emit(st, a.key))
            self.actions_box.addWidget(b)
        more = QtWidgets.QPushButton("Outras ferramentas e consultas  ▾")
        menu = QtWidgets.QMenu(more)
        for act in other:
            menu.addAction(act.label, lambda a=act: self.action_requested.emit(st, a.key))
        more.setMenu(menu)
        self.actions_box.addWidget(more)

    # PSK Reporter por banda e modo
    def refresh_band(self) -> None:
        wait = 300 - (time.time() - self._psk_last)
        if wait > 0:
            self._status.emit(f"PSK Reporter: aguarde {int(wait)} s (limite de 1 consulta a cada 5 min).")
            return
        low, high = self.cb_band.currentData()
        mode = self.cb_mode.currentData() or ""
        if mode == "WSPR":
            self.refresh_wspr()
            return
        self._psk_last = time.time()

        def work() -> None:
            try:
                self._band_ready.emit(stations.fetch_psk_band(low, high, mode), "psk_band")
            except Exception as exc:
                self._status.emit(f"PSK Reporter: {exc}")

        self._status.emit("PSK Reporter: consultando a banda…")
        threading.Thread(target=work, daemon=True).start()

    def refresh_wspr(self) -> None:
        if time.time() - self._wspr_last < 60:
            self._status.emit("wspr.live: aguarde 1 min entre consultas.")
            return
        self._wspr_last = time.time()
        low, high = self.cb_band.currentData()

        def work() -> None:
            try:
                got = [s for s in stations.fetch_wspr(1800) if low <= s.freq <= high]
                self._band_ready.emit(got, "wspr")
            except Exception as exc:
                self._status.emit(f"wspr.live: {exc}")

        self._status.emit("wspr.live: consultando…")
        threading.Thread(target=work, daemon=True).start()

    def _on_stations(self, sts: list, layer: str) -> None:
        self.points[layer].clear()
        for st in sts:
            self.add_station(layer, st, refresh=False)
        self._refresh_layers()
        self._status.emit(f"{stations.SOURCES[layer]}: {len(self.points[layer])} estações no mapa.")

    def refresh_wwff(self) -> None:
        if time.time() - self._wwff_last < 30:
            self._status.emit("WWFF: aguarde 30 s entre consultas (regra do Spotline).")
            return
        self._wwff_last = time.time()

        def work() -> None:
            try:
                self._band_ready.emit(stations.fetch_wwff(), "wwff")
            except Exception as exc:
                self._status.emit(f"WWFF: {exc}")

        self._status.emit("WWFF: consultando…")
        threading.Thread(target=work, daemon=True).start()

    # satélites, mapa de calor
    def refresh_sats(self) -> None:
        def work() -> None:
            try:
                self._sats_ready.emit(satellites.fetch_sats())
            except Exception as exc:
                self._status.emit(f"CelesTrak: {exc}")

        self._status.emit("CelesTrak: baixando elementos orbitais…")
        threading.Thread(target=work, daemon=True).start()

    def _on_sats(self, sats: list) -> None:
        self.sats = sats
        self._sat_by_name = {s.name: s for s in sats}
        self._update_sats()
        self._status.emit(f"Satélites: {len(sats)} no mapa (posição aproximada, atualiza a cada minuto).")

    def _update_sats(self) -> None:
        if not self.sats:
            return
        now = datetime.now(timezone.utc)
        self.points["sat"].clear()
        for s in self.sats:
            lat, lon, alt = satellites.subpoint(s, now)
            info = f"altitude {alt:.0f} km"
            if self.home:
                el, az = satellites.look_angles(s, now, self.home[0], self.home[1])
                info += f", visto daí: elevação {el:.0f}°, azimute {az:.0f}°"
            self.add_station("sat", Station(s.name, 0, "SAT", "sat", lat, lon, info=info), refresh=False)
        self._refresh_layers()

    def _heat_changed(self) -> None:
        key = self.cb_heat.currentData()
        if self.space:
            if key == "aurora":
                self.space.ensure_aurora()
            elif key in ("cloud", "rain"):
                self.space.ensure_weather(key)
            elif key == "drap" and self.space.drap is None:
                self.space.refresh()
        self._update_heat()

    def _set_heat(self, rgba: np.ndarray, x0: float, y0: float, w: float, h: float) -> None:
        self.heatimg.setImage(np.transpose(rgba, (1, 0, 2)), autoLevels=False)
        self.heatimg.setRect(QtCore.QRectF(x0, y0, w, h))

    def _update_heat(self) -> None:
        key = self.cb_heat.currentData()
        sp = self.space
        if not key or key == "none" or sp is None:
            self.heatimg.clear()
            self.lbl_heat_legend.setText("")
            return
        legend = HEAT_LEGEND[key]
        freq = self.dial() if self.dial else 0
        if key == "prop":
            if not (self.home and freq and self.solar):
                self.heatimg.clear()
                legend = "Precisa do seu local (Local / GPS), da frequência do rádio e dos índices solares."
            else:
                kp = sp.sw.kp if sp.sw else float(self.solar.k_index)
                lats, lons, z = heatmap.estimate_grid(self.home, freq, self.solar.sfi, kp, datetime.now(timezone.utc), sp.drap)
                st = lons[1] - lons[0]
                self._set_heat(heatmap.colorize(z, "prop"), lons[0] - st / 2, lats[0] - st / 2, 360 + st, 180 + st)
                legend = f"{freq / 1e6:.3f} MHz: " + legend
        elif key == "drap":
            if sp.drap is None:
                legend = "Carregando D-RAP…"
            else:
                lats, lons, hz = sp.drap
                f = max((freq or 14_000_000) / 1e6, 1.0)
                self._set_heat(heatmap.colorize(np.clip(hz / f, 0, 1), "seq"), -180, -90, 360, 180)
                legend = f"{f:.3f} MHz: " + legend
        elif key == "aurora":
            if sp.aurora is None:
                legend = "Carregando aurora…"
            else:
                g = np.roll(sp.aurora[0], 180, axis=1)
                self._set_heat(heatmap.colorize(np.clip(g / 50.0, 0, 1), "seq"), -180, -90.5, 360, 181)
                legend += f" Previsão {sp.aurora[1]}."
        else:
            wx = sp.wx.get(key)
            if wx is None:
                legend = "Consultando o Open-Meteo (grade global)…"
            else:
                lats, lons, z, _t = wx
                scale = 100.0 if key == "cloud" else 3.0
                st = lons[1] - lons[0]
                self._set_heat(heatmap.colorize(np.clip(z / scale, 0, 1), "seq"), lons[0] - st / 2, lats[0] - st / 2,
                               st * len(lons), st * len(lats))
        self.lbl_heat_legend.setText(legend)

    def import_list(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Lista de estações", "", "Listas (*.csv *.txt *.tsv);;Todos (*)")
        if not path:
            return
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError as exc:
            self._status.emit(f"Lista: {exc}")
            return
        sts = stations.parse_station_list(text, "lista", self.cb_mode.currentData() or "")
        self._on_stations(sts, "lista")
        if not sts:
            self._status.emit("Lista: nenhuma estação reconhecida no arquivo.")

    # Reverse Beacon Network
    def _toggle_rbn(self, on: bool) -> None:
        if self.rbn:
            self.rbn.stop()
            self.rbn = None
        if not on:
            return
        if not self.call:
            self.chk_rbn.setChecked(False)
            self._status.emit("Informe seu indicativo (Local / GPS) para entrar no Reverse Beacon Network.")
            return
        self.rbn = ClusterClient(stations.RBN_HOST, stations.RBN_PORT_CW_RTTY, self.call,
                                 lambda sp: self._rbn_spot.emit(sp), lambda m: self._status.emit(f"RBN: {m}"))
        self.rbn.start()

    def _on_rbn_spot(self, sp: Spot) -> None:
        mode, _ = stations.split_cluster_info(sp.info)
        self.add_station("rbn", Station(sp.call, sp.freq, mode, "rbn", info=sp.info, spotter=sp.spotter), refresh=False)
        self._rbn_dirty = True

    def _flush_rbn(self) -> None:
        if self._rbn_dirty:
            self._rbn_dirty = False
            self._refresh_layers()

    def closeEvent(self, e: QtGui.QCloseEvent) -> None:
        if self.rbn:
            self.rbn.stop()
        super().closeEvent(e)

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
