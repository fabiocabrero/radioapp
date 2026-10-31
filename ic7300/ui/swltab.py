"""Aba Ondas curtas: emissoras no ar agora, com horário local, alvo e condição de propagação."""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets

from .. import geo, propagation, swl
from ..bands import BandPlan
from ..settings import app_dir

MAX_ROWS = 1500
COND_BG = {"Good": "#1f5f2a", "Fair": "#7a5d12", "Poor": "#6b1f1f"}


class SwlTab(QtWidgets.QWidget):
    tune_requested = QtCore.Signal(int, str)  # Hz, modo
    _loaded = QtCore.Signal(object, str)
    _status = QtCore.Signal(str)

    def __init__(self, plan: BandPlan) -> None:
        super().__init__()
        self.plan = plan
        self.entries: list[swl.Entry] = []
        self.home: Optional[tuple[float, float]] = None
        self.solar: Optional[propagation.SolarData] = None
        self.season = ""
        self.path = app_dir() / "broadcast.csv"
        self.info_path = app_dir() / "broadcast.info"

        lay = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        self.chk_now = QtWidgets.QCheckBox("No ar agora")
        self.chk_now.setChecked(True)
        self.chk_target = QtWidgets.QCheckBox("Dirigidas à minha região")
        self.chk_voice = QtWidgets.QCheckBox("Ocultar sinais não falados (CW, HFDL, fax)")
        self.chk_voice.setChecked(True)
        self.cb_band = QtWidgets.QComboBox()
        self.cb_band.addItem("Ondas curtas (2,3–30 MHz)", (2300, 30000))
        self.cb_band.addItem("Ondas médias e longas", (0, 2300))
        self.cb_band.addItem("Todas as frequências", None)
        for o in self.plan.other:
            if o["kind"] == "broadcast":
                self.cb_band.addItem(o["name"].replace("Broadcast ", ""), (o["start"] // 1000, o["stop"] // 1000))
        self.cb_lang = QtWidgets.QComboBox()
        self.cb_lang.addItem("Todos os idiomas", "")
        self.ed_search = QtWidgets.QLineEdit()
        self.ed_search.setPlaceholderText("Buscar estação, país, idioma ou frequência")
        self.btn_update = QtWidgets.QPushButton("Atualizar lista (EiBi)")
        for w in (self.chk_now, self.chk_target, self.chk_voice, self.cb_band, self.cb_lang):
            top.addWidget(w)
        top.addWidget(self.ed_search, 1)
        top.addWidget(self.btn_update)
        lay.addLayout(top)

        self.table = QtWidgets.QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(["kHz", "Horário local", "UTC", "Estação", "Idioma", "País", "Alvo",
                                              "Dist.", "kW", "Propagação"])
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(3, 260)
        lay.addWidget(self.table, 1)
        self.lbl = QtWidgets.QLabel("")
        self.lbl.setWordWrap(True)
        lay.addWidget(self.lbl)
        note = QtWidgets.QLabel("Duplo clique sintoniza em AM. Grade: EiBi (Eike Bierwirth, www.eibispace.de). Distância e alvo usam o "
                                "centro do país da emissora (aproximado); a coluna Propagação é um indicativo do N0NBH por faixa.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#8a97a8; font-size:8pt")
        lay.addWidget(note)

        self.timer = QtCore.QTimer(self, interval=60_000, timeout=self.refresh)
        self.timer.start()
        for w in (self.chk_now, self.chk_target, self.chk_voice):
            w.toggled.connect(self.refresh)
        self.cb_band.currentIndexChanged.connect(self.refresh)
        self.cb_lang.currentIndexChanged.connect(self.refresh)
        self.ed_search.textChanged.connect(self.refresh)
        self.btn_update.clicked.connect(self.update_list)
        self.table.cellDoubleClicked.connect(self._double)
        self._loaded.connect(self._on_loaded)
        self._status.connect(self.lbl.setText)
        self._rows: list[swl.Entry] = []

        if self.path.exists():
            self._load_cached()
        QtCore.QTimer.singleShot(1000, self._maybe_update)

    # ---------------------------------------------------------------- dados
    def set_home(self, lat: float, lon: float) -> None:
        self.home = (lat, lon) if (lat or lon) else None
        self.refresh()

    def set_solar(self, solar: propagation.SolarData) -> None:
        self.solar = solar
        self.refresh()

    def _load_cached(self) -> None:
        try:
            self.entries = swl.load_file(self.path)
            self.season = self.info_path.read_text(encoding="utf-8").split()[0] if self.info_path.exists() else ""
        except OSError:
            self.entries = []
        self._fill_languages()
        self.refresh()

    def _maybe_update(self) -> None:
        """Baixa a grade se não existir ou se a temporada vigente for outra."""
        current = swl.seasons(datetime.now(timezone.utc).date())[0]
        if not self.entries or self.season != current:
            self.update_list()

    def update_list(self) -> None:
        self.btn_update.setEnabled(False)
        self._status.emit("Baixando a grade do EiBi…")

        def work() -> None:
            try:
                text, season = swl.download()
                self.path.write_text(text, encoding="utf-8", newline="\n")
                self.info_path.write_text(f"{season} {datetime.now():%Y-%m-%d}\n", encoding="utf-8")
                self._loaded.emit(swl.parse_schedule(text), season)
            except Exception as exc:
                self._loaded.emit(None, str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _on_loaded(self, entries, info: str) -> None:
        self.btn_update.setEnabled(True)
        if entries is None:
            self._status.emit(f"Não foi possível atualizar a grade: {info}" + (" (usando a lista salva)" if self.entries else ""))
            return
        self.entries, self.season = entries, info
        self._fill_languages()
        self.refresh()

    def _fill_languages(self) -> None:
        current = self.cb_lang.currentData()
        self.cb_lang.blockSignals(True)
        self.cb_lang.clear()
        self.cb_lang.addItem("Todos os idiomas", "")
        for lang in sorted({e.lang for e in self.entries if e.lang}):
            self.cb_lang.addItem(lang, lang)
        i = self.cb_lang.findData(current)
        self.cb_lang.setCurrentIndex(max(0, i))
        self.cb_lang.blockSignals(False)

    # ---------------------------------------------------------------- lista
    def refresh(self) -> None:
        if not self.entries:
            self.lbl.setText("Sem grade de emissoras: clique em “Atualizar lista (EiBi)” (precisa de internet).")
            self.table.setRowCount(0)
            return
        utc = datetime.now(timezone.utc)
        band = self.cb_band.currentData()
        lang = self.cb_lang.currentData()
        text = self.ed_search.text().strip().lower()
        rows = []
        for e in self.entries:
            state = swl.on_air(e, utc)
            if self.chk_now.isChecked() and state is False:
                continue
            if band and not (band[0] <= e.freq_khz <= band[1]):
                continue
            if lang and e.lang != lang:
                continue
            if self.chk_voice.isChecked() and e.lang.startswith("-"):
                continue
            if text and text not in f"{e.station} {e.itu} {e.lang} {e.target} {e.freq_khz:g}".lower():
                continue
            covers = swl.target_covers(e.target, *self.home) if self.home else None
            if self.chk_target.isChecked() and self.home and covers is not True:
                continue
            rows.append((0 if covers else 1, 0 if state else 1, e, state, covers))
        rows.sort(key=lambda r: (r[0], r[1], r[2].freq_khz))
        shown = rows[:MAX_ROWS]
        self._rows = [r[2] for r in shown]
        day = propagation.is_daytime(*self.home) if self.home else True
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(shown))
        for r, (_, _, e, state, covers) in enumerate(shown):
            dist = ""
            pos = e.position()
            if pos and self.home:
                dist = f"{geo.distance_bearing(self.home[0], self.home[1], pos[0], pos[1])[0]:.0f} km"
            cond = self.solar.condition_for_group(swl.band_group(e.freq_khz), day) if self.solar else ""
            station = e.station + ("  (talvez)" if state is None else "")
            vals = (f"{e.freq_khz:g}", swl.local_window(e, utc), swl.utc_window(e), station, e.lang, e.itu, e.target,
                    dist, f"{e.power:g}", propagation.CONDITION_PT.get(cond, cond))
            for c, v in enumerate(vals):
                item = QtWidgets.QTableWidgetItem(v)
                if covers:
                    item.setBackground(QtGui.QColor("#16392a"))
                if c == 9 and cond:
                    item.setBackground(QtGui.QColor(COND_BG.get(cond, "#333")))
                self.table.setItem(r, c, item)
        n_now = sum(1 for r in rows if r[3])
        self.lbl.setText(f"{len(rows)} emissões listadas ({n_now} no ar) · {len(self.entries)} na grade {self.season.upper()} · "
                         f"{utc:%H:%M} UTC" + ("" if self.home else " · defina seu local para filtrar por região e ver distâncias")
                         + (f" · mostrando as {MAX_ROWS} primeiras" if len(rows) > MAX_ROWS else ""))

    def _double(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._rows):
            e = self._rows[row]
            self.tune_requested.emit(e.freq_hz, "AM")
