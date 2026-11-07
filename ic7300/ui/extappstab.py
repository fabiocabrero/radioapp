"""Página 'Winlink e outros': programas externos de modos digitais, com detecção, abertura e dicas de ligação."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6 import QtCore, QtGui, QtWidgets

from .. import extapps
from ..settings import Settings


class ExtAppCard(QtWidgets.QFrame):
    changed = QtCore.Signal()

    def __init__(self, app: extapps.ExtApp, settings: Settings, message: Callable[[str], None],
                 want_rigctl: Callable[[], None]) -> None:
        super().__init__()
        self.app, self.settings, self.message, self.want_rigctl = app, settings, message, want_rigctl
        self.setObjectName("card")
        lay = QtWidgets.QGridLayout(self)
        self.lbl_name = QtWidgets.QLabel(app.name)
        self.lbl_name.setObjectName("cardTitle")
        self.lbl_state = QtWidgets.QLabel()
        summary = QtWidgets.QLabel(app.summary)
        summary.setWordWrap(True)
        tips = QtWidgets.QLabel("\n".join("• " + t for t in app.tips))
        tips.setWordWrap(True)
        tips.setObjectName("cardTips")
        self.lbl_path = QtWidgets.QLabel()
        self.lbl_path.setObjectName("cardTips")
        self.btn_open = QtWidgets.QPushButton("Abrir")
        btn_find = QtWidgets.QPushButton("Procurar…")
        btn_get = QtWidgets.QPushButton("Como obter")
        lay.addWidget(self.lbl_name, 0, 0)
        lay.addWidget(self.lbl_state, 0, 1, QtCore.Qt.AlignmentFlag.AlignRight)
        lay.addWidget(summary, 1, 0, 1, 2)
        if app.tips:
            lay.addWidget(tips, 2, 0, 1, 2)
        lay.addWidget(self.lbl_path, 3, 0, 1, 2)
        row = QtWidgets.QHBoxLayout()
        for b in (self.btn_open, btn_find, btn_get):
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row, 4, 0, 1, 2)
        self.btn_open.clicked.connect(self._open)
        btn_find.clicked.connect(self._browse)
        btn_get.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl(app.url)))
        self.refresh()

    def path(self) -> Path | None:
        return extapps.find(self.app, self.settings.ext_paths.get(self.app.key, ""))

    def refresh(self) -> None:
        p = self.path()
        if p:
            self.lbl_state.setText("● instalado")
            self.lbl_state.setStyleSheet("color:#66bb6a;font-weight:600")
            self.lbl_path.setText(str(p))
        else:
            self.lbl_state.setText("○ não encontrado")
            self.lbl_state.setStyleSheet("color:#8a97a8")
            self.lbl_path.setText("Instale o programa ou use “Procurar…” se ele estiver em outra pasta.")
        self.btn_open.setEnabled(p is not None)

    def _open(self) -> None:
        p = self.path()
        if not p:
            return
        if self.app.needs_rigctl:
            self.want_rigctl()
        try:
            pid = extapps.launch(p)
            self.message(f"{self.app.name} aberto (PID {pid}).")
        except OSError as exc:
            self.message(f"Não foi possível abrir {self.app.name}: {exc}")

    def _browse(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, f"Onde está o {self.app.name}?", "", "Programas (*.exe);;Todos (*)")
        if path:
            self.settings.ext_paths[self.app.key] = path
            self.settings.save()
            self.refresh()
            self.changed.emit()


class ExtAppsTab(QtWidgets.QWidget):
    rigctl_requested = QtCore.Signal()
    message = QtCore.Signal(str)

    def open_app(self, key: str) -> bool:
        """Abre o programa pelo código (usado pelo mapa). False se não está instalado."""
        card = next((c for c in self.cards if c.app.key == key), None)
        if not card or not card.path():
            return False
        card._open()
        return True

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        outer = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel(
            "Estes modos são programas de terceiros. VARA e VarAC são proprietários (código fechado) e só funcionam pelos próprios "
            "programas; este app não os reimplementa. Aqui você abre cada um e vê como ligá-lo ao rádio e à placa de som. "
            "Para dividir o rádio com eles, ative o servidor rigctl em Configurações.")
        intro.setWordWrap(True)
        outer.addWidget(intro)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        body = QtWidgets.QWidget()
        scroll.setWidget(body)
        col = QtWidgets.QVBoxLayout(body)
        self.cards: list[ExtAppCard] = []
        for group in extapps.GROUPS:
            head = QtWidgets.QLabel(group.upper())
            head.setObjectName("sectionTitle")
            col.addWidget(head)
            for app in (a for a in extapps.APPS if a.group == group):
                card = ExtAppCard(app, settings, self.message.emit, self.rigctl_requested.emit)
                col.addWidget(card)
                self.cards.append(card)
        col.addStretch()
        outer.addWidget(scroll, 1)
        btn = QtWidgets.QPushButton("Verificar de novo")
        btn.clicked.connect(lambda: [c.refresh() for c in self.cards])
        outer.addWidget(btn, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
