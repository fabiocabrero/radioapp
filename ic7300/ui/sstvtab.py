"""Aba SSTV: recepção de imagens (Martin M1/M2, Scottie S1/S2) e transmissão de imagem com legenda."""
from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from ..dsp import sstv
from ..ftengine import Decimator4
from ..radio import RadioState
from ..settings import Settings, app_dir
from .. import audio as audio_mod

CALLING = [("14.230 MHz (20 m, USB)", 14_230_000, "USB"), ("21.340 MHz (15 m, USB)", 21_340_000, "USB"),
           ("28.680 MHz (10 m, USB)", 28_680_000, "USB"), ("7.171 MHz (40 m, LSB)", 7_171_000, "LSB"),
           ("3.845 MHz (80 m, LSB)", 3_845_000, "LSB")]


def to_qimage(arr: np.ndarray) -> QtGui.QImage:
    h, w, _ = arr.shape
    arr = np.ascontiguousarray(arr)
    return QtGui.QImage(arr.data, w, h, 3 * w, QtGui.QImage.Format.Format_RGB888).copy()


def to_array(img: QtGui.QImage) -> np.ndarray:
    img = img.convertToFormat(QtGui.QImage.Format.Format_RGB888)
    h, w, bpl = img.height(), img.width(), img.bytesPerLine()
    buf = np.frombuffer(img.constBits(), dtype=np.uint8, count=h * bpl).reshape(h, bpl)
    return buf[:, :3 * w].reshape(h, w, 3).copy()


