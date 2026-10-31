"""Aba POTA: ativadores no ar agora, com filtros, distância e marca de já trabalhados."""
from __future__ import annotations

import threading
from typing import Callable, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from .. import geo
from ..bands import BandPlan
from ..logbook import Logbook
from ..spots import Spot, fetch_pota


class PotaTab(QtWidgets.QWidget):
    spot_chosen = QtCore.Signal(object)   # Spot
    spots_loaded = QtCore.Signal(object)  # list[Spot], para o mapa
    _loaded = QtCore.Signal(object, str)

    def __init__(self, plan: BandPlan, logbook: Logbook, get_home: Callable[[], Optional[tuple[float, float]]]) -> None:
        super().__init__()
        self.plan, self.logbook, self.get_home = plan, logbook, get_home
        self.spots: list[Spot] = []
        self._rows: list[Spot] = []

        lay = QtWidgets.QVBoxLayout(self)
        bar = QtWidgets.QHBoxLayout()
        self.cb_band = QtWidgets.QComboBox()
        self.cb_band.addItem("Todas as bandas", "")
        for b in self.plan.band_names():
            self.cb_band.addItem(b, b)
        self.cb_mode = QtWidgets.QComboBox()
        self.cb_mode.addItems(["Todos os modos", "SSB", "CW", "FT8", "FT4", "AM", "FM", "OUTROS"])
        self.chk_new = QtWidgets.QCheckBox("Ocultar já trabalhados")
        self.chk_auto = QtWidgets.QCheckBox("Atualizar a cada 2 min")
        self.chk_auto.setChecked(True)
        self.ed_search = QtWidgets.QLineEdit()
        self.ed_search.setPlaceholderText("Buscar indicativo, parque ou local")
        self.btn = QtWidgets.QPushButton("Atualizar agora")
        for w in (self.cb_band, self.cb_mode, self.chk_new, self.chk_auto):
            bar.addWidget(w)
        bar.addWidget(self.ed_search, 1)
        bar.addWidget(self.btn)
        lay.addLayout(bar)
        self.table = QtWidgets.QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(["Ativador", "kHz", "Modo", "Parque", "Nome", "Local", "Dist./Az.", "Hora (UTC)", "Comentário"])
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(4, 240)
        lay.addWidget(self.table, 1)
        self.lbl = QtWidgets.QLabel("")
        self.lbl.setWordWrap(True)
        lay.addWidget(self.lbl)
        note = QtWidgets.QLabel("Duplo clique: sintoniza (modo sugerido), preenche indicativo e parque no log. Verde = ainda não trabalhado "
                                "neste parque. Fonte: api.pota.app. SOTA: o app só registra referências no log (a API do SOTA exige "
                                "aprovação do projeto para software de terceiros).")
        note.setWordWrap(True)
        note.setStyleSheet("color:#8a97a8; font-size:8pt")
        lay.addWidget(note)

        self.btn.clicked.connect(self.update_spots)
        for w in (self.cb_band, self.cb_mode):
            w.currentIndexChanged.connect(self.refresh)
        self.chk_new.toggled.connect(self.refresh)
        self.ed_search.textChanged.connect(self.refresh)
        self.table.cellDoubleClicked.connect(self._double)
        self._loaded.connect(self._on_loaded)
        self.timer = QtCore.QTimer(self, interval=120_000, timeout=self._auto)
        self.timer.start()
        QtCore.QTimer.singleShot(2000, self.update_spots)

    def _auto(self) -> None:
        if self.chk_auto.isChecked() and self.isVisible():
            self.update_spots()

    def update_spots(self) -> None:
        self.btn.setEnabled(False)

        def work() -> None:
            try:
                self._loaded.emit(fetch_pota(), "")
            except Exception as exc:
                self._loaded.emit(None, str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _on_loaded(self, spots, error: str) -> None:
        self.btn.setEnabled(True)
        if spots is None:
            self.lbl.setText(f"Não foi possível carregar os spots do POTA: {error}")
            return
        self.spots = spots
        self.spots_loaded.emit(spots)
        self.refresh()

    def refresh(self) -> None:
        band, mode = self.cb_band.currentData(), self.cb_mode.currentText()
        text = self.ed_search.text().strip().lower()
        home = self.get_home()
        rows = []
        for s in self.spots:
            if band and self.plan.band_for(s.freq) != band:
                continue
            if not mode.startswith("Todos"):
                if mode == "OUTROS":
                    if s.mode.upper() in ("SSB", "CW", "FT8", "FT4", "AM", "FM"):
                        continue
                elif s.mode.upper() != mode:
                    continue
            ref = s.info.split(" ", 1)[0]
            worked = self.logbook.worked_ref(s.call, ref)
            if self.chk_new.isChecked() and worked:
                continue
            if text and text not in f"{s.call} {s.info}".lower():
                continue
            rows.append((s, ref, worked))
        rows.sort(key=lambda r: r[0].time, reverse=True)
        self._rows = [r[0] for r in rows]
        self.table.setRowCount(len(rows))
        for r, (s, ref, worked) in enumerate(rows):
            name = s.info[len(ref):].strip()
            dist = ""
            if home and s.lat is not None and s.lon is not None:
                d, b = geo.distance_bearing(home[0], home[1], s.lat, s.lon)
                dist = f"{d:.0f} km / {b:.0f}°"
            vals = (s.call, f"{s.freq / 1e3:g}", s.mode, ref, name, s.place, dist, s.time, s.comment)
            for c, v in enumerate(vals):
                item = QtWidgets.QTableWidgetItem(v)
                if not worked:
                    item.setBackground(QtGui.QColor("#16392a"))
                self.table.setItem(r, c, item)
        self.lbl.setText(f"{len(rows)} ativações mostradas de {len(self.spots)} no ar" +
                         ("" if home else " · defina seu local para ver distâncias"))

    def _double(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._rows):
            self.spot_chosen.emit(self._rows[row])
