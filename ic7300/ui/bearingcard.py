"""Card "Direção da antena": azimute para o contato (caminho curto e longo) num mostrador, para apontar antenas direcionais."""
from __future__ import annotations

import math
from typing import Callable, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from .. import geo, rotator


class Dial(QtWidgets.QWidget):
    """Rosa dos ventos com a seta do caminho curto (cheia) e do longo (tracejada)."""

    def __init__(self) -> None:
        super().__init__()
        self.short: Optional[float] = None
        self.long: Optional[float] = None
        self.rotor: Optional[float] = None
        self.setMinimumSize(130, 130)

    def set_angles(self, short: Optional[float], long: Optional[float]) -> None:
        self.short, self.long = short, long
        self.update()

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = min(w, h) / 2 - 16
        c = QtCore.QPointF(w / 2, h / 2)
        pal = self.palette()
        fg = pal.color(QtGui.QPalette.ColorRole.WindowText)
        p.setPen(QtGui.QPen(fg, 1.2))
        p.drawEllipse(c, r, r)
        for deg in range(0, 360, 30):
            a = math.radians(deg)
            inner = r - (9 if deg % 90 == 0 else 5)
            p.drawLine(QtCore.QPointF(c.x() + inner * math.sin(a), c.y() - inner * math.cos(a)),
                       QtCore.QPointF(c.x() + r * math.sin(a), c.y() - r * math.cos(a)))
        for label, deg in (("N", 0), ("L", 90), ("S", 180), ("O", 270)):
            a = math.radians(deg)
            p.drawText(QtCore.QRectF(c.x() + (r + 9) * math.sin(a) - 8, c.y() - (r + 9) * math.cos(a) - 8, 16, 16),
                       QtCore.Qt.AlignmentFlag.AlignCenter, label)
        for az, color, dashed in ((self.long, "#8a8f98", True), (self.short, "#e0562a", False), (self.rotor, "#2e8bd8", False)):
            if az is None:
                continue
            a = math.radians(az)
            pen = QtGui.QPen(QtGui.QColor(color), 3 if not dashed else 2)
            if dashed:
                pen.setStyle(QtCore.Qt.PenStyle.DashLine)
            p.setPen(pen)
            tip = QtCore.QPointF(c.x() + (r - 4) * math.sin(a), c.y() - (r - 4) * math.cos(a))
            p.drawLine(c, tip)
            if not dashed:
                p.setBrush(QtGui.QColor(color))
                for side in (-0.28, 0.28):
                    b = a + math.pi + side
                    p.drawLine(tip, QtCore.QPointF(tip.x() + 11 * math.sin(b), tip.y() - 11 * math.cos(b)))
        p.end()


