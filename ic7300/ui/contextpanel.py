"""Painel fixo, presente em todas as telas: propagação com mapa de calor, localidade do contato e radioperador (ou busca)."""
from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from .. import geo, heatmap, mapdata, propagation, weather
from ..bands import BandPlan
from ..dxcc import Cty
from ..hamqth import HamQTH, HamQTHError
from ..settings import Settings
from ..stations import Station, SOURCES
from .spacedata import SpaceData

_GRID = re.compile(r"^[A-R]{2}\d{2}([A-X]{2})?$", re.I)
SEVERITY_COLOR = {"warning": "#ff8a65", "alert": "#ff8a65", "watch": "#ffd54f", "summary": "#9aa7b6", "other": "#9aa7b6"}


def _card(title: str) -> tuple[QtWidgets.QFrame, QtWidgets.QVBoxLayout]:
    card = QtWidgets.QFrame()
    card.setObjectName("card")
    lay = QtWidgets.QVBoxLayout(card)
    lay.setContentsMargins(10, 8, 10, 8)
    lay.setSpacing(4)
    head = QtWidgets.QLabel(title)
    head.setObjectName("cardTitle")
    lay.addWidget(head)
    return card, lay


def _label(text: str = "", tips: bool = False) -> QtWidgets.QLabel:
    lab = QtWidgets.QLabel(text)
    lab.setWordWrap(True)
    lab.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
    if tips:
        lab.setObjectName("cardTips")
    return lab