class SstvTab(QtWidgets.QWidget):
    tune_requested = QtCore.Signal(int, str)  # Hz, banda lateral (com DATA)
    _started = QtCore.Signal(str)
    _line = QtCore.Signal(int, object)
    _done = QtCore.Signal(str, object)
    _status = QtCore.Signal(str)

    def __init__(self, settings: Settings, get_state: Callable[[], RadioState], set_ptt: Callable[[bool], None],
                 play: Callable[[np.ndarray], None]) -> None:
        super().__init__()
        self.settings, self.get_state, self.set_ptt, self.play = settings, get_state, set_ptt, play
        self.decimator = Decimator4()
        self.decoder = sstv.SstvDecoder(on_start=lambda m: self._started.emit(m.name),
                                        on_line=lambda y, row: self._line.emit(y, row),
                                        on_image=lambda m, img: self._done.emit(m.name, img))
        self._rx_image: np.ndarray | None = None
        self._tx_image: np.ndarray | None = None
        self._tx_busy = threading.Event()
        self._confirmed = False
        self._src_image: QtGui.QImage | None = None
        self.gallery = app_dir() / "sstv"
        self.gallery.mkdir(exist_ok=True)

        lay = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QVBoxLayout()
        lay.addLayout(left, 3)
        bar = QtWidgets.QHBoxLayout()
        self.chk_rx = QtWidgets.QCheckBox("Ouvir e decodificar")
        self.cb_freq = QtWidgets.QComboBox()
        for label, hz, sb in CALLING:
            self.cb_freq.addItem(label, (hz, sb))
        btn_tune = QtWidgets.QPushButton("Sintonizar")
        self.btn_save = QtWidgets.QPushButton("Salvar imagem…")
        for w in (self.chk_rx, self.cb_freq, btn_tune, self.btn_save):
            bar.addWidget(w)
        bar.addStretch()
        left.addLayout(bar)
        self.view = QtWidgets.QLabel("Aguardando um sinal SSTV (o início é detectado pelo código VIS).")
        self.view.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.view.setMinimumSize(400, 320)
        self.view.setStyleSheet("background:#0b0f14; border:1px solid #2c3541")
        left.addWidget(self.view, 1)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setFormat("%v / %m linhas")
        left.addWidget(self.progress)
        self.lbl = QtWidgets.QLabel("")
        self.lbl.setWordWrap(True)
        left.addWidget(self.lbl)

        right = QtWidgets.QVBoxLayout()
        lay.addLayout(right, 2)
        right.addWidget(QtWidgets.QLabel("Imagens recebidas (duplo clique abre)"))
        self.lst = QtWidgets.QListWidget()
        right.addWidget(self.lst, 1)
        box = QtWidgets.QGroupBox("Transmitir")
        tx = QtWidgets.QVBoxLayout(box)
        row = QtWidgets.QHBoxLayout()
        self.cb_mode = QtWidgets.QComboBox()
        for name, m in sstv.MODES.items():
            self.cb_mode.addItem(f"{name} ({m.line_ms * m.height / 1000:.0f} s)", name)
        btn_img = QtWidgets.QPushButton("Escolher imagem…")
        row.addWidget(self.cb_mode)
        row.addWidget(btn_img)
        tx.addLayout(row)
        self.ed_text = QtWidgets.QLineEdit("CQ CQ SSTV {call}")
        self.chk_text = QtWidgets.QCheckBox("Escrever o texto sobre a imagem")
        self.chk_text.setChecked(True)
        tx.addWidget(self.ed_text)
        tx.addWidget(self.chk_text)
        self.preview = QtWidgets.QLabel("Escolha uma imagem")
        self.preview.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(160)
        self.preview.setStyleSheet("background:#0b0f14; border:1px solid #2c3541")
        tx.addWidget(self.preview)
        row2 = QtWidgets.QHBoxLayout()
        self.sl_level = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.sl_level.setRange(5, 100)
        self.sl_level.setValue(30)
        self.btn_send = QtWidgets.QPushButton("Transmitir")
        self.btn_stop = QtWidgets.QPushButton("Parar")
        self.btn_stop.setStyleSheet("background:#8e2420")
        for w in (QtWidgets.QLabel("Nível"), self.sl_level, self.btn_send, self.btn_stop):
            row2.addWidget(w)
        row2.setStretch(1, 1)
        tx.addLayout(row2)
        right.addWidget(box)
        note = QtWidgets.QLabel("Rádio em USB/LSB com DATA, sem compressor. As imagens recebidas ficam salvas em " + str(self.gallery))
        note.setWordWrap(True)
        note.setStyleSheet("color:#8a97a8; font-size:8pt")
        right.addWidget(note)

        self._started.connect(self._on_start)
        self._line.connect(self._on_line)
        self._done.connect(self._on_done)
        self._status.connect(self.lbl.setText)
        btn_tune.clicked.connect(lambda: self.tune_requested.emit(*self.cb_freq.currentData()))
        self.btn_save.clicked.connect(self._save)
        self.lst.itemDoubleClicked.connect(self._open_item)
        btn_img.clicked.connect(self._choose)
        self.ed_text.textChanged.connect(self._render_tx)
        self.chk_text.toggled.connect(self._render_tx)
        self.cb_mode.currentIndexChanged.connect(self._render_tx)
        self.btn_send.clicked.connect(self._send)
        self.btn_stop.clicked.connect(self._stop)
        self._load_gallery()

    # ---------------------------------------------------------------- recepção
    def feed(self, samples48: np.ndarray) -> None:  # thread de áudio
        if self.chk_rx.isChecked():
            self.decoder.feed(self.decimator.process(samples48))

    def _on_start(self, name: str) -> None:
        mode = sstv.MODES[name]
        self._rx_image = np.zeros((mode.height, mode.width, 3), dtype=np.uint8)
        self.progress.setRange(0, mode.height)
        self.progress.setValue(0)
        self._status.emit(f"Recebendo {name}…")

    def _on_line(self, y: int, row: np.ndarray) -> None:
        if self._rx_image is None:
            return
        self._rx_image[y] = row
        self.progress.setValue(y + 1)
        if y % 4 == 0 or y == len(self._rx_image) - 1:
            self._show(self._rx_image)

    def _on_done(self, name: str, image: np.ndarray) -> None:
        self._rx_image = image
        self._show(image)
        path = self.gallery / f"{datetime.now():%Y%m%d_%H%M%S}_{name.replace(' ', '')}.png"
        to_qimage(image).save(str(path))
        self.lst.insertItem(0, path.name)
        self.lst.item(0).setData(QtCore.Qt.ItemDataRole.UserRole, str(path))
        self._status.emit(f"{name}: imagem completa, salva em {path.name}")

    def _show(self, arr: np.ndarray) -> None:
        pix = QtGui.QPixmap.fromImage(to_qimage(arr))
        self.view.setPixmap(pix.scaled(self.view.size(), QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                       QtCore.Qt.TransformationMode.SmoothTransformation))

    def _load_gallery(self) -> None:
        for p in sorted(self.gallery.glob("*.png"), reverse=True)[:100]:
            item = QtWidgets.QListWidgetItem(p.name)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, str(p))
            self.lst.addItem(item)

    def _open_item(self, item: QtWidgets.QListWidgetItem) -> None:
        img = QtGui.QImage(item.data(QtCore.Qt.ItemDataRole.UserRole))
        if not img.isNull():
            self._rx_image = to_array(img)
            self._show(self._rx_image)

    def _save(self) -> None:
        if self._rx_image is None:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Salvar imagem", "sstv.png", "PNG (*.png)")
        if path:
            to_qimage(self._rx_image).save(path)

    # ---------------------------------------------------------------- transmissão
    def _choose(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Imagem para transmitir", "", "Imagens (*.png *.jpg *.jpeg *.bmp)")
        if path:
            img = QtGui.QImage(path)
            if img.isNull():
                QtWidgets.QMessageBox.warning(self, "SSTV", "Não foi possível abrir a imagem.")
                return
            self._src_image = img
            self._render_tx()

    def _render_tx(self) -> None:
        if self._src_image is None:
            return
        mode = sstv.MODES[self.cb_mode.currentData()]
        canvas = QtGui.QImage(mode.width, mode.height, QtGui.QImage.Format.Format_RGB888)
        canvas.fill(QtGui.QColor("black"))
        scaled = self._src_image.scaled(mode.width, mode.height, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                        QtCore.Qt.TransformationMode.SmoothTransformation)
        p = QtGui.QPainter(canvas)
        p.drawImage((mode.width - scaled.width()) // 2, (mode.height - scaled.height()) // 2, scaled)
        text = self.ed_text.text().replace("{call}", self.settings.callsign or "").strip()
        if self.chk_text.isChecked() and text:
            font = QtGui.QFont("Arial", 20, QtGui.QFont.Weight.Bold)
            p.setFont(font)
            bar = QtCore.QRect(0, mode.height - 38, mode.width, 38)
            p.fillRect(bar, QtGui.QColor(0, 0, 0, 170))
            p.setPen(QtGui.QColor("white"))
            p.drawText(bar, QtCore.Qt.AlignmentFlag.AlignCenter, text)
        p.end()
        self._tx_image = to_array(canvas)
        self.preview.setPixmap(QtGui.QPixmap.fromImage(canvas).scaledToHeight(150, QtCore.Qt.TransformationMode.SmoothTransformation))

    def _send(self) -> None:
        st = self.get_state()
        if self._tx_image is None or self._tx_busy.is_set():
            self._status.emit("Escolha uma imagem antes de transmitir.")
            return
        if not st.connected:
            self._status.emit("Conecte ao rádio (ou ao simulador) antes de transmitir.")
            return
        if not self.settings.callsign:
            self._status.emit("Informe seu indicativo na aba Local / GPS antes de transmitir.")
            return
        mode = sstv.MODES[self.cb_mode.currentData()]
        if not self._confirmed and not self.settings.simulator:
            seconds = mode.line_ms * mode.height / 1000 + 4
            ok = QtWidgets.QMessageBox.question(self, "Transmitir SSTV", f"O rádio vai TRANSMITIR por cerca de {seconds:.0f} s.\n\n"
                                                "Confirme: antena ou carga conectada, USB MOD ajustado (ALC sem acionar) e "
                                                "frequência livre.\n\nTransmitir?")
            if ok != QtWidgets.QMessageBox.StandardButton.Yes:
                return
            self._confirmed = True
        audio = sstv.encode(self._tx_image, mode, fs=audio_mod.FS, amp=self.sl_level.value() / 100)
        threading.Thread(target=self._transmit, args=(audio, mode.name), daemon=True).start()

    def _transmit(self, audio: np.ndarray, name: str) -> None:
        self._tx_busy.set()
        try:
            self._status.emit(f"Transmitindo {name} ({len(audio) / audio_mod.FS:.0f} s)…")
            self.set_ptt(True)
            time.sleep(0.2)
            self.play(audio)
            time.sleep(0.1)
            self._status.emit("Transmissão concluída.")
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