class BearingCard(QtWidgets.QGroupBox):
    """Mostra para onde apontar. Opcionalmente gira o rotor (rotctld do Hamlib)."""

    message = QtCore.Signal(str)
    _checked = QtCore.Signal(object, str)

    def __init__(self, get_home: Callable[[], Optional[tuple[float, float]]], rotor_text: str = "") -> None:
        super().__init__("Direção da antena")
        self.get_home = get_home
        self._target: Optional[tuple[float, float]] = None
        self._az: Optional[float] = None
        lay = QtWidgets.QHBoxLayout(self)
        self.dial = Dial()
        lay.addWidget(self.dial)
        col = QtWidgets.QVBoxLayout()
        self.lbl_who = QtWidgets.QLabel("Escolha um contato")
        self.lbl_who.setStyleSheet("font-weight:600")
        self.lbl_short = QtWidgets.QLabel("")
        self.lbl_short.setStyleSheet("font: 700 18pt 'Consolas'; color:#e0562a")
        self.lbl_long = QtWidgets.QLabel("")
        self.lbl_note = QtWidgets.QLabel("")
        self.lbl_note.setWordWrap(True)
        for w in (self.lbl_who, self.lbl_short, self.lbl_long, self.lbl_note):
            col.addWidget(w)
        row = QtWidgets.QHBoxLayout()
        self.ed_rotor = QtWidgets.QLineEdit(rotor_text)
        self.ed_rotor.setPlaceholderText("rotor: host:porta (rotctld)")
        self.ed_rotor.setMaximumWidth(150)
        self.btn_turn = QtWidgets.QPushButton("Girar antena")
        self.btn_turn.clicked.connect(self._turn)
        row.addWidget(self.ed_rotor)
        row.addWidget(self.btn_turn)
        self.btn_check = QtWidgets.QPushButton("Verificar rotor")
        self.btn_check.setToolTip("Testa a conexão com o rotctld e mostra a posição atual da antena (seta azul)")
        self.btn_check.clicked.connect(self._check)
        row.addWidget(self.btn_check)
        row.addStretch()
        col.addLayout(row)
        self.lbl_rotor = QtWidgets.QLabel("")
        self.lbl_rotor.setWordWrap(True)
        col.addWidget(self.lbl_rotor)
        self._checked.connect(self._show_check)
        col.addStretch()
        lay.addLayout(col, 1)
        self.setMinimumHeight(150)

    @property
    def rotor_text(self) -> str:
        return self.ed_rotor.text().strip()

    def set_target(self, label: str, lat: Optional[float], lon: Optional[float], approx: str = "") -> None:
        home = self.get_home()
        if lat is None or lon is None or not home:
            self._target, self._az = None, None
            self.dial.set_angles(None, None)
            self.lbl_who.setText(label or "Escolha um contato")
            self.lbl_short.setText("")
            self.lbl_long.setText("")
            self.lbl_note.setText("" if home else "Informe sua localização (Apps > Local / GPS).")
            return
        info = geo.bearing_info(home[0], home[1], lat, lon)
        self._target, self._az = (lat, lon), info["short_az"]
        self.dial.set_angles(info["short_az"], info["long_az"])
        self.lbl_who.setText(label)
        self.lbl_short.setText(f"{info['short_az']:.0f}°  {geo.compass(info['short_az'])}")
        self.lbl_long.setText(f"{info['short_km']:,.0f} km curto · longo: {info['long_az']:.0f}° {geo.compass(info['long_az'])} "
                              f"({info['long_km']:,.0f} km)".replace(",", " "))
        self.lbl_note.setText(approx)

    def azimuth(self) -> Optional[float]:
        return self._az

    def _check(self) -> None:
        """Verifica o rotor em segundo plano (a conexão pode demorar até o tempo limite)."""
        try:
            client = rotator.RotatorClient.from_text(self.ed_rotor.text())
        except ValueError as exc:
            self._show_check(None, str(exc))
            return
        self.btn_check.setEnabled(False)
        self.lbl_rotor.setStyleSheet("")
        self.lbl_rotor.setText("Verificando...")

        def work() -> None:
            try:
                self._checked.emit(client.check(), "")
            except RuntimeError as exc:
                self._checked.emit(None, str(exc))

        import threading
        threading.Thread(target=work, daemon=True).start()

    def _show_check(self, az, error: str) -> None:
        self.btn_check.setEnabled(True)
        self.dial.rotor = az
        self.dial.update()
        if az is None:
            self.lbl_rotor.setStyleSheet("color:#c0392b")
            self.lbl_rotor.setText(f"Rotor: {error}")
        else:
            self.lbl_rotor.setStyleSheet("color:#3a9a4a")
            self.lbl_rotor.setText(f"Rotor conectado: antena em {az:.0f}° {geo.compass(az)}")
        self.message.emit(self.lbl_rotor.text())

    def _turn(self) -> None:
        if self._az is None:
            self.message.emit("Escolha um contato antes de girar a antena.")
            return
        try:
            client = rotator.RotatorClient.from_text(self.ed_rotor.text())
            client.set_azimuth(self._az)
            self.message.emit(f"Rotor: girando para {self._az:.0f}°.")
        except (ValueError, OSError, RuntimeError) as exc:
            self.message.emit(f"Rotor: {exc}")