class ContextPanel(QtWidgets.QScrollArea):
    search_requested = QtCore.Signal(str)
    _wx_ready = QtCore.Signal(object, str)
    _op_ready = QtCore.Signal(object, str)

    def __init__(self, settings: Settings, cty: Cty, plan: BandPlan, space: SpaceData,
                 get_freq: Callable[[], int], get_home: Callable[[], Optional[tuple[float, float]]]) -> None:
        super().__init__()
        self.settings, self.cty, self.plan, self.space = settings, cty, plan, space
        self.get_freq, self.get_home = get_freq, get_home
        self.station: Optional[Station] = None
        self.hamqth = HamQTH(settings.hamqth_user, settings.hamqth_pass)
        self._grid_key: tuple = ()
        self._grid = None
        self._wx_cache: dict[tuple, tuple[float, str]] = {}
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumWidth(330)
        self.setMaximumWidth(400)
        body = QtWidgets.QWidget()
        self.setWidget(body)
        col = QtWidgets.QVBoxLayout(body)
        col.setContentsMargins(6, 6, 6, 6)
        col.setSpacing(8)

        # ---- propagação
        card, lay = _card("Propagação agora")
        self.lbl_idx = _label()
        self.lbl_band = _label()
        self.lbl_alert = _label()
        self.mini = pg.PlotWidget(background="#0b1220")
        self.mini.setMenuEnabled(False)
        self.mini.hideButtons()
        self.mini.setMouseEnabled(False, False)
        self.mini.setAspectLocked(True)
        self.mini.showAxis("left", False)
        self.mini.showAxis("bottom", False)
        self.mini.setFixedHeight(165)
        self.mini.getPlotItem().vb.setRange(xRange=(-180, 180), yRange=(-90, 90), padding=0)
        self.mini.getPlotItem().vb.setLimits(xMin=-360, xMax=360, yMin=-200, yMax=200)
        self.heat = pg.ImageItem()
        self.heat.setZValue(-5)
        self.mini.addItem(self.heat)
        xs, ys = mapdata.load_lines("coast")
        coast = pg.PlotDataItem(xs, ys, pen=pg.mkPen("#6b7a90", width=1), connect="finite")
        self.mini.addItem(coast)
        self.mini_home = pg.ScatterPlotItem(size=10, symbol="star", pen=pg.mkPen("w"), brush=pg.mkBrush("#ff5252"))
        self.mini_sel = pg.ScatterPlotItem(size=9, pen=pg.mkPen("w"), brush=pg.mkBrush("#ffffff"))
        self.mini.addItem(self.mini_home)
        self.mini.addItem(self.mini_sel)
        self.lbl_heat = _label("", tips=True)
        for w in (self.lbl_idx, self.lbl_band, self.lbl_alert, self.mini, self.lbl_heat):
            lay.addWidget(w)
        col.addWidget(card)

        # ---- localidade
        card, lay = _card("Localidade do contato")
        self.lbl_loc = _label("Selecione uma estação no mapa (ou busque abaixo) para ver o local, a hora e o tempo.", tips=True)
        self.lbl_wx = _label("", tips=True)
        lay.addWidget(self.lbl_loc)
        lay.addWidget(self.lbl_wx)
        col.addWidget(card)

        # ---- radioperador
        card, lay = _card("Radioperador")
        self.lbl_op = _label("Nenhum indicativo selecionado.", tips=True)
        lay.addWidget(self.lbl_op)
        row = QtWidgets.QHBoxLayout()
        self.ed_search = QtWidgets.QLineEdit()
        self.ed_search.setPlaceholderText("Buscar indicativo ou grid (ex.: PY2XX, GG67)")
        btn = QtWidgets.QPushButton("Buscar")
        row.addWidget(self.ed_search, 1)
        row.addWidget(btn)
        lay.addLayout(row)
        self.btn_hamqth = QtWidgets.QPushButton("Configurar HamQTH (dados do operador)…")
        lay.addWidget(self.btn_hamqth)
        col.addWidget(card)
        col.addStretch()

        btn.clicked.connect(self._search)
        self.ed_search.returnPressed.connect(self._search)
        self.btn_hamqth.clicked.connect(self._config_hamqth)
        self._wx_ready.connect(self._on_wx)
        self._op_ready.connect(self._on_op)
        space.changed.connect(self.refresh_prop)
        self.timer = QtCore.QTimer(self, interval=5000, timeout=self.refresh_prop)
        self.timer.start()
        self._update_hamqth_button()
        self.refresh_prop()

    # ------------------------------------------------------------------ propagação
    def refresh_prop(self) -> None:
        s, sw = self.space.solar, self.space.sw
        home = self.get_home()
        freq = self.get_freq()
        if s:
            kp = f" · Kp NOAA {sw.kp:.1f}" if sw else ""
            self.lbl_idx.setText(f"SFI {s.sfi} · A {s.a_index} · K {s.k_index}{kp} · manchas {s.sunspots}\n"
                                 f"Raios-X {s.xray} · vento solar {s.solar_wind:.0f} km/s · {s.geomag}")
        else:
            self.lbl_idx.setText("Índices solares: carregando…")
        band = self.plan.band_for(freq) if freq else None
        if band and s:
            day_c = propagation.CONDITION_PT.get(s.condition_for(band, True), "—")
            night_c = propagation.CONDITION_PT.get(s.condition_for(band, False), "—")
            here = ""
            if home:
                now_day = propagation.is_daytime(*home)
                here = f"\nAí agora é {'dia' if now_day else 'noite'}: condição {propagation.CONDITION_PT.get(s.condition_for(band, now_day), '—')}."
            self.lbl_band.setText(f"{freq / 1e6:.3f} MHz ({band}): dia {day_c} · noite {night_c}.{here}")
        else:
            self.lbl_band.setText(f"{freq / 1e6:.3f} MHz: fora das bandas de radioamador." if freq else "Rádio desconectado.")
        if sw and sw.alerts:
            a = sw.alerts[0]
            self.lbl_alert.setText(f"<span style='color:{SEVERITY_COLOR.get(a.severity, '#9aa7b6')}'>NOAA {a.issued} UTC: {a.headline}</span>")
        else:
            self.lbl_alert.setText("")
        self._update_heat(home, freq)

    def _update_heat(self, home: Optional[tuple[float, float]], freq: int) -> None:
        s, sw = self.space.solar, self.space.sw
        self.mini_home.setData(x=[home[1]] if home else [], y=[home[0]] if home else [])
        if not (home and freq and s):
            self.heat.clear()
            self.lbl_heat.setText("Mapa de calor: precisa do seu local (Local / GPS), da frequência do rádio e dos índices solares.")
            return
        minute = datetime.now(timezone.utc).strftime("%H%M")
        key = (home, freq // 50_000, s.sfi, sw.kp if sw else 0, minute, self.space.drap is not None)
        if key != self._grid_key:
            self._grid_key = key
            self._grid = heatmap.estimate_grid(home, freq, s.sfi, sw.kp if sw else float(s.k_index), datetime.now(timezone.utc),
                                               self.space.drap)
            lats, lons, z = self._grid
            step = lons[1] - lons[0]
            self.heat.setImage(np.transpose(heatmap.colorize(z, "prop"), (1, 0, 2)), autoLevels=False)
            self.heat.setRect(QtCore.QRectF(lons[0] - step / 2, lats[0] - step / 2, 360 + step, 180 + step))
        txt = ("Cor = chance estimada de a frequência atual fechar com o seu QTH (vermelho fechada, verde boa). "
               "Estimativa simplificada (SFI, Sol, D-RAP, Kp), não é VOACAP.")
        if self.station and self.station.lat is not None and self._grid:
            lats, lons, z = self._grid
            p = heatmap.sample(lats, lons, z, self.station.lat, self.station.lon)
            txt = f"Para {self.station.call} nesta frequência: {heatmap.classify(p)} ({p * 100:.0f}%).\n" + txt
        self.lbl_heat.setText(txt)

    # ------------------------------------------------------------------ contato selecionado
    def set_station(self, st: Optional[Station]) -> None:
        self.station = st
        if st is None:
            return
        self.mini_sel.setData(x=[st.lon] if st.lon is not None else [], y=[st.lat] if st.lat is not None else [])
        self._show_locality(st)
        self._show_operator(st)
        self._update_heat(self.get_home(), self.get_freq())

    def _show_locality(self, st: Station) -> None:
        ent = self.cty.lookup(st.call) if not st.call.startswith("Grid ") else None
        lines = []
        if ent:
            lines.append(f"{ent.name} ({ent.continent}) · CQ {ent.cq} · ITU {ent.itu} · prefixo {ent.prefix}")
        if st.lat is not None and st.lon is not None:
            grid = st.grid or geo.latlon_to_grid(st.lat, st.lon)
            lines.append(f"{abs(st.lat):.2f}°{'N' if st.lat >= 0 else 'S'}, {abs(st.lon):.2f}°{'E' if st.lon >= 0 else 'W'} · grid {grid[:6]}")
            when = datetime.now(timezone.utc)
            offset = -ent.tz if ent else st.lon / 15.0
            local = when + timedelta(hours=offset)
            lines.append(f"Hora local ≈ {local:%H:%M} ({'fuso do país' if ent else 'solar aproximada'}) · "
                         f"{'dia' if propagation.is_daytime(st.lat, st.lon) else 'noite'} lá")
            home = self.get_home()
            if home:
                d, b = geo.distance_bearing(home[0], home[1], st.lat, st.lon)
                lines.append(f"{d:.0f} km · azimute {b:.0f}° (caminho longo {(b + 180) % 360:.0f}°, {40075 - d:.0f} km)")
        if st.source in SOURCES:
            lines.append(f"Fonte: {SOURCES[st.source]}" + (f" · ouvido por {st.spotter}" if st.spotter else ""))
        self.lbl_loc.setText("\n".join(lines) or "Local desconhecido.")
        self.lbl_wx.setText("")
        if st.lat is not None and st.lon is not None:
            key = (round(st.lat, 1), round(st.lon, 1))
            hit = self._wx_cache.get(key)
            if hit and time.time() - hit[0] < 900:
                self.lbl_wx.setText("Tempo agora: " + hit[1])
                return
            self.lbl_wx.setText("Tempo agora: consultando…")
            lat, lon = st.lat, st.lon

            def work() -> None:
                try:
                    self._wx_ready.emit(weather.fetch_weather(lat, lon), f"{key[0]},{key[1]}")
                except Exception as exc:
                    self._wx_ready.emit(None, str(exc))

            threading.Thread(target=work, daemon=True).start()

    def _on_wx(self, w, key: str) -> None:
        if w is None:
            self.lbl_wx.setText(f"Tempo agora: indisponível ({key}).")
            return
        try:
            lat, lon = (float(x) for x in key.split(","))
            self._wx_cache[(lat, lon)] = (time.time(), w.summary())
        except ValueError:
            pass
        self.lbl_wx.setText("Tempo agora: " + w.summary() + "\n(Open-Meteo; no VHF/UHF nuvens e pressão alta indicam dutos)")

    def _show_operator(self, st: Station) -> None:
        base = [f"{st.call}"]
        ent = self.cty.lookup(st.call) if not st.call.startswith("Grid ") else None
        if ent:
            base.append(f"{ent.name}")
        if st.freq:
            base.append(f"{st.freq / 1e6:.4f} MHz {st.mode}".strip())
        if st.info:
            base.append(st.info)
        self.lbl_op.setText(" · ".join(base) + ("\nBuscando no HamQTH…" if self.hamqth.configured and not st.call.startswith("Grid ") else
                                                "\nDados pessoais do operador: configure o HamQTH (conta gratuita) ou use a busca."))
        if self.hamqth.configured and not st.call.startswith("Grid "):
            call = st.call.split("/")[0] if "/" in st.call and len(st.call.split("/")[0]) > 2 else st.call

            def work() -> None:
                try:
                    self._op_ready.emit(self.hamqth.lookup(call.split("-")[0]), st.call)
                except (HamQTHError, OSError) as exc:
                    self._op_ready.emit(str(exc), st.call)

            threading.Thread(target=work, daemon=True).start()

    def _on_op(self, data, call: str) -> None:
        if not self.station or self.station.call != call:
            return
        if isinstance(data, str):
            self.lbl_op.setText(self.lbl_op.text().split("\n")[0] + f"\nHamQTH: {data}")
            return
        parts = [data.get("adr_name") or data.get("nick", ""), data.get("qth") or data.get("adr_city", ""), data.get("country", ""),
                 f"grid {data['grid']}" if data.get("grid") else "", f"CQ {data['cq']}" if data.get("cq") else "",
                 f"IOTA {data['iota']}" if data.get("iota") else "", f"licenciado desde {data['lic_year']}" if data.get("lic_year") else ""]
        qsl = [f"{k.upper()}: {data[k]}" for k in ("lotw", "eqsl") if data.get(k)] + ([f"QSL via {data['qsl_via']}"] if data.get("qsl_via") else [])
        self.lbl_op.setText(self.lbl_op.text().split("\n")[0] + "\n" + " · ".join(p for p in parts if p) +
                            ("\n" + " · ".join(qsl) if qsl else "") + "\nFonte: HamQTH")

    # ------------------------------------------------------------------ busca e configuração
    def _search(self) -> None:
        text = self.ed_search.text().strip()
        if text:
            self.search_requested.emit(text)

    def _config_hamqth(self) -> None:
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("HamQTH")
        form = QtWidgets.QFormLayout(dlg)
        user = QtWidgets.QLineEdit(self.settings.hamqth_user)
        pw = QtWidgets.QLineEdit(self.settings.hamqth_pass)
        pw.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        form.addRow("Usuário (seu indicativo)", user)
        form.addRow("Senha", pw)
        note = QtWidgets.QLabel("Conta gratuita em hamqth.com. A senha fica salva em texto no perfil local deste PC "
                                "(%APPDATA%/IC7300App). Os dados vêm do HamQTH.")
        note.setWordWrap(True)
        form.addRow(note)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Save | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        form.addRow(bb)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        if dlg.exec():
            self.settings.hamqth_user, self.settings.hamqth_pass = user.text().strip(), pw.text()
            self.settings.save()
            self.hamqth = HamQTH(self.settings.hamqth_user, self.settings.hamqth_pass)
            self._update_hamqth_button()
            if self.station:
                self._show_operator(self.station)

    def _update_hamqth_button(self) -> None:
        self.btn_hamqth.setText("HamQTH: conectado (trocar conta…)" if self.hamqth.configured else
                                "Configurar HamQTH (dados do operador)…")
