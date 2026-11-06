"""Tela de opções em grade de blocos (como o menu de aplicativos do Xiegu): cada bloco abre uma tela própria."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6 import QtCore, QtWidgets


@dataclass(frozen=True)
class AppEntry:
    key: str
    icon: str
    name: str
    subtitle: str


SECTIONS: tuple[tuple[str, tuple[AppEntry, ...]], ...] = (
    ("Operação", (
        AppEntry("radio", "📻", "Rádio", "Frequência, espectro, volume e PTT"),
    )),
    ("Modos", (
        AppEntry("cw", "〰", "CW", "Decodificador e manipulador"),
        AppEntry("ft8", "🛰", "FT8 / FT4", "Decodificar e transmitir"),
        AppEntry("rtty", "⌨", "RTTY", "AFSK 45 a 100 baud"),
        AppEntry("sstv", "🖼", "SSTV", "Martin e Scottie, imagens"),
        AppEntry("wsjt", "📶", "FST4 / Q65 / WSPR", "Recepção pelo motor do WSJT-X"),
        AppEntry("digital", "📋", "Frequências digitais", "Pontos de chamada por banda"),
        AppEntry("ext", "✉", "Winlink e outros", "VARA, VarAC, Pat, JS8Call, Fldigi"),
        AppEntry("protocols", "📚", "Protocolos e modos", "IARU, ARRL e FCC: o que é cada um"),
    )),
    ("Informação", (
        AppEntry("map", "🗺", "Mapa e propagação", "Dia/noite, índices solares, spots"),
        AppEntry("swl", "🌍", "Ondas curtas", "Emissoras no ar, horários e alvo"),
        AppEntry("bands", "📊", "Plano de bandas", "Faixas, classes e modos do seu país"),
    )),
    ("Atividades", (
        AppEntry("cluster", "📣", "DX Cluster", "Spots em tempo real"),
        AppEntry("pota", "🌲", "POTA", "Ativações no ar agora"),
        AppEntry("contests", "🏆", "Concursos", "Calendário, log e Cabrillo"),
        AppEntry("log", "📒", "Log", "QSOs, referências e ADIF"),
    )),
    ("Sistema", (
        AppEntry("location", "📍", "Local / GPS", "Indicativo, grid, classe e plano"),
        AppEntry("settings", "⚙", "Configurações", "Porta, áudio e integrações"),
    )),
)


class Tile(QtWidgets.QPushButton):
    def __init__(self, entry: AppEntry) -> None:
        super().__init__()
        self.entry = entry
        self.setObjectName("tile")
        self.setMinimumSize(150, 100)
        self.setMaximumSize(250, 120)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{entry.name}: {entry.subtitle}")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(2)
        icon = QtWidgets.QLabel(entry.icon)
        icon.setObjectName("tileIcon")
        name = QtWidgets.QLabel(entry.name)
        name.setObjectName("tileName")
        sub = QtWidgets.QLabel(entry.subtitle)
        sub.setObjectName("tileSub")
        sub.setWordWrap(True)
        for w in (icon, name, sub):
            w.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            w.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
            lay.addWidget(w)
        lay.addStretch()


class AppMenu(QtWidgets.QScrollArea):
    open_page = QtCore.Signal(str)

    def __init__(self, sections=SECTIONS) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        body = QtWidgets.QWidget()
        self.setWidget(body)
        outer = QtWidgets.QVBoxLayout(body)
        outer.setContentsMargins(20, 10, 20, 14)
        outer.setSpacing(8)
        self.tiles: dict[str, Tile] = {}
        for title, entries in sections:
            head = QtWidgets.QLabel(title.upper())
            head.setObjectName("sectionTitle")
            outer.addWidget(head)
            grid = QtWidgets.QGridLayout()
            grid.setSpacing(12)
            for i, entry in enumerate(entries):
                tile = Tile(entry)
                tile.clicked.connect(lambda _=False, k=entry.key: self.open_page.emit(k))
                grid.addWidget(tile, i // 6, i % 6)
                self.tiles[entry.key] = tile
            for c in range(6):
                grid.setColumnStretch(c, 1)
            outer.addLayout(grid)
        outer.addStretch()

    def keys(self) -> list[str]:
        return list(self.tiles)
