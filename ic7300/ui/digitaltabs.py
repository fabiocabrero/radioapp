"""Abas de modos digitais adicionais: RTTY (nativo) e FST4/Q65/JT65/JT9/WSPR (motor do WSJT-X)."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Callable

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from .. import audio as audio_mod
from .. import wsjtx_engine as wx
from ..dsp import rtty
from ..dxcc import Cty
from ..radio import RadioState
from ..settings import Settings

RTTY_MACROS = ["CQ CQ CQ DE {call} {call} {call} PSE K", "{their} DE {call} UR RST 599 599 NAME {name} {name} BTU {their} DE {call} K",
               "{their} DE {call} TNX FER QSO 73 73 SK", "{their} DE {call} PSE AGN K"]


def _calls(text: str) -> list[str]:
    words = [w.strip("<>") for w in text.split()]
    return [w for w in words if any(c.isdigit() for c in w) and any(c.isalpha() for c in w) and len(w) >= 3
            and not (len(w) == 4 and w[:2].isalpha() and w[2:].isdigit())]


class RttyTab(QtWidgets.QWidget):
    _rx = QtCore.Signal(str)
    _status = QtCore.Signal(str)

    def __init__(self, settings: Settings, get_state: Callable[[], RadioState], set_ptt: Callable[[bool], None],
                 play: Callable[[np.ndarray], None], get_their: Callable[[], str]) -> None:
        super().__init__()
        self.settings, self.get_state, self.set_ptt, self.play, self.get_their = settings, get_state, set_ptt, play, get_their
        self.decoder = rtty.RttyDecoder()
        self._tx_busy = threading.Event()
        self._confirmed = False
        self.guard: Callable[[str], bool] = lambda category: True

        lay = QtWidgets.QVBoxLayout(self)
        bar = QtWidgets.QHBoxLayout()
        self.chk_rx = QtWidgets.QCheckBox("Ouvir e decodificar")
        self.cb_baud = QtWidgets.QComboBox()
        for b in ("45.45", "50", "75", "100"):
            self.cb_baud.addItem(b + " baud", float(b))
        self.sp_mark = QtWidgets.QSpinBox()
        self.sp_mark.setRange(300, 3500)
        self.sp_mark.setValue(2125)
        self.sp_mark.setSuffix(" Hz (marca)")
        self.sp_shift = QtWidgets.QSpinBox()
        self.sp_shift.setRange(50, 1000)
        self.sp_shift.setValue(170)
        self.sp_shift.setSuffix(" Hz (shift)")
        self.chk_rev = QtWidgets.QCheckBox("Invertido (REV)")
        self.chk_uos = QtWidgets.QCheckBox("UOS")
        self.chk_uos.setChecked(True)
        self.chk_uos.setToolTip("Unshift on space: depois de um espaço volta para letras")
        self.lbl_level = QtWidgets.QLabel("")
        for w in (self.chk_rx, self.cb_baud, self.sp_mark, self.sp_shift, self.chk_rev, self.chk_uos):
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(self.lbl_level)
        lay.addLayout(bar)
        self.txt = QtWidgets.QPlainTextEdit(readOnly=True)
        self.txt.setStyleSheet("font: 13pt 'Consolas'")
        lay.addWidget(self.txt, 1)
        tx = QtWidgets.QHBoxLayout()
        self.ed_tx = QtWidgets.QLineEdit()
        self.ed_tx.setPlaceholderText("Texto para transmitir em RTTY (AFSK)")
        self.sl_level = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.sl_level.setRange(5, 100)
        self.sl_level.setValue(30)
        self.sl_level.setMaximumWidth(110)
        self.btn_send = QtWidgets.QPushButton("Transmitir")
        self.btn_stop = QtWidgets.QPushButton("Parar")
        self.btn_stop.setStyleSheet("background:#8e2420")
        btn_clear = QtWidgets.QPushButton("Limpar")
        tx.addWidget(self.ed_tx, 1)
        for w in (QtWidgets.QLabel("Nível"), self.sl_level, self.btn_send, self.btn_stop, btn_clear):
            tx.addWidget(w)
        lay.addLayout(tx)
        macros = QtWidgets.QHBoxLayout()
        for i, text in enumerate(RTTY_MACROS):
            b = QtWidgets.QPushButton(f"F{i + 1}")
            b.setToolTip(text)
            b.clicked.connect(lambda _=False, t=text: self.ed_tx.setText(self._expand(t)))
            macros.addWidget(b)
        lay.addLayout(macros)
        self.lbl = QtWidgets.QLabel("Use o rádio em USB com DATA (AFSK), sem filtro estreito, e o tom de marca igual ao do outro operador "
                                    "(padrão 2125 Hz, shift 170 Hz). Os botões F1–F4 só preenchem o texto; você confirma o envio.")
        self.lbl.setWordWrap(True)
        self.lbl.setStyleSheet("color:#8a97a8; font-size:8pt")
        lay.addWidget(self.lbl)

        self._rx.connect(self._append)
        self._status.connect(self.lbl.setText)
        for w in (self.cb_baud,):
            w.currentIndexChanged.connect(self._apply)
        for w in (self.sp_mark, self.sp_shift):
            w.valueChanged.connect(self._apply)
        for w in (self.chk_rev, self.chk_uos):
            w.toggled.connect(self._apply)
        self.btn_send.clicked.connect(self._send)
        self.ed_tx.returnPressed.connect(self._send)
        self.btn_stop.clicked.connect(self._stop)
        btn_clear.clicked.connect(self.txt.clear)
        self.timer = QtCore.QTimer(self, interval=500, timeout=lambda: self.lbl_level.setText(
            f"nível {self.decoder.level * 100:.0f}" + ("" if self.decoder.level > self.decoder.squelch else " (sem sinal)")))
        self.timer.start()

    def _expand(self, text: str) -> str:
        return text.replace("{call}", self.settings.callsign or "NOCALL").replace("{their}", self.get_their() or "").replace(
            "{name}", "")

    def _apply(self) -> None:
        self.decoder.configure(self.sp_mark.value(), self.sp_shift.value(), self.chk_rev.isChecked(), self.cb_baud.currentData())
        self.decoder.uos = self.chk_uos.isChecked()

    def feed(self, samples48: np.ndarray) -> None:  # thread de áudio
        if self.chk_rx.isChecked():
            text = self.decoder.process(samples48)
            if text:
                self._rx.emit(text)

    def _append(self, text: str) -> None:
        self.txt.moveCursor(QtGui.QTextCursor.MoveOperation.End)
        self.txt.insertPlainText(text.replace("\r", ""))
        self.txt.moveCursor(QtGui.QTextCursor.MoveOperation.End)

    def _send(self) -> None:
        text = self.ed_tx.text().strip()
        st = self.get_state()
        if not text or self._tx_busy.is_set():
            return
        if not st.connected:
            self._status.emit("Conecte ao rádio (ou ao simulador) antes de transmitir.")
            return
        if not self.settings.callsign:
            self._status.emit("Informe seu indicativo na aba Local / GPS antes de transmitir.")
            return
        if not self.guard("DIG"):
            return
        if not self._confirmed and not self.settings.simulator:
            ok = QtWidgets.QMessageBox.question(self, "Transmitir RTTY", "O rádio vai TRANSMITIR agora.\n\nConfirme: antena ou carga "
                                                "conectada, USB MOD ajustado (ALC sem acionar) e frequência livre.\n\nTransmitir?")
            if ok != QtWidgets.QMessageBox.StandardButton.Yes:
                return
            self._confirmed = True
        audio = rtty.encode(text + "\n", self.cb_baud.currentData(), self.sp_mark.value(), self.sp_shift.value(),
                            reverse=self.chk_rev.isChecked(), amp=self.sl_level.value() / 100, uos=self.chk_uos.isChecked())
        threading.Thread(target=self._transmit, args=(audio, text), daemon=True).start()

    def _transmit(self, audio: np.ndarray, text: str) -> None:
        self._tx_busy.set()
        try:
            self._rx.emit(f"\n>> {text}\n")
            self.set_ptt(True)
            time.sleep(0.15)
            self.play(audio)
            time.sleep(0.1)
        except Exception as exc:
            self._status.emit(f"Falha no TX: {exc}")
        finally:
            self.set_ptt(False)
            self._tx_busy.clear()

    def _stop(self) -> None:
        try:
            audio_mod.stop_playback()
        except Exception:
            pass
        self.set_ptt(False)


class JtTab(QtWidgets.QWidget):
    _rx = QtCore.Signal(object)
    _status = QtCore.Signal(str)

    def __init__(self, settings: Settings, cty: Cty, get_state: Callable[[], RadioState]) -> None:
        super().__init__()
        self.settings, self.cty, self.get_state = settings, cty, get_state
        self.engine = wx.SlotEngine(self._rx.emit, self._status.emit)
        self.engine.bin_dir = wx.find_bin(settings.wsjtx_dir)

        lay = QtWidgets.QVBoxLayout(self)
        bar = QtWidgets.QHBoxLayout()
        self.chk = QtWidgets.QCheckBox("Ouvir e decodificar")
        self.cb_mode = QtWidgets.QComboBox()
        for m in wx.MODES:
            self.cb_mode.addItem(m + ("" if wx.VALIDATED[m] else " *"), m)
        self.cb_period = QtWidgets.QComboBox()
        self.sp_freq = QtWidgets.QSpinBox()
        self.sp_freq.setRange(200, 3000)
        self.sp_freq.setValue(1500)
        self.sp_freq.setSuffix(" Hz (centro)")
        self.sp_tol = QtWidgets.QSpinBox()
        self.sp_tol.setRange(10, 1500)
        self.sp_tol.setValue(100)
        self.sp_tol.setPrefix("± ")
        self.sp_tol.setSuffix(" Hz")
        self.cb_sub = QtWidgets.QComboBox()
        self.cb_sub.addItems(["Q65-A", "Q65-B", "Q65-C", "Q65-D", "Q65-E"])
        self.lbl_slot = QtWidgets.QLabel("")
        self.lbl_slot.setStyleSheet("font: 600 12pt 'Consolas'")
        for w in (self.chk, self.cb_mode, self.cb_period, self.sp_freq, self.sp_tol, self.cb_sub):
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(self.lbl_slot)
        lay.addLayout(bar)
        self.table = QtWidgets.QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["UTC", "Modo", "SNR", "DT", "Freq", "Mensagem", "Detalhe"])
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(5, 320)
        lay.addWidget(self.table, 1)
        path_row = QtWidgets.QHBoxLayout()
        self.lbl_bin = QtWidgets.QLabel("")
        btn_bin = QtWidgets.QPushButton("Escolher pasta do WSJT-X…")
        path_row.addWidget(self.lbl_bin, 1)
        path_row.addWidget(btn_bin)
        lay.addLayout(path_row)
        self.lbl = QtWidgets.QLabel("")
        self.lbl.setWordWrap(True)
        lay.addWidget(self.lbl)
        note = QtWidgets.QLabel("Só recepção: usa o jt9.exe e o wsprd.exe do WSJT-X instalado no seu PC (não são distribuídos com este app). "
                                "FST4 e Q65 foram validados com os simuladores do WSJT-X. * JT65, JT9 e WSPR usam o mesmo caminho, mas "
                                "ainda não foram validados com sinais reais. No WSPR a frequência exibida é a absoluta (dial do rádio + tom).")
        note.setWordWrap(True)
        note.setStyleSheet("color:#8a97a8; font-size:8pt")
        lay.addWidget(note)

        self._fill_periods()
        self._show_bin()
        self.chk.toggled.connect(self._apply)
        self.cb_mode.currentIndexChanged.connect(self._mode_changed)
        self.cb_period.currentIndexChanged.connect(self._apply)
        self.sp_freq.valueChanged.connect(self._apply)
        self.sp_tol.valueChanged.connect(self._apply)
        self.cb_sub.currentIndexChanged.connect(self._apply)
        btn_bin.clicked.connect(self._choose_bin)
        self._rx.connect(self._on_rx)
        self._status.connect(self.lbl.setText)
        self.timer = QtCore.QTimer(self, interval=500, timeout=self._tick)
        self.timer.start()

    def _show_bin(self) -> None:
        b = self.engine.bin_dir
        self.lbl_bin.setText(f"WSJT-X: {b}" if b else "WSJT-X não encontrado: instale-o ou escolha a pasta que contém jt9.exe.")

    def _choose_bin(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Pasta do WSJT-X (com jt9.exe)")
        if folder:
            found = wx.find_bin(folder)
            if not found:
                QtWidgets.QMessageBox.warning(self, "WSJT-X", "jt9.exe não está nessa pasta.")
                return
            self.settings.wsjtx_dir = str(found)
            self.engine.bin_dir = found
            self._show_bin()

    def _fill_periods(self) -> None:
        mode = self.cb_mode.currentData()
        _, periods, default = wx.MODES[mode]
        self.cb_period.blockSignals(True)
        self.cb_period.clear()
        for p in periods:
            self.cb_period.addItem(f"{p} s", p)
        self.cb_period.setCurrentIndex(periods.index(default))
        self.cb_period.blockSignals(False)
        self.cb_sub.setVisible(mode == "Q65")

    def _mode_changed(self) -> None:
        self._fill_periods()
        self.table.setRowCount(0)
        self._apply()

    def _apply(self) -> None:
        e = self.engine
        e.set_mode(self.cb_mode.currentData(), self.cb_period.currentData() or 60)
        e.rx_freq, e.tolerance = self.sp_freq.value(), self.sp_tol.value()
        e.q65_submode = self.cb_sub.currentText()[-1]
        e.enabled = self.chk.isChecked()

    def _tick(self) -> None:
        self.engine.dial_mhz = self.get_state().freq / 1e6
        if self.engine.enabled:
            self.lbl_slot.setText(f"slot {self.engine.seconds_into_slot():5.1f}/{self.engine.period} s")
        else:
            self.lbl_slot.setText("")

    def feed(self, samples48: np.ndarray) -> None:  # thread de áudio
        self.engine.feed(samples48)

    def _on_rx(self, found: list) -> None:
        for d in found:
            utc = datetime.fromtimestamp(d.start, timezone.utc).strftime("%H:%M")
            freq = f"{d.freq / 1e6:.6f} MHz" if d.mode == "WSPR" else str(d.freq)
            country = next((e.name for c in _calls(d.text) if (e := self.cty.lookup(c))), "")
            self.table.insertRow(0)
            for c, v in enumerate((utc, d.mode, str(d.snr), f"{d.dt:+.1f}", freq, d.text, (d.extra + " " + country).strip())):
                self.table.setItem(0, c, QtWidgets.QTableWidgetItem(v))
        while self.table.rowCount() > 400:
            self.table.removeRow(self.table.rowCount() - 1)
