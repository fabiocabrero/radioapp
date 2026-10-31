"""Aba Concursos: calendário (WA7BNM) e log de concurso com checagem de duplicados e exportação Cabrillo."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from .. import contests, geo
from ..dxcc import Cty
from ..radio import RadioState
from ..settings import Settings

CABRILLO_FIELDS = [("CATEGORY-OPERATOR", "Categoria (operador)", "SINGLE-OP"), ("CATEGORY-BAND", "Categoria (banda)", "ALL"),
                   ("CATEGORY-MODE", "Categoria (modo)", "MIXED"), ("CATEGORY-POWER", "Categoria (potência)", "LOW"),
                   ("CATEGORY-ASSISTED", "Assistido", "NON-ASSISTED"), ("NAME", "Nome", ""), ("ADDRESS", "Endereço", ""),
                   ("ADDRESS-CITY", "Cidade", ""), ("ADDRESS-STATE-PROVINCE", "Estado", ""),
                   ("ADDRESS-POSTALCODE", "CEP", ""), ("ADDRESS-COUNTRY", "País", "Brazil"), ("EMAIL", "E-mail", ""),
                   ("CLUB", "Clube", ""), ("CLAIMED-SCORE", "Pontuação declarada", "")]


def _human(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    days, rest = divmod(minutes, 1440)
    hours, mins = divmod(rest, 60)
    if days:
        return f"{days} d {hours} h"
    return f"{hours} h {mins:02d} min" if hours else f"{mins} min"


class ContestsTab(QtWidgets.QWidget):
    _loaded = QtCore.Signal(object, str)

    def __init__(self, settings: Settings, cty: Cty, get_state: Callable[[], RadioState],
                 get_call: Callable[[], str]) -> None:
        super().__init__()
        self.settings, self.cty, self.get_state, self.get_call = settings, cty, get_state, get_call
        self.calendar: list[contests.Contest] = []
        self.log: Optional[contests.ContestLog] = None
        self._rows: list[contests.Contest] = []

        lay = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QVBoxLayout()
        lay.addLayout(left, 5)
        bar = QtWidgets.QHBoxLayout()
        self.cb_filter = QtWidgets.QComboBox()
        self.cb_filter.addItems(["No ar e próximos 7 dias", "No ar agora", "Todos"])
        self.cb_mode = QtWidgets.QComboBox()
        self.cb_mode.addItems(["Todos os modos", "CW", "SSB", "Digital", "RTTY", "FM", "EME", "Misto"])
        self.btn_cal = QtWidgets.QPushButton("Atualizar calendário")
        bar.addWidget(self.cb_filter)
        bar.addWidget(self.cb_mode)
        bar.addWidget(self.btn_cal)
        left.addLayout(bar)
        self.tbl_cal = QtWidgets.QTableWidget(0, 5)
        self.tbl_cal.setHorizontalHeaderLabels(["Concurso", "Modo", "Início (hora local)", "Fim (hora local)", "Situação"])
        self.tbl_cal.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_cal.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_cal.verticalHeader().setVisible(False)
        self.tbl_cal.horizontalHeader().setStretchLastSection(True)
        self.tbl_cal.setColumnWidth(0, 280)
        left.addWidget(self.tbl_cal, 1)
        self.lbl_cal = QtWidgets.QLabel("")
        self.lbl_cal.setWordWrap(True)
        left.addWidget(self.lbl_cal)
        note = QtWidgets.QLabel("Duplo clique: usa o concurso no log ao lado; botão direito: abre as regras no navegador. "
                                "Calendário: WA7BNM Contest Calendar (contestcalendar.com).")
        note.setWordWrap(True)
        note.setStyleSheet("color:#8a97a8; font-size:8pt")
        left.addWidget(note)

        right = QtWidgets.QVBoxLayout()
        lay.addLayout(right, 6)
        form = QtWidgets.QHBoxLayout()
        self.ed_contest = QtWidgets.QLineEdit(settings.contest_name)
        self.ed_contest.setPlaceholderText("Nome do concurso")
        self.ed_cab_id = QtWidgets.QLineEdit()
        self.ed_cab_id.setPlaceholderText("ID Cabrillo (ex.: CQ-WW-SSB)")
        self.btn_open = QtWidgets.QPushButton("Abrir log")
        form.addWidget(self.ed_contest, 3)
        form.addWidget(self.ed_cab_id, 2)
        form.addWidget(self.btn_open)
        right.addLayout(form)
        ex = QtWidgets.QHBoxLayout()
        self.ed_exch = QtWidgets.QLineEdit()
        self.ed_exch.setPlaceholderText("Minha troca (ex.: 05 ou SP)")
        self.chk_serial = QtWidgets.QCheckBox("Número de série automático")
        self.chk_serial.setChecked(True)
        ex.addWidget(self.ed_exch, 2)
        ex.addWidget(self.chk_serial, 2)
        right.addLayout(ex)
        entry = QtWidgets.QHBoxLayout()
        self.ed_call = QtWidgets.QLineEdit()
        self.ed_call.setPlaceholderText("Indicativo")
        self.ed_rst = QtWidgets.QLineEdit("59")
        self.ed_rst.setMaximumWidth(50)
        self.ed_rexch = QtWidgets.QLineEdit()
        self.ed_rexch.setPlaceholderText("Troca recebida")
        self.btn_add = QtWidgets.QPushButton("Registrar")
        for w in (self.ed_call, self.ed_rst, self.ed_rexch, self.btn_add):
            entry.addWidget(w)
        entry.setStretch(0, 2)
        entry.setStretch(2, 2)
        right.addLayout(entry)
        self.lbl_dupe = QtWidgets.QLabel("")
        self.lbl_dupe.setStyleSheet("font-weight:600")
        right.addWidget(self.lbl_dupe)
        self.tbl_log = QtWidgets.QTableWidget(0, 8)
        self.tbl_log.setHorizontalHeaderLabels(["UTC", "Indicativo", "kHz", "Modo", "RST env.", "Troca env.", "RST rec.", "Troca rec."])
        self.tbl_log.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_log.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_log.verticalHeader().setVisible(False)
        self.tbl_log.horizontalHeader().setStretchLastSection(True)
        right.addWidget(self.tbl_log, 1)
        self.lbl_stats = QtWidgets.QLabel("Abra um log para começar.")
        self.lbl_stats.setWordWrap(True)
        right.addWidget(self.lbl_stats)
        btns = QtWidgets.QHBoxLayout()
        self.btn_header = QtWidgets.QPushButton("Cabeçalho Cabrillo…")
        self.btn_export = QtWidgets.QPushButton("Exportar Cabrillo")
        self.btn_del = QtWidgets.QPushButton("Apagar selecionado")
        for b in (self.btn_header, self.btn_export, self.btn_del):
            btns.addWidget(b)
        right.addLayout(btns)

        self.btn_cal.clicked.connect(self.update_calendar)
        self.cb_filter.currentIndexChanged.connect(self.refresh_calendar)
        self.cb_mode.currentIndexChanged.connect(self.refresh_calendar)
        self.tbl_cal.cellDoubleClicked.connect(self._use_contest)
        self.tbl_cal.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.tbl_cal.customContextMenuRequested.connect(self._open_rules)
        self.btn_open.clicked.connect(self._open_log)
        self.ed_call.textChanged.connect(self._check_call)
        for w in (self.ed_call, self.ed_rst, self.ed_rexch):
            w.returnPressed.connect(self._add)
        self.btn_add.clicked.connect(self._add)
        self.btn_header.clicked.connect(self._edit_header)
        self.btn_export.clicked.connect(self._export)
        self.btn_del.clicked.connect(self._delete)
        self._loaded.connect(self._on_loaded)
        self.timer = QtCore.QTimer(self, interval=60_000, timeout=self.refresh_calendar)
        self.timer.start()
        QtCore.QTimer.singleShot(1500, self.update_calendar)
        if settings.contest_name:
            self._open_log()

    # ---------------------------------------------------------------- calendário
    def update_calendar(self) -> None:
        self.btn_cal.setEnabled(False)
        self.lbl_cal.setText("Baixando o calendário…")

        def work() -> None:
            try:
                self._loaded.emit(contests.fetch_calendar(), "")
            except Exception as exc:
                self._loaded.emit(None, str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _on_loaded(self, cal, error: str) -> None:
        self.btn_cal.setEnabled(True)
        if cal is None:
            self.lbl_cal.setText(f"Não foi possível carregar o calendário: {error}")
            return
        self.calendar = cal
        self.refresh_calendar()

    def refresh_calendar(self) -> None:
        now = datetime.now(timezone.utc)
        mode = self.cb_mode.currentText()
        mode_filter = None if mode.startswith("Todos") else mode
        horizon = {0: timedelta(days=7), 1: timedelta(0), 2: timedelta(days=3650)}[self.cb_filter.currentIndex()]
        items = []
        for c in self.calendar:
            if mode_filter and c.mode() != mode_filter:
                continue
            run = c.running(now)
            nxt = c.next_window(now)
            if run:
                items.append((0, run.end, c, run, True))
            elif nxt and self.cb_filter.currentIndex() != 1 and nxt.start - now <= horizon:
                items.append((1, nxt.start, c, nxt, False))
        items.sort(key=lambda x: (x[0], x[1]))
        self._rows = [i[2] for i in items]
        self.tbl_cal.setRowCount(len(items))
        for r, (_, _, c, w, running) in enumerate(items):
            label = f" ({w.label})" if w.label else ""
            state = f"NO AR, termina em {_human(w.end - now)}" if running else f"começa em {_human(w.start - now)}"
            vals = (c.title + label, c.mode(), f"{w.start.astimezone():%d/%m %H:%M}", f"{w.end.astimezone():%d/%m %H:%M}", state)
            for col, v in enumerate(vals):
                item = QtWidgets.QTableWidgetItem(v)
                if running:
                    item.setBackground(QtGui.QColor("#16392a"))
                self.tbl_cal.setItem(r, col, item)
        self.lbl_cal.setText(f"{len(items)} concursos · {len(self.calendar)} no calendário · horários na hora do PC "
                             f"(UTC{now.astimezone().strftime('%z')[:3]})" if self.calendar else
                             "Calendário vazio: clique em “Atualizar calendário” (precisa de internet).")

    def _use_contest(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._rows):
            self.ed_contest.setText(self._rows[row].title)

    def _open_rules(self, pos: QtCore.QPoint) -> None:
        row = self.tbl_cal.rowAt(pos.y())
        if 0 <= row < len(self._rows) and self._rows[row].link:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(self._rows[row].link))

    # ---------------------------------------------------------------- log
    def _open_log(self) -> None:
        name = self.ed_contest.text().strip()
        if not name:
            QtWidgets.QMessageBox.information(self, "Concurso", "Informe o nome do concurso.")
            return
        self.settings.contest_name = name
        self.log = contests.ContestLog(name)
        self._refresh_log()
        self._next_exchange()

    def _next_exchange(self) -> None:
        if self.log and self.chk_serial.isChecked():
            self.ed_exch.setText(f"{self.log.next_serial():03d}")

    def _check_call(self, text: str) -> None:
        call = text.strip().upper()
        self.lbl_dupe.setText("")
        if not call:
            return
        ent = self.cty.lookup(call)
        info = f"{ent.name} · CQ {ent.cq} · ITU {ent.itu}" if ent else "indicativo desconhecido"
        s = self.settings
        if ent and (s.lat or s.lon):
            d, b = geo.distance_bearing(s.lat, s.lon, ent.lat, ent.lon)
            info += f" · {d:.0f} km · {b:.0f}°"
        st = self.get_state()
        if self.log and self.log.is_dupe(call, st.freq, st.mode):
            self.lbl_dupe.setText(f"DUPLICADO nesta banda e modo. {info}")
            self.lbl_dupe.setStyleSheet("font-weight:600; color:#ef5350")
        else:
            self.lbl_dupe.setText(info)
            self.lbl_dupe.setStyleSheet("font-weight:600; color:#9ccc65")

    def _add(self) -> None:
        call = self.ed_call.text().strip().upper()
        if not call:
            return
        if not self.log:
            self._open_log()
            if not self.log:
                return
        st = self.get_state()
        q = self.log.add(contests.ContestQso(call, st.freq, st.mode, "59" if st.mode not in ("CW", "CW-R", "RTTY") else "599",
                                             self.ed_exch.text().strip(), self.ed_rst.text().strip() or "59",
                                             self.ed_rexch.text().strip()))
        if q.dupe:
            self.lbl_dupe.setText(f"{call} registrado como DUPLICADO (não conta pontos).")
            self.lbl_dupe.setStyleSheet("font-weight:600; color:#ffa726")
        self.ed_call.clear()
        self.ed_rexch.clear()
        self.ed_rst.setText("59" if st.mode not in ("CW", "CW-R", "RTTY") else "599")
        self._refresh_log()
        self._next_exchange()
        self.ed_call.setFocus()

    def _refresh_log(self) -> None:
        if not self.log:
            return
        qsos = list(reversed(self.log.all()))
        self.tbl_log.setRowCount(len(qsos))
        for r, q in enumerate(qsos):
            vals = (q.when, q.call + ("  (dup)" if q.dupe else ""), f"{q.freq / 1e3:.1f}", q.mode, q.rst_sent, q.exch_sent,
                    q.rst_rcvd, q.exch_rcvd)
            for c, v in enumerate(vals):
                item = QtWidgets.QTableWidgetItem(v)
                if q.dupe:
                    item.setForeground(QtGui.QColor("#ffa726"))
                item.setData(QtCore.Qt.ItemDataRole.UserRole, q.id)
                self.tbl_log.setItem(r, c, item)
        st = self.log.stats(self.cty)
        bands = ", ".join(f"{b}m: {n}" for b, n in sorted(st["bands"].items(), key=lambda kv: -kv[1])) or "—"
        self.lbl_stats.setText(f"{self.log.contest}: {st['qsos']} QSOs válidos · {st['dupes']} duplicados · "
                               f"{st.get('dxcc', 0)} entidades DXCC · {st.get('cq_zones', 0)} zonas CQ · {bands}")

    def _delete(self) -> None:
        row = self.tbl_log.currentRow()
        if self.log and row >= 0:
            self.log.delete(self.tbl_log.item(row, 0).data(QtCore.Qt.ItemDataRole.UserRole))
            self._refresh_log()
            self._next_exchange()

    # ---------------------------------------------------------------- Cabrillo
    def _edit_header(self) -> None:
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Cabeçalho do Cabrillo")
        form = QtWidgets.QFormLayout(dlg)
        edits = {}
        for key, label, default in CABRILLO_FIELDS:
            edits[key] = QtWidgets.QLineEdit(str(self.settings.cabrillo.get(key, default)))
            form.addRow(label, edits[key])
        hint = QtWidgets.QLabel("Categorias e troca variam por concurso: confira as regras e os valores aceitos antes de enviar.")
        hint.setWordWrap(True)
        form.addRow(hint)
        box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        form.addRow(box)
        if dlg.exec():
            self.settings.cabrillo = {k: e.text().strip() for k, e in edits.items()}
            self.settings.save()

    def _export(self) -> None:
        call = self.get_call()
        if not self.log or not call:
            QtWidgets.QMessageBox.information(self, "Cabrillo", "Abra um log e informe seu indicativo na aba Local / GPS.")
            return
        header = {k: d for k, _, d in CABRILLO_FIELDS if d}
        header.update(self.settings.cabrillo)
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Exportar Cabrillo", f"{call.upper()}.log", "Cabrillo (*.log *.cbr)")
        if path:
            Path(path).write_text(self.log.export_cabrillo(call, header, self.ed_cab_id.text().strip()), encoding="utf-8")
            QtWidgets.QMessageBox.information(self, "Cabrillo", f"{len(self.log.all())} QSOs exportados.\nConfira o cabeçalho e as regras do concurso antes de enviar.")
