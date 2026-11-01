"""Janela principal do app IC-7300."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from .. import audio as audio_mod
from .. import civ, geo
from .. import ft8 as ft8_mod
from ..ftengine import FtEngine, RxLine, suggest_reply
from ..bands import MODE_LABELS, USE_LABELS, BandPlan, choose_plan
from ..dsp.cw_decoder import CwDecoder
from ..dsp.spectrum import AudioSpectrum
from ..dxcc import Cty
from ..logbook import Logbook, Qso, ref_kind
from ..radio import Radio, RadioState, SerialTransport, SimTransport, list_serial_ports, power_watts, s_meter_text, swr_value
from ..rigctl import RigctlServer
from ..settings import Settings
from ..spots import ClusterClient, Spot, fetch_pota
from .conteststab import ContestsTab
from .digitaltabs import JtTab, RttyTab
from .sstvtab import SstvTab
from .maptab import MapTab
from .potatab import PotaTab
from .swltab import SwlTab
from .widgets import FrequencyDisplay, SpectrumView

MODE_BUTTONS = ["LSB", "USB", "CW", "CW-R", "AM", "FM", "RTTY"]
MODE_STEPS = {"LSB": 500, "USB": 500, "CW": 100, "CW-R": 100, "AM": 1000, "FM": 1000, "RTTY": 100, "RTTY-R": 100}
SCOPE_SPAN_LABELS = ["±2,5 kHz", "±5 kHz", "±10 kHz", "±25 kHz", "±50 kHz", "±100 kHz", "±250 kHz", "±500 kHz"]


class Bridge(QtCore.QObject):
    """Leva eventos de threads de rádio/áudio/rede para a thread da interface."""
    state = QtCore.Signal(object)
    scope = QtCore.Signal(object)
    message = QtCore.Signal(str)
    audio_row = QtCore.Signal(object)
    cw_text = QtCore.Signal(str)
    spot = QtCore.Signal(object)
    pota = QtCore.Signal(object)
    ft_rx = QtCore.Signal(object)
    ft_msg = QtCore.Signal(str)
    ft_stop = QtCore.Signal()


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("IC-7300 Station")
        self.resize(1360, 900)
        self.settings = Settings.load()
        self.plan = BandPlan()
        self.cty = Cty()
        self.plan.select(self._resolve_plan())
        self.log = Logbook()
        self.bridge = Bridge()
        self.radio: Optional[Radio] = None
        self.audio: Optional[audio_mod.AudioSource] = None
        self.cluster: Optional[ClusterClient] = None
        self.gps: Optional[geo.GpsReader] = None
        self.rigctl: Optional[RigctlServer] = None
        self.state = RadioState()
        self.cw = CwDecoder()
        self.ft = FtEngine(self.bridge.ft_rx.emit, self.bridge.ft_msg.emit, self._ft_ptt, self._ft_play)
        self.audio_spec = AudioSpectrum()
        self._last_scope = 0.0
        self._last_audio_row = 0.0
        self._ptt_user = False

        self._build_ui()
        self._wire()
        self._refresh_ports()
        self.clock = QtCore.QTimer(self, interval=1000, timeout=self._tick)
        self.clock.start()
        self._tick()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)

        # Conexão
        conn = QtWidgets.QHBoxLayout()
        self.cb_port = QtWidgets.QComboBox()
        self.cb_port.setMinimumWidth(220)
        self.cb_baud = QtWidgets.QComboBox()
        self.cb_baud.addItems(["115200", "57600", "38400", "19200", "9600", "4800"])
        self.cb_baud.setCurrentText(str(self.settings.baud))
        self.ed_addr = QtWidgets.QLineEdit(f"{self.settings.civ_address:02X}")
        self.ed_addr.setMaximumWidth(40)
        self.cb_audio = QtWidgets.QComboBox()
        self.cb_audio.setMinimumWidth(200)
        self.chk_sim = QtWidgets.QCheckBox("Simulador (sem rádio)")
        self.chk_sim.setChecked(self.settings.simulator)
        self.btn_connect = QtWidgets.QPushButton("Conectar")
        self.btn_refresh = QtWidgets.QPushButton("↻")
        self.btn_refresh.setMaximumWidth(30)
        for label, w in (("Porta CI-V", self.cb_port), ("", self.btn_refresh), ("Baud", self.cb_baud),
                         ("Endereço", self.ed_addr), ("Áudio", self.cb_audio)):
            if label:
                conn.addWidget(QtWidgets.QLabel(label))
            conn.addWidget(w)
        self.chk_rigctl = QtWidgets.QCheckBox(f"Servidor rigctl (porta {self.settings.rigctl_port})")
        self.chk_rigctl.setToolTip("Permite que WSJT-X, JS8Call, Fldigi etc. usem este app como rádio (Hamlib NET rigctl, 127.0.0.1)")
        self.chk_rigctl.setChecked(self.settings.rigctl_enabled)
        conn.addWidget(self.chk_sim)
        conn.addWidget(self.chk_rigctl)
        conn.addStretch()
        self.lbl_status = QtWidgets.QLabel("● Desconectado")
        conn.addWidget(self.lbl_status)
        conn.addWidget(self.btn_connect)
        root.addLayout(conn)

        # Frequência, modo, PTT
        top = QtWidgets.QHBoxLayout()
        self.freq_disp = FrequencyDisplay()
        top.addWidget(self.freq_disp, 3)
        ctrl = QtWidgets.QVBoxLayout()
        row = QtWidgets.QHBoxLayout()
        self.mode_btns: dict[str, QtWidgets.QPushButton] = {}
        grp = QtWidgets.QButtonGroup(self)
        for m in MODE_BUTTONS:
            b = QtWidgets.QPushButton(m)
            b.setCheckable(True)
            grp.addButton(b)
            row.addWidget(b)
            self.mode_btns[m] = b
            b.clicked.connect(lambda _=False, mode=m: self._set_mode(mode))
        self.chk_data = QtWidgets.QCheckBox("DATA")
        self.cb_filter = QtWidgets.QComboBox()
        self.cb_filter.addItems(["FIL1", "FIL2", "FIL3"])
        self.cb_step = QtWidgets.QComboBox()
        for s in (10, 50, 100, 500, 1000, 2500, 5000, 10000):
            self.cb_step.addItem(f"{s} Hz" if s < 1000 else f"{s // 1000} kHz", s)
        self.cb_step.setCurrentIndex(3)
        row.addWidget(self.chk_data)
        row.addWidget(self.cb_filter)
        row.addWidget(QtWidgets.QLabel("Passo"))
        row.addWidget(self.cb_step)
        ctrl.addLayout(row)
        row2 = QtWidgets.QHBoxLayout()
        self.band_row = row2
        self.band_btns: dict[str, QtWidgets.QPushButton] = {}
        ctrl.addLayout(row2)
        self._rebuild_band_buttons()
        row3 = QtWidgets.QHBoxLayout()
        self.lbl_seg = QtWidgets.QLabel("")
        self.lbl_seg.setStyleSheet("font-weight:600")
        row3.addWidget(self.lbl_seg, 1)
        self.cb_span = QtWidgets.QComboBox()
        self.cb_span.addItems(SCOPE_SPAN_LABELS)
        self.cb_span.setCurrentIndex(3)
        row3.addWidget(QtWidgets.QLabel("Scope"))
        row3.addWidget(self.cb_span)
        ctrl.addLayout(row3)
        top.addLayout(ctrl, 4)
        self.btn_ptt = QtWidgets.QPushButton("PTT")
        self.btn_ptt.setCheckable(True)
        self.btn_ptt.setMinimumSize(90, 90)
        self.btn_ptt.setStyleSheet("QPushButton{font:700 16pt; background:#3a3f47; border-radius:10px}"
                                   "QPushButton:checked{background:#d32f2f; color:white}")
        top.addWidget(self.btn_ptt)
        root.addLayout(top)

        # Medidores
        meters = QtWidgets.QHBoxLayout()
        self.bar_s, self.bar_po, self.bar_swr = (self._meter(n, 255) for n in ("S", "PO", "SWR"))
        for bar in (self.bar_s, self.bar_po, self.bar_swr):
            meters.addWidget(bar)
        root.addLayout(meters)

        # Espectro + abas
        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.spectrum = SpectrumView(self.plan)
        split.addWidget(self.spectrum)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._tab_cw(), "CW")
        self.map = MapTab(self.plan, self.cty)
        self.tabs.addTab(self.map, "Mapa / Propagação")
        self.pota = PotaTab(self.plan, self.log, lambda: (self.settings.lat, self.settings.lon) if (self.settings.lat or self.settings.lon) else None)
        self.tabs.addTab(self.pota, "POTA")
        self.pota.spot_chosen.connect(self._pota_chosen)
        self.pota.spots_loaded.connect(self._pota_to_map)
        self.rtty = RttyTab(self.settings, lambda: self.state, self._ft_ptt, self._ft_play, lambda: self.ed_call.text().strip().upper())
        self.tabs.addTab(self.rtty, "RTTY")
        self.sstv = SstvTab(self.settings, lambda: self.state, self._ft_ptt, self._ft_play)
        self.tabs.addTab(self.sstv, "SSTV")
        self.sstv.tune_requested.connect(self._sstv_tune)
        self.jt = JtTab(self.settings, self.cty, lambda: self.state)
        self.tabs.addTab(self.jt, "FST4 / Q65 / WSPR")
        self.contests = ContestsTab(self.settings, self.cty, lambda: self.state, lambda: self.settings.callsign)
        self.tabs.addTab(self.contests, "Concursos")
        self.swl = SwlTab(self.plan)
        self.tabs.addTab(self.swl, "Ondas curtas")
        self.map.solar_updated.connect(self.swl.set_solar)
        self.swl.tune_requested.connect(self._swl_tune)
        self.tabs.addTab(self._tab_ft(), "FT8 / FT4")
        self.tabs.addTab(self._tab_digital(), "Modos digitais")
        self.tabs.addTab(self._tab_bands(), "Plano de bandas")
        self.tabs.addTab(self._tab_spots(), "DX Cluster / POTA")
        self.tabs.addTab(self._tab_log(), "Log")
        self.tabs.addTab(self._tab_location(), "Local / GPS")
        split.addWidget(self.tabs)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        root.addWidget(split, 1)

        self.lbl_utc = QtWidgets.QLabel()
        self.lbl_grid = QtWidgets.QLabel()
        self.statusBar().addPermanentWidget(self.lbl_grid)
        self.statusBar().addPermanentWidget(self.lbl_utc)
        self.setStyleSheet("QMainWindow,QWidget{background:#171c23;color:#d6dde6}"
                           "QPushButton{background:#2a323d;border:1px solid #3a4452;border-radius:5px;padding:5px 9px}"
                           "QPushButton:checked{background:#2e7d32}QPushButton:hover{background:#34404e}"
                           "QLineEdit,QComboBox,QPlainTextEdit,QTableWidget,QSpinBox,QDoubleSpinBox{background:#10151c;border:1px solid #2c3541;padding:3px}"
                           "QTabBar::tab{padding:6px 14px;background:#222a34}QTabBar::tab:selected{background:#2e7d32}"
                           "QHeaderView::section{background:#222a34;border:0;padding:4px}"
                           "QProgressBar{border:1px solid #2c3541;text-align:center;background:#10151c}"
                           "QProgressBar::chunk{background:#43a047}")

    def _meter(self, name: str, maximum: int) -> QtWidgets.QProgressBar:
        bar = QtWidgets.QProgressBar()
        bar.setRange(0, maximum)
        bar.setFormat(f"{name}  %v")
        return bar

    def _table(self, headers: list[str]) -> QtWidgets.QTableWidget:
        t = QtWidgets.QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        t.horizontalHeader().setStretchLastSection(True)
        t.verticalHeader().setVisible(False)
        return t

    def _tab_cw(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        info = QtWidgets.QHBoxLayout()
        self.lbl_cw = QtWidgets.QLabel("Tom: --- Hz · --- WPM")
        self.chk_auto_tone = QtWidgets.QCheckBox("Seguir o tom automaticamente")
        self.chk_auto_tone.setChecked(True)
        self.sp_tone = QtWidgets.QSpinBox()
        self.sp_tone.setRange(300, 1200)
        self.sp_tone.setValue(600)
        self.sp_tone.setSuffix(" Hz")
        btn_clear = QtWidgets.QPushButton("Limpar")
        info.addWidget(self.lbl_cw)
        info.addStretch()
        info.addWidget(self.chk_auto_tone)
        info.addWidget(self.sp_tone)
        info.addWidget(btn_clear)
        lay.addLayout(info)
        self.txt_cw = QtWidgets.QPlainTextEdit(readOnly=True)
        self.txt_cw.setStyleSheet("font: 14pt 'Consolas'")
        lay.addWidget(self.txt_cw, 1)
        send = QtWidgets.QHBoxLayout()
        self.ed_cw = QtWidgets.QLineEdit()
        self.ed_cw.setPlaceholderText("Texto para enviar em CW (manipulador do rádio, modo CW)")
        btn_send = QtWidgets.QPushButton("Enviar")
        btn_stop = QtWidgets.QPushButton("Parar")
        send.addWidget(self.ed_cw, 1)
        send.addWidget(btn_send)
        send.addWidget(btn_stop)
        lay.addLayout(send)
        macros = QtWidgets.QHBoxLayout()
        for i, text in enumerate(self.settings.cw_macros[:8]):
            b = QtWidgets.QPushButton(f"F{i + 1}")
            b.setToolTip(text)
            b.clicked.connect(lambda _=False, t=text: self._send_cw(self._expand_macro(t)))
            macros.addWidget(b)
        lay.addLayout(macros)
        btn_clear.clicked.connect(lambda: (self.txt_cw.clear(), self.cw.reset()))
        btn_send.clicked.connect(lambda: self._send_cw(self.ed_cw.text()))
        self.ed_cw.returnPressed.connect(lambda: self._send_cw(self.ed_cw.text()))
        btn_stop.clicked.connect(lambda: self.radio and self.radio.stop_cw())
        self.sp_tone.valueChanged.connect(self._tone_changed)
        self.chk_auto_tone.toggled.connect(self._tone_changed)
        return w

    def _tab_ft(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        top = QtWidgets.QHBoxLayout()
        self.cb_ftmode = QtWidgets.QComboBox()
        self.cb_ftmode.addItems(["FT8", "FT4"])
        self.sp_ftfreq = QtWidgets.QSpinBox()
        self.sp_ftfreq.setRange(200, 3000)
        self.sp_ftfreq.setValue(1500)
        self.sp_ftfreq.setSuffix(" Hz")
        self.cb_ftslot = QtWidgets.QComboBox()
        self.cb_ftslot.addItems(["TX em slots pares (:00/:30)", "TX em slots ímpares (:15/:45)"])
        self.sl_level = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.sl_level.setRange(5, 100)
        self.sl_level.setValue(30)
        self.sl_level.setMaximumWidth(120)
        self.lbl_slot = QtWidgets.QLabel("")
        self.lbl_slot.setStyleSheet("font: 600 12pt 'Consolas'")
        for x in (QtWidgets.QLabel("Modo"), self.cb_ftmode, QtWidgets.QLabel("Tom TX"), self.sp_ftfreq, self.cb_ftslot,
                  QtWidgets.QLabel("Nível"), self.sl_level):
            top.addWidget(x)
        top.addStretch()
        top.addWidget(self.lbl_slot)
        lay.addLayout(top)
        self.tbl_ft = self._table(["UTC", "SNR", "DT", "Freq", "Mensagem", "País"])
        lay.addWidget(self.tbl_ft, 1)
        tx = QtWidgets.QHBoxLayout()
        self.ed_fttx = QtWidgets.QLineEdit()
        self.ed_fttx.setPlaceholderText("Mensagem a transmitir (ex.: CQ PY2XX GG66). Duplo clique numa linha sugere a resposta")
        self.chk_fttx = QtWidgets.QCheckBox("Habilitar TX")
        self.btn_cq = QtWidgets.QPushButton("CQ")
        self.btn_halt = QtWidgets.QPushButton("Parar TX")
        self.btn_halt.setStyleSheet("background:#8e2420")
        for x in (self.ed_fttx, self.btn_cq, self.chk_fttx, self.btn_halt):
            tx.addWidget(x)
        tx.setStretch(0, 1)
        lay.addLayout(tx)
        self.lbl_ft = QtWidgets.QLabel("" if ft8_mod.available() else
                                       "ft8.dll não encontrada: rode 'python build_native.py' para compilar o decoder.")
        lay.addWidget(self.lbl_ft)
        self.ft.tx_level = 0.3
        self.cb_ftmode.currentTextChanged.connect(self._ft_mode)
        self.sp_ftfreq.valueChanged.connect(lambda v: setattr(self.ft, "tx_freq", float(v)))
        self.cb_ftslot.currentIndexChanged.connect(lambda i: setattr(self.ft, "tx_even", i == 0))
        self.sl_level.valueChanged.connect(lambda v: setattr(self.ft, "tx_level", v / 100))
        self.ed_fttx.textChanged.connect(lambda t: setattr(self.ft, "tx_text", t.strip().upper()))
        self.btn_cq.clicked.connect(self._ft_cq)
        self.chk_fttx.toggled.connect(self._ft_tx_toggled)
        self.btn_halt.clicked.connect(self._ft_halt)
        self.tbl_ft.cellDoubleClicked.connect(self._ft_reply)
        return w

    def _tab_digital(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        top = QtWidgets.QHBoxLayout()
        self.chk_dig_band = QtWidgets.QCheckBox("Somente a banda atual")
        self.chk_dig_band.setChecked(True)
        top.addWidget(self.chk_dig_band)
        top.addStretch()
        lay.addLayout(top)
        self.tbl_dig = self._table(["Modo / banda", "Frequência (kHz)", "Tipo"])
        lay.addWidget(self.tbl_dig, 1)
        note = QtWidgets.QLabel("Duplo clique: sintoniza a frequência e coloca o rádio em USB + DATA. "
                                "A decodificação de FT8/FT4/JS8/WSPR ainda não está embutida: use WSJT-X / JS8Call "
                                "apontados para o 'USB Audio CODEC' do rádio.")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.tbl_dig.cellDoubleClicked.connect(self._dig_double)
        self.chk_dig_band.toggled.connect(self._fill_digital)
        return w

    def _tab_bands(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        self.lbl_plan = QtWidgets.QLabel("")
        self.lbl_plan.setStyleSheet("font: 600 11pt")
        self.lbl_plan.setWordWrap(True)
        lay.addWidget(self.lbl_plan)
        self.lbl_band_now = QtWidgets.QLabel("")
        self.lbl_band_now.setStyleSheet("font: 600 12pt")
        self.lbl_band_now.setWordWrap(True)
        lay.addWidget(self.lbl_band_now)
        self.tbl_bands = self._table(["Banda", "Início (kHz)", "Fim (kHz)", "Uso", "Modos liberados", "Classes", "Obs."])
        self.tbl_bands.setColumnWidth(4, 260)
        lay.addWidget(self.tbl_bands, 1)
        self.lbl_plan_src = QtWidgets.QLabel("")
        self.lbl_plan_src.setWordWrap(True)
        self.lbl_plan_src.setStyleSheet("color:#8a97a8; font-size:8pt")
        lay.addWidget(self.lbl_plan_src)
        self.tbl_bands.cellDoubleClicked.connect(
            lambda r, c: self._tune(self.plan.segments[r].start + 1000, auto_mode=True))
        self._fill_bands()
        return w

    def _fill_bands(self) -> None:
        cls = self._cls()
        self.tbl_bands.setRowCount(0)
        for seg in self.plan.segments:
            r = self.tbl_bands.rowCount()
            self.tbl_bands.insertRow(r)
            modes = ", ".join(MODE_LABELS.get(m, m) for m in seg.modes) if seg.modes else "(plano genérico)"
            classes = "/".join(seg.classes) if seg.classes else "—"
            vals = (seg.band, f"{seg.start / 1e3:g}", f"{seg.stop / 1e3:g}", USE_LABELS.get(seg.use, seg.use), modes, classes, seg.note)
            for c, v in enumerate(vals):
                item = QtWidgets.QTableWidgetItem(v)
                if cls and seg.classes and cls not in seg.classes:
                    item.setForeground(QtGui.QColor("#6b7685"))  # fora dos privilégios da sua classe
                self.tbl_bands.setItem(r, c, item)
        power = ""
        if cls and self.plan.max_power(cls):
            power = f" · potência máxima da classe {cls}: {self.plan.max_power(cls)} W"
        label = self.plan.classes.get(cls, cls)
        self.lbl_plan.setText(f"Plano ativo: {self.plan.name}" + (f" · sua classe: {label}" if cls else (" · informe sua classe em Local / GPS" if self.plan.classes else "")) + power)
        legend = ("Classes: " + "; ".join(f"{c} = {n}" for c, n in self.plan.classes.items()) + ". ") if self.plan.classes else ""
        self.lbl_plan_src.setText(legend + self.plan.info.get("source", "") + " " + self.plan.info.get("power_note", "") +
                                  " Linhas em cinza: fora dos privilégios da sua classe. O app avisa, mas não impede, e não substitui a regulamentação.")

    def _resolve_plan(self, band_plan: str | None = None, callsign: str | None = None) -> str:
        chosen = self.settings.band_plan if band_plan is None else band_plan
        if chosen and chosen != "auto" and chosen in self.plan.plans:
            return chosen
        call = self.settings.callsign if callsign is None else callsign
        return choose_plan(call, self.settings.lat, self.settings.lon, self.cty, set(self.plan.plans))

    def _cls(self) -> str:
        """Classe de licença informada para o plano ativo."""
        return self.settings.classes_by_plan.get(self.plan.plan_id, "")

    def _preview_plan(self) -> str:
        """Plano que valerá com os campos de Local / GPS como estão agora (antes de salvar)."""
        return self._resolve_plan(self.cb_plan.currentData(), self.ed_mycall.text().strip().upper())

    def _fill_class_combo(self, plan_id: str) -> None:
        classes = self.plan.plans[plan_id].get("classes") or {}
        current = self.settings.classes_by_plan.get(plan_id, "")
        self.cb_class.blockSignals(True)
        self.cb_class.clear()
        self.cb_class.addItem("Não informar" if classes else "(este plano não tem classes)", "")
        for code, label in classes.items():
            self.cb_class.addItem(label, code)
        self.cb_class.setCurrentIndex(max(0, self.cb_class.findData(current)))
        self.cb_class.setEnabled(bool(classes))
        self.cb_class.blockSignals(False)

    def _preview_class_combo(self) -> None:
        self._fill_class_combo(self._preview_plan())

    def _apply_plan(self) -> None:
        self.plan.select(self._resolve_plan())
        self._fill_class_combo(self.plan.plan_id)
        self._rebuild_band_buttons()
        self._fill_bands()
        self.spectrum._range_drawn = None
        self.spectrum._draw_bandplan()
        self._dig_key = None
        self._fill_digital()
        self._on_state(self.state)

    def _rebuild_band_buttons(self) -> None:
        while self.band_row.count():
            item = self.band_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.band_btns = {}
        for name in self.plan.band_names():
            b = QtWidgets.QPushButton(name)
            b.setMaximumWidth(52)
            b.clicked.connect(lambda _=False, n=name: self._goto_band(n))
            self.band_row.addWidget(b)
            self.band_btns[name] = b

    def _tx_guard(self, category: str | None = None) -> bool:
        """Avisa quando a transmissão agora não é compatível com o plano, a classe e a emissão; o operador decide."""
        st = self.state
        cat = category or self.plan.category(st.mode, st.data_mode)
        status = self.plan.tx_status(st.freq, self._cls(), cat)
        if status.ok:
            return True
        answer = QtWidgets.QMessageBox.warning(
            self, "Verifique antes de transmitir", status.text + "\n\nO app apenas avisa; a responsabilidade é do operador. "
            "Transmitir mesmo assim?", QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No)
        return answer == QtWidgets.QMessageBox.StandardButton.Yes

    def _ft_allowed(self) -> bool:  # thread de áudio: sem diálogo
        st = self.state
        ok = self.plan.tx_status(st.freq, self._cls(), "DIG").ok
        if not ok:
            self.bridge.ft_stop.emit()
        return ok

    def _tab_spots(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        top = QtWidgets.QHBoxLayout()
        self.ed_host = QtWidgets.QLineEdit(self.settings.cluster_host)
        self.sp_cport = QtWidgets.QSpinBox()
        self.sp_cport.setRange(1, 65535)
        self.sp_cport.setValue(self.settings.cluster_port)
        self.btn_cluster = QtWidgets.QPushButton("Conectar cluster")
        self.btn_pota = QtWidgets.QPushButton("Atualizar POTA")
        self.lbl_cluster = QtWidgets.QLabel("")
        for x in (QtWidgets.QLabel("Servidor"), self.ed_host, self.sp_cport, self.btn_cluster, self.btn_pota, self.lbl_cluster):
            top.addWidget(x)
        top.addStretch()
        lay.addLayout(top)
        self.tbl_spots = self._table(["Fonte", "Indicativo", "Freq (kHz)", "País", "Dist./Az.", "Info", "Hora"])
        lay.addWidget(self.tbl_spots, 1)
        self.spots: list[Spot] = []
        self.btn_cluster.clicked.connect(self._toggle_cluster)
        self.btn_pota.clicked.connect(self._load_pota)
        self.tbl_spots.cellDoubleClicked.connect(self._spot_double)
        return w

    def _tab_log(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        form = QtWidgets.QHBoxLayout()
        self.ed_call = QtWidgets.QLineEdit(placeholderText="Indicativo")
        self.ed_rs = QtWidgets.QLineEdit("59")
        self.ed_rr = QtWidgets.QLineEdit("59")
        self.ed_name = QtWidgets.QLineEdit(placeholderText="Nome")
        self.ed_qgrid = QtWidgets.QLineEdit(placeholderText="Grid")
        self.ed_cmt = QtWidgets.QLineEdit(placeholderText="Comentário")
        btn_add = QtWidgets.QPushButton("Registrar QSO")
        btn_exp = QtWidgets.QPushButton("Exportar ADIF")
        for x in (self.ed_call, self.ed_rs, self.ed_rr, self.ed_name, self.ed_qgrid, self.ed_cmt, btn_add, btn_exp):
            form.addWidget(x)
        refs = QtWidgets.QHBoxLayout()
        self.ed_ref = QtWidgets.QLineEdit(placeholderText="Referência do contato (POTA BR-0123, SOTA PY/SP-001, WWFF PYFF-0001)")
        self.ed_myref = QtWidgets.QLineEdit(self.settings.my_ref, placeholderText="Minha referência, se ativando")
        btn_exp_ref = QtWidgets.QPushButton("ADIF da ativação")
        self.lbl_act = QtWidgets.QLabel("")
        for x in (self.ed_ref, self.ed_myref, btn_exp_ref, self.lbl_act):
            refs.addWidget(x)
        refs.setStretch(0, 3)
        refs.setStretch(1, 2)
        self.ed_rs.setMaximumWidth(50)
        self.ed_rr.setMaximumWidth(50)
        self.ed_qgrid.setMaximumWidth(80)
        lay.addLayout(form)
        lay.addLayout(refs)
        self.lbl_dxcc = QtWidgets.QLabel("")
        lay.addWidget(self.lbl_dxcc)
        self.tbl_log = self._table(["UTC", "Indicativo", "Freq (kHz)", "Modo", "RST env.", "RST rec.", "País", "Nome", "Grid", "Referência", "Minha ref."])
        lay.addWidget(self.tbl_log, 1)
        self.ed_call.textChanged.connect(self._lookup_call)
        btn_add.clicked.connect(self._add_qso)
        btn_exp.clicked.connect(lambda: self._export_adif(False))
        btn_exp_ref.clicked.connect(lambda: self._export_adif(True))
        self.ed_myref.textChanged.connect(self._myref_changed)
        self._fill_log()
        return w

    def _tab_location(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(w)
        self.ed_mycall = QtWidgets.QLineEdit(self.settings.callsign)
        self.ed_mycall.editingFinished.connect(lambda: self._fill_class_combo(self._preview_plan()))
        self.ed_mygrid = QtWidgets.QLineEdit(self.settings.grid)
        self.sp_lat = QtWidgets.QDoubleSpinBox()
        self.sp_lat.setRange(-90, 90)
        self.sp_lat.setDecimals(5)
        self.sp_lat.setValue(self.settings.lat)
        self.sp_lon = QtWidgets.QDoubleSpinBox()
        self.sp_lon.setRange(-180, 180)
        self.sp_lon.setDecimals(5)
        self.sp_lon.setValue(self.settings.lon)
        self.cb_gps = QtWidgets.QComboBox()
        self.cb_gps.setEditable(True)
        self.btn_gps = QtWidgets.QPushButton("Iniciar GPS")
        btn_grid = QtWidgets.QPushButton("Grid → lat/lon")
        btn_ll = QtWidgets.QPushButton("Lat/lon → grid")
        btn_save = QtWidgets.QPushButton("Salvar")
        form.addRow("Meu indicativo", self.ed_mycall)
        form.addRow("Grid Maidenhead", self.ed_mygrid)
        form.addRow("Latitude (° , sul negativo)", self.sp_lat)
        form.addRow("Longitude (° , oeste negativo)", self.sp_lon)
        self.cb_plan = QtWidgets.QComboBox()
        self.cb_plan.addItem("Automático (pelo indicativo ou local)", "auto")
        for pid, pname in self.plan.available():
            self.cb_plan.addItem(pname, pid)
        self.cb_plan.setCurrentIndex(max(0, self.cb_plan.findData(self.settings.band_plan)))
        self.cb_class = QtWidgets.QComboBox()
        self._fill_class_combo(self.plan.plan_id)
        self.cb_plan.currentIndexChanged.connect(self._preview_class_combo)
        form.addRow("Plano de bandas", self.cb_plan)
        form.addRow("Classe da licença", self.cb_class)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(btn_grid)
        row.addWidget(btn_ll)
        row.addWidget(btn_save)
        form.addRow(row)
        grow = QtWidgets.QHBoxLayout()
        grow.addWidget(self.cb_gps, 1)
        grow.addWidget(self.btn_gps)
        form.addRow("Porta do GPS (NMEA)", grow)
        self.lbl_gps = QtWidgets.QLabel("")
        form.addRow(self.lbl_gps)
        btn_grid.clicked.connect(self._grid_to_ll)
        btn_ll.clicked.connect(self._ll_to_grid)
        btn_save.clicked.connect(self._save_location)
        self.btn_gps.clicked.connect(self._toggle_gps)
        return w

    # ---------------------------------------------------------------- wiring
    def _wire(self) -> None:
        self.btn_connect.clicked.connect(self._toggle_connect)
        self.chk_rigctl.toggled.connect(self._toggle_rigctl)
        if self.chk_rigctl.isChecked():
            QtCore.QTimer.singleShot(0, lambda: self._toggle_rigctl(True))
        self.btn_refresh.clicked.connect(self._refresh_ports)
        self.freq_disp.tuned.connect(self._tune)
        self.spectrum.clicked_freq.connect(self._click_tune)
        self.cb_step.currentIndexChanged.connect(lambda: setattr(self.freq_disp, "step", self.cb_step.currentData()))
        self.freq_disp.step = self.cb_step.currentData()
        self.btn_ptt.toggled.connect(self._ptt)
        self.chk_data.toggled.connect(lambda: self._set_mode(self.state.mode))
        self.cb_filter.currentIndexChanged.connect(lambda: self._set_mode(self.state.mode))
        self.cb_span.currentIndexChanged.connect(self._span_changed)
        self.bridge.state.connect(self._on_state)
        self.bridge.scope.connect(self._on_scope)
        self.bridge.message.connect(lambda m: self.statusBar().showMessage(m, 6000))
        self.bridge.audio_row.connect(self._on_audio_row)
        self.bridge.cw_text.connect(self._on_cw_text)
        self.bridge.spot.connect(self._on_spot)
        self.bridge.pota.connect(self._on_pota)
        self.bridge.ft_rx.connect(self._on_ft_rx)
        self.bridge.ft_stop.connect(self._ft_halt)
        self.ft.tx_allowed = self._ft_allowed
        self.rtty.guard = self._tx_guard
        self.sstv.guard = self._tx_guard
        self.bridge.ft_msg.connect(lambda m: (self.lbl_ft.setText(m), self.statusBar().showMessage(m, 8000)))
        self._fill_digital()
        self.map.set_home(self.settings.lat, self.settings.lon, self.settings.callsign)
        self.swl.set_home(self.settings.lat, self.settings.lon)

    # --------------------------------------------------------------- conexão
    def _refresh_ports(self) -> None:
        self.cb_port.clear()
        for dev, desc in list_serial_ports():
            self.cb_port.addItem(f"{dev} — {desc}", dev)
        if self.settings.port:
            i = self.cb_port.findData(self.settings.port)
            if i >= 0:
                self.cb_port.setCurrentIndex(i)
        self.cb_gps.clear()
        self.cb_gps.addItems([d for d, _ in list_serial_ports()])
        self.cb_audio.clear()
        self.cb_audio.addItem("(automático: USB Audio CODEC)", "")
        for n in audio_mod.list_input_devices():
            self.cb_audio.addItem(n, n)

    def _toggle_connect(self) -> None:
        if self.radio:
            self._disconnect()
            return
        try:
            if self.chk_sim.isChecked():
                transport = SimTransport()
            else:
                port = self.cb_port.currentData()
                if not port:
                    raise RuntimeError("Selecione a porta serial do IC-7300.")
                transport = SerialTransport(port, int(self.cb_baud.currentText()))
            addr = int(self.ed_addr.text(), 16)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Conexão", str(exc))
            return
        self.settings.simulator = self.chk_sim.isChecked()
        self.settings.port = self.cb_port.currentData() or ""
        self.settings.baud = int(self.cb_baud.currentText())
        self.settings.civ_address = addr
        self.settings.save()
        self.radio = Radio(transport, address=addr)
        self.radio.on_state = self.bridge.state.emit
        self.radio.on_scope = self.bridge.scope.emit
        self.radio.on_message = self.bridge.message.emit
        self.radio.start()
        self.radio.set_scope(True, civ.SCOPE_SPANS_HZ[self.cb_span.currentIndex()])
        self._start_audio()
        self.btn_connect.setText("Desconectar")

    def _toggle_rigctl(self, on: bool) -> None:
        if self.rigctl:
            self.rigctl.stop()
            self.rigctl = None
        if on:
            try:
                self.rigctl = RigctlServer(lambda: self.radio, lambda: self.state, port=self.settings.rigctl_port,
                                           on_message=self.bridge.message.emit)
                self.rigctl.start()
            except OSError as exc:
                QtWidgets.QMessageBox.warning(self, "rigctl", f"Não foi possível abrir a porta {self.settings.rigctl_port}: {exc}")
                self.rigctl = None
                self.chk_rigctl.blockSignals(True)
                self.chk_rigctl.setChecked(False)
                self.chk_rigctl.blockSignals(False)
                on = False
        self.settings.rigctl_enabled = on

    def _disconnect(self) -> None:
        if self.audio:
            self.audio.stop()
            self.audio = None
        if self.radio:
            if self.state.ptt:
                self.radio.set_ptt(False)
            self.radio.stop()
            self.radio = None
        self.btn_ptt.setChecked(False)
        self.btn_connect.setText("Conectar")
        self.lbl_status.setText("● Desconectado")
        self.lbl_status.setStyleSheet("color:#ef5350")
        self.spectrum.set_audio_mode(False)

    def _start_audio(self) -> None:
        if self.chk_sim.isChecked():
            self.audio = audio_mod.SimAudio(self._on_audio)
        else:
            dev = self.cb_audio.currentData() or audio_mod.find_radio_input()
            if not dev:
                self.bridge.message.emit("Codec de áudio do rádio não encontrado; CW e espectro de áudio indisponíveis.")
                return
            self.audio = audio_mod.DeviceAudio(dev, self._on_audio)
        try:
            self.audio.start()
        except Exception as exc:
            self.audio = None
            self.bridge.message.emit(f"Áudio: {exc}")

    def _on_audio(self, samples: np.ndarray) -> None:  # thread de áudio
        text = self.cw.process(samples)
        if text:
            self.bridge.cw_text.emit(text)
        if self.radio:
            self.ft.feed(samples)
            self.rtty.feed(samples)
            self.sstv.feed(samples)
            self.jt.feed(samples)
        row = self.audio_spec.push(samples)
        now = time.time()
        if row is not None and now - self._last_audio_row > 0.08:
            self._last_audio_row = now
            self.bridge.audio_row.emit(row)

    # ---------------------------------------------------------------- eventos
    def _on_state(self, st: RadioState) -> None:
        self.state = st
        self.freq_disp.set_freq(st.freq)
        self.spectrum.set_freq(st.freq)
        if st.connected:
            self.lbl_status.setText("● Conectado")
            self.lbl_status.setStyleSheet("color:#66bb6a")
        else:
            self.lbl_status.setText("● Sem resposta do rádio")
            self.lbl_status.setStyleSheet("color:#ffa726")
        btn = self.mode_btns.get(st.mode)
        if btn and not btn.isChecked():
            btn.setChecked(True)
        for w, v in ((self.chk_data, st.data_mode),):
            w.blockSignals(True)
            w.setChecked(v)
            w.blockSignals(False)
        self.cb_filter.blockSignals(True)
        self.cb_filter.setCurrentIndex(max(0, min(2, st.filter - 1)))
        self.cb_filter.blockSignals(False)
        self.freq_disp.step = self.cb_step.currentData() if st.mode not in ("CW", "CW-R") or self.cb_step.currentData() <= 1000 else 100
        self.bar_s.setValue(st.s_meter)
        self.bar_s.setFormat(f"S  {s_meter_text(st.s_meter)}")
        self.bar_po.setValue(st.power)
        self.bar_po.setFormat(f"PO  {power_watts(st.power):.0f} W")
        self.bar_swr.setValue(st.swr)
        self.bar_swr.setFormat(f"SWR  {swr_value(st.swr):.1f}")
        self.btn_ptt.blockSignals(True)
        self.btn_ptt.setChecked(st.ptt)
        self.btn_ptt.blockSignals(False)
        band = self.plan.band_for(st.freq)
        seg = self.plan.segment_for(st.freq)
        for n, b in self.band_btns.items():
            b.setStyleSheet("background:#2e7d32" if n == band else "")
        if seg:
            extra = f" · classes {'/'.join(seg.classes)}" if seg.classes else ""
            status = self.plan.tx_status(st.freq, self._cls(), self.plan.category(st.mode, st.data_mode))
            self.lbl_seg.setText(f"{seg.band} · {USE_LABELS.get(seg.use, seg.use)}{extra}")
            self.lbl_band_now.setText(f"Frequência atual: {st.freq / 1e3:.2f} kHz — {seg.band}, {USE_LABELS.get(seg.use, seg.use)}{extra}"
                                      + ("" if status.ok else f"\nAtenção: {status.text}"))
            self.lbl_seg.setStyleSheet("font-weight:600;color:#9ccc65" if status.ok else "font-weight:600;color:#ffa726")
        else:
            self.lbl_seg.setText("Fora das faixas de radioamador")
            self.lbl_band_now.setText(f"Frequência atual: {st.freq / 1e3:.2f} kHz — fora das faixas de radioamador")
            self.lbl_seg.setStyleSheet("font-weight:600;color:#ef5350")
        if band:
            self.settings.last_freq_by_band[band] = st.freq
        self._fill_digital()

    def _on_scope(self, line: civ.ScopeLine) -> None:
        self._last_scope = time.time()
        self.spectrum.set_audio_mode(False)
        self.spectrum.push_scope(line.values, line.low_hz, line.high_hz)

    def _on_audio_row(self, row: np.ndarray) -> None:
        if time.time() - self._last_scope > 1.5:  # sem scope do rádio: mostra o espectro do áudio
            self.spectrum.set_audio_mode(True)
            self.spectrum.push_audio(row, self.audio_spec.freqs)

    def _on_cw_text(self, text: str) -> None:
        self.txt_cw.moveCursor(QtGui.QTextCursor.MoveOperation.End)
        self.txt_cw.insertPlainText(text)
        self.txt_cw.moveCursor(QtGui.QTextCursor.MoveOperation.End)
        self.lbl_cw.setText(f"Tom: {self.cw.tone:.0f} Hz · {self.cw.wpm:.0f} WPM" + ("" if self.cw.snr_ok else " · sem sinal"))

    # ---------------------------------------------------------------- rádio
    def _tune(self, hz: int, auto_mode: bool = False) -> None:
        if not self.radio:
            self.bridge.message.emit("Conecte ao rádio (ou ao simulador) primeiro.")
            return
        hz = max(30_000, min(74_800_000, int(hz)))
        self.radio.set_freq(hz)
        if auto_mode:
            mode, data = self.plan.suggest_mode(hz)
            self.radio.set_mode(mode, data, self.state.filter)

    def _swl_tune(self, hz: int, mode: str) -> None:
        if not self.radio:
            self.bridge.message.emit("Conecte ao rádio (ou ao simulador) para sintonizar.")
            return
        self._tune(hz)
        self.radio.set_mode(mode, False, self.state.filter)

    def _sstv_tune(self, hz: int, sideband: str) -> None:
        if not self.radio:
            self.bridge.message.emit("Conecte ao rádio (ou ao simulador) para sintonizar.")
            return
        self._tune(hz)
        self.radio.set_mode(sideband, True, self.state.filter)

    def _click_tune(self, hz: int) -> None:
        step = self.cb_step.currentData() or 100
        self._tune(round(hz / step) * step)

    def _set_mode(self, mode: str) -> None:
        if self.radio:
            self.radio.set_mode(mode, self.chk_data.isChecked(), self.cb_filter.currentIndex() + 1)
        self.freq_disp.step = MODE_STEPS.get(mode, 500)

    def _goto_band(self, name: str) -> None:
        start, stop = self.plan.band_range(name)
        hz = self.settings.last_freq_by_band.get(name) or start + 20_000
        self._tune(hz, auto_mode=True)

    def _ptt(self, on: bool) -> None:
        if on and not self._tx_guard():
            self.btn_ptt.blockSignals(True)
            self.btn_ptt.setChecked(False)
            self.btn_ptt.blockSignals(False)
            return
        if self.radio:
            self.radio.set_ptt(on)

    def _span_changed(self) -> None:
        if self.radio:
            self.radio.set_scope_span(civ.SCOPE_SPANS_HZ[self.cb_span.currentIndex()])

    # ---------------------------------------------------------------- CW
    def _expand_macro(self, text: str) -> str:
        return text.replace("{call}", self.settings.callsign or "NOCALL").replace("{their}", self.ed_call.text().upper() or "")

    def _send_cw(self, text: str) -> None:
        if not self.radio:
            return
        if self.state.mode not in ("CW", "CW-R"):
            self.bridge.message.emit("Coloque o rádio em CW antes de enviar.")
            return
        if not self._tx_guard("CW"):
            return
        self.radio.send_cw(text)
        self.txt_cw.appendPlainText(f"\n>> {text}\n")

    def _tone_changed(self) -> None:
        self.cw.auto_tone = self.chk_auto_tone.isChecked()
        if not self.cw.auto_tone:
            self.cw.tone = float(self.sp_tone.value())

    # ---------------------------------------------------------------- FT8 / FT4
    def _ft_ptt(self, on: bool) -> None:
        if self.radio:
            self.radio.set_ptt(on)

    def _ft_play(self, samples: np.ndarray) -> None:  # thread de TX
        if self.chk_sim.isChecked():
            time.sleep(len(samples) / audio_mod.FS)
            return
        audio_mod.play_blocking(samples, self.settings.audio_output or audio_mod.find_radio_output())

    def _ft_mode(self, mode: str) -> None:
        self.ft.set_mode(mode)
        self.tbl_ft.setRowCount(0)

    def _ft_cq(self) -> None:
        call, grid = self.settings.callsign, self.settings.grid[:4]
        if not call:
            QtWidgets.QMessageBox.information(self, "FT8", "Informe seu indicativo na aba Local / GPS.")
            return
        self.ed_fttx.setText(f"CQ {call} {grid}".strip())

    def _ft_tx_toggled(self, on: bool) -> None:
        if not on:
            self.ft.tx_enabled = False
            return
        if not self.settings.callsign or not self.radio:
            QtWidgets.QMessageBox.information(self, "FT8", "Conecte ao rádio e informe seu indicativo antes de transmitir.")
            self.chk_fttx.setChecked(False)
            return
        if not self.chk_sim.isChecked():
            ok = QtWidgets.QMessageBox.question(
                self, "Habilitar transmissão",
                "O rádio vai TRANSMITIR automaticamente nos slots escolhidos.\n\n"
                "Confirme: relógio do PC sincronizado, antena ou carga conectada, nível do USB MOD ajustado "
                "(ALC sem acionar) e frequência livre.\n\nHabilitar TX?")
            if ok != QtWidgets.QMessageBox.StandardButton.Yes:
                self.chk_fttx.setChecked(False)
                return
        if not (self.state.mode == "USB" and self.state.data_mode):
            self.radio.set_mode("USB", True, self.state.filter)
            self.state.mode, self.state.data_mode = "USB", True
        if not self._tx_guard("DIG"):
            self.chk_fttx.blockSignals(True)
            self.chk_fttx.setChecked(False)
            self.chk_fttx.blockSignals(False)
            return
        self.ft.tx_enabled = True

    def _ft_halt(self) -> None:
        self.ft.halt()
        self.chk_fttx.blockSignals(True)
        self.chk_fttx.setChecked(False)
        self.chk_fttx.blockSignals(False)

    def _on_ft_rx(self, lines: list[RxLine]) -> None:
        my = self.settings.callsign.upper()
        for line in lines:
            d = line.decode
            utc = datetime.fromtimestamp(line.slot_start, timezone.utc).strftime("%H:%M:%S")
            country = ""
            for c in d.callsigns():
                ent = self.cty.lookup(c)
                if ent:
                    country = ent.name
            self.map.add_ft_message(d.text, d.snr, d.freq)
            self.tbl_ft.insertRow(0)
            for c, v in enumerate((utc, str(d.snr), f"{d.dt:+.1f}", str(d.freq), d.text, country)):
                item = QtWidgets.QTableWidgetItem(v)
                if my and my in d.text.split():
                    item.setBackground(QtGui.QColor(120, 40, 40))
                elif d.text.startswith("CQ"):
                    item.setBackground(QtGui.QColor(30, 80, 40))
                self.tbl_ft.setItem(0, c, item)
        while self.tbl_ft.rowCount() > 400:
            self.tbl_ft.removeRow(self.tbl_ft.rowCount() - 1)

    def _ft_reply(self, row: int, _col: int) -> None:
        text = self.tbl_ft.item(row, 4).text()
        snr = int(self.tbl_ft.item(row, 1).text())
        sug = suggest_reply(self.settings.callsign, text, self.settings.grid, snr)
        if not sug:
            self.statusBar().showMessage("Mensagem não é um CQ nem dirigida a você.", 5000)
            return
        call, msg = sug
        self.ed_fttx.setText(msg)
        self.ed_call.setText(call)

    # ---------------------------------------------------------------- digital
    def _fill_digital(self) -> None:
        band = self.plan.band_for(self.state.freq) if self.chk_dig_band.isChecked() else None
        items = self.plan.digital_for_band(band) if self.chk_dig_band.isChecked() else self.plan.digital
        key = (band, len(items))
        if getattr(self, "_dig_key", None) == key:
            return
        self._dig_key = key
        self._dig_items = items
        self.tbl_dig.setRowCount(0)
        for d in items:
            r = self.tbl_dig.rowCount()
            self.tbl_dig.insertRow(r)
            for c, v in enumerate((d["label"], f"{d['freq'] / 1e3:g}", d["type"])):
                self.tbl_dig.setItem(r, c, QtWidgets.QTableWidgetItem(v))

    def _dig_double(self, row: int, _col: int) -> None:
        d = self._dig_items[row]
        if self.radio:
            self.radio.set_freq(d["freq"])
            self.radio.set_mode("USB", True, self.state.filter)
            self.chk_data.setChecked(True)

    # ---------------------------------------------------------------- spots
    def _toggle_cluster(self) -> None:
        if self.cluster:
            self.cluster.stop()
            self.cluster = None
            self.btn_cluster.setText("Conectar cluster")
            return
        if not self.settings.callsign:
            QtWidgets.QMessageBox.information(self, "Cluster", "Informe seu indicativo na aba Local / GPS.")
            return
        self.settings.cluster_host, self.settings.cluster_port = self.ed_host.text(), self.sp_cport.value()
        self.cluster = ClusterClient(self.settings.cluster_host, self.settings.cluster_port, self.settings.callsign,
                                     self.bridge.spot.emit, self.bridge.message.emit)
        self.cluster.start()
        self.btn_cluster.setText("Desconectar cluster")

    def _load_pota(self) -> None:
        import threading

        def work() -> None:
            try:
                self.bridge.pota.emit(fetch_pota())
            except Exception as exc:
                self.bridge.message.emit(f"POTA: {exc}")

        threading.Thread(target=work, daemon=True).start()

    def _on_spot(self, spot: Spot) -> None:
        self._add_spot(spot)

    def _on_pota(self, spots: list[Spot]) -> None:
        self.spots = [s for s in self.spots if s.source != "POTA"]
        self.tbl_spots.setRowCount(0)
        for s in self.spots:
            self._add_spot(s, store=False)
        for s in spots[:150]:
            self._add_spot(s)

    def _add_spot(self, spot: Spot, store: bool = True) -> None:
        if store:
            self.spots.insert(0, spot)
            self.spots = self.spots[:300]
        self.map.add_spot(spot.call, spot.freq, spot.info, spot.lat, spot.lon)
        ent = self.cty.lookup(spot.call)
        country, db = (ent.name, "") if ent else ("?", "")
        if ent and (self.settings.lat or self.settings.lon):
            d, b = geo.distance_bearing(self.settings.lat, self.settings.lon, ent.lat, ent.lon)
            db = f"{d:.0f} km / {b:.0f}°"
        self.tbl_spots.insertRow(0)
        for c, v in enumerate((spot.source, spot.call, f"{spot.freq / 1e3:.1f}", country, db, spot.info, spot.time)):
            self.tbl_spots.setItem(0, c, QtWidgets.QTableWidgetItem(v))
        while self.tbl_spots.rowCount() > 300:
            self.tbl_spots.removeRow(self.tbl_spots.rowCount() - 1)

    def _spot_double(self, row: int, _col: int) -> None:
        call = self.tbl_spots.item(row, 1).text()
        freq = int(float(self.tbl_spots.item(row, 2).text()) * 1000)
        self._tune(freq, auto_mode=True)
        self.ed_call.setText(call)

    # ---------------------------------------------------------------- log
    def _lookup_call(self, text: str) -> None:
        ent = self.cty.lookup(text)
        if not ent:
            self.lbl_dxcc.setText("")
            return
        msg = f"{ent.name} · {ent.continent} · CQ {ent.cq} · ITU {ent.itu}"
        if self.settings.lat or self.settings.lon:
            d, b = geo.distance_bearing(self.settings.lat, self.settings.lon, ent.lat, ent.lon)
            msg += f" · {d:.0f} km · azimute {b:.0f}°"
        n = self.log.worked(text)
        if n:
            msg += f" · já contatado {n}x"
        self.lbl_dxcc.setText(msg)

    def _add_qso(self) -> None:
        call = self.ed_call.text().strip().upper()
        if not call:
            return
        ent = self.cty.lookup(call)
        mode = "CW" if self.state.mode in ("CW", "CW-R") else self.state.mode
        dig = self.plan.digital_at(self.state.freq)
        if dig and self.state.data_mode:
            mode = dig["type"] if dig["type"] in ("FT8", "FT4", "JS8", "WSPR") else "DIGI"
        self.log.add(Qso(call, self.state.freq, mode, self.ed_rs.text(), self.ed_rr.text(), self.ed_name.text(),
                         self.ed_qgrid.text(), ent.name if ent else "", self.ed_cmt.text(), ref=self.ed_ref.text(),
                         my_ref=self.ed_myref.text()))
        for e in (self.ed_call, self.ed_name, self.ed_qgrid, self.ed_cmt, self.ed_ref):
            e.clear()
        self._fill_log()

    def _fill_log(self) -> None:
        qsos = self.log.all(500)
        self.tbl_log.setRowCount(len(qsos))
        for r, q in enumerate(qsos):
            vals = (q.when, q.call, f"{q.freq / 1e3:.1f}", q.mode, q.rst_sent, q.rst_rcvd, q.country, q.name, q.grid,
                    q.ref, q.my_ref)
            for c, v in enumerate(vals):
                self.tbl_log.setItem(r, c, QtWidgets.QTableWidgetItem(v))
        self._update_activation()

    def _export_adif(self, only_activation: bool = False) -> None:
        my_ref = self.ed_myref.text().strip().upper()
        if only_activation and not my_ref:
            QtWidgets.QMessageBox.information(self, "ADIF", "Informe a sua referência (parque ou cume) para exportar a ativação.")
            return
        name = (my_ref or "log").replace("/", "_") + ".adi"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Exportar ADIF", name, "ADIF (*.adi)")
        if path:
            n = self.log.export_adif(Path(path), self.plan.band_for, my_ref if only_activation else "", self.settings.callsign)
            self.statusBar().showMessage(f"{n} QSOs exportados.", 6000)

    def _myref_changed(self, text: str) -> None:
        self.settings.my_ref = text.strip().upper()
        self._update_activation()

    def _update_activation(self) -> None:
        ref = self.settings.my_ref
        if not ref:
            self.lbl_act.setText("")
            return
        n = self.log.activation_count(ref)
        kind = ref_kind(ref)
        extra = ""
        if kind == "POTA":
            extra = " · ativação válida" if n >= 10 else f" · faltam {10 - n} para validar (POTA)"
        self.lbl_act.setText(f"Hoje (UTC): {n} QSOs{extra}")

    def _pota_chosen(self, spot) -> None:
        kind = spot.mode.upper()
        if kind == "SSB":
            mode, data = ("LSB" if spot.freq < 10_000_000 else "USB"), False
        elif kind == "CW":
            mode, data = "CW", False
        elif kind in ("FT8", "FT4"):
            mode, data = "USB", True
        elif kind in ("AM", "FM"):
            mode, data = kind, False
        else:
            mode, data = self.plan.suggest_mode(spot.freq)
        if self.radio:
            self.radio.set_freq(spot.freq)
            self.radio.set_mode(mode, data, self.state.filter)
        else:
            self.bridge.message.emit("Conecte ao rádio para sintonizar; indicativo e parque foram copiados para o log.")
        self.ed_call.setText(spot.call)
        self.ed_ref.setText(spot.info.split(" ", 1)[0])

    def _pota_to_map(self, spots) -> None:
        for s in spots[:150]:
            self.map.add_spot(s.call, s.freq, s.info, s.lat, s.lon)

    # ---------------------------------------------------------------- local
    def _grid_to_ll(self) -> None:
        try:
            lat, lon = geo.grid_to_latlon(self.ed_mygrid.text().strip())
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Grid", str(exc))
            return
        self.sp_lat.setValue(lat)
        self.sp_lon.setValue(lon)

    def _ll_to_grid(self) -> None:
        self.ed_mygrid.setText(geo.latlon_to_grid(self.sp_lat.value(), self.sp_lon.value()))

    def _save_location(self) -> None:
        s = self.settings
        s.callsign = self.ed_mycall.text().strip().upper()
        s.grid = self.ed_mygrid.text().strip()
        s.lat, s.lon = self.sp_lat.value(), self.sp_lon.value()
        s.band_plan = self.cb_plan.currentData()
        s.classes_by_plan[self._preview_plan()] = self.cb_class.currentData() or ""
        s.save()
        self._apply_plan()
        self.map.set_home(s.lat, s.lon, s.callsign)
        self.swl.set_home(s.lat, s.lon)
        self.lbl_grid.setText(f"{s.callsign}  {s.grid}")
        self.statusBar().showMessage("Local salvo.", 4000)

    def _toggle_gps(self) -> None:
        if self.gps:
            self.gps.stop()
            self.gps = None
            self.btn_gps.setText("Iniciar GPS")
            return
        port = self.cb_gps.currentText().strip()
        if not port:
            return

        def on_fix(lat: float, lon: float) -> None:
            self.bridge.message.emit(f"GPS: {lat:.5f}, {lon:.5f}")
            QtCore.QMetaObject.invokeMethod(self, "_apply_fix", QtCore.Qt.ConnectionType.QueuedConnection,
                                            QtCore.Q_ARG(float, lat), QtCore.Q_ARG(float, lon))

        self.gps = geo.GpsReader(port, self.settings.gps_baud, on_fix)
        self.gps.start()
        self.btn_gps.setText("Parar GPS")

    @QtCore.Slot(float, float)
    def _apply_fix(self, lat: float, lon: float) -> None:
        self.sp_lat.setValue(lat)
        self.sp_lon.setValue(lon)
        self.ed_mygrid.setText(geo.latlon_to_grid(lat, lon))
        self.map.set_home(lat, lon, self.settings.callsign)
        self.swl.set_home(lat, lon)
        self.lbl_gps.setText(f"Posição do GPS: {lat:.5f}, {lon:.5f} ({self.ed_mygrid.text()})")

    # ---------------------------------------------------------------- misc
    def _tick(self) -> None:
        self.lbl_utc.setText(datetime.now(timezone.utc).strftime("UTC %H:%M:%S"))
        self.lbl_slot.setText(f"slot {self.ft.seconds_into_slot():4.1f}/{self.ft.slot_len:.1f} s"
                              + ("  ● TX" if self.state.ptt else ""))
        s = self.settings
        self.lbl_grid.setText(f"{s.callsign or 'sem indicativo'}  {s.grid}")

    def closeEvent(self, e: QtGui.QCloseEvent) -> None:
        self._disconnect()
        if self.cluster:
            self.cluster.stop()
        if self.gps:
            self.gps.stop()
        if self.rigctl:
            self.rigctl.stop()
        self.settings.save()
        super().closeEvent(e)
