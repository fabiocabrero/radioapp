"""Página 'Protocolos e modos': catálogo com reconhecimento IARU/FCC, onde operar e o que há neste app."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6 import QtCore, QtWidgets

DATA = Path(__file__).parent.parent / "data" / "protocols.json"
APP_LABEL = {"native": "Nativo neste app", "engine": "Recepção pelo motor do WSJT-X instalado",
             "external": "Programa externo (aba Winlink e outros)", "none": "Sem suporte neste app"}
_DATA_KINDS = {"Imagem (SSTV/FAX)", "Voz digital"}


def tune_mode(kind: str, khz: float) -> tuple[str, bool]:
    """(modo, usa DATA) para sintonizar um centro de atividade."""
    if kind.startswith("CW"):
        return "CW", False
    if kind == "AM":
        return "AM", False
    if kind == "FM chamada":
        return "FM", False
    if kind == "6 m" and khz == 50305:
        return "USB", True
    return ("LSB" if khz < 10_000 else "USB"), kind in _DATA_KINDS


class ProtocolsTab(QtWidgets.QWidget):
    open_page = QtCore.Signal(str)
    tune_requested = QtCore.Signal(int, str, bool)  # Hz, modo, DATA

    def __init__(self) -> None:
        super().__init__()
        raw = json.loads(DATA.read_text(encoding="utf-8"))
        self.protocols, self.centers, self.source = raw["protocols"], raw["centers"], raw["_fonte"]
        lay = QtWidgets.QVBoxLayout(self)
        tabs = QtWidgets.QTabWidget()
        lay.addWidget(tabs, 1)

        # ---- catálogo
        cat = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(cat)
        left = QtWidgets.QVBoxLayout()
        self.cb_cat = QtWidgets.QComboBox()
        self.cb_cat.addItem("Todas as categorias", "")
        for c in sorted({p["category"] for p in self.protocols}):
            self.cb_cat.addItem(c, c)
        self.lst = QtWidgets.QListWidget()
        left.addWidget(self.cb_cat)
        left.addWidget(self.lst, 1)
        h.addLayout(left, 2)
        right = QtWidgets.QVBoxLayout()
        self.detail = QtWidgets.QTextBrowser()
        self.detail.setOpenExternalLinks(True)
        self.btn_open = QtWidgets.QPushButton("")
        right.addWidget(self.detail, 1)
        right.addWidget(self.btn_open, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
        h.addLayout(right, 4)
        tabs.addTab(cat, "Protocolos")

        # ---- centros de atividade
        self.tbl = QtWidgets.QTableWidget(0, 3)
        self.tbl.setHorizontalHeaderLabels(["Tipo", "Frequência", "Banda"])
        self.tbl.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        for c in self.centers:
            r = self.tbl.rowCount()
            self.tbl.insertRow(r)
            band = f"{c['khz'] / 1000:g} MHz"
            for i, v in enumerate((c["kind"], c["label"], band)):
                self.tbl.setItem(r, i, QtWidgets.QTableWidgetItem(v))
        wrap = QtWidgets.QWidget()
        wl = QtWidgets.QVBoxLayout(wrap)
        wl.addWidget(QtWidgets.QLabel("Centros de atividade do plano da IARU Região 2 (voluntários). Duplo clique sintoniza o rádio."))
        wl.addWidget(self.tbl, 1)
        tabs.addTab(wrap, "Centros de atividade")

        note = QtWidgets.QLabel(f"Fontes: {self.source} A IARU e a ARRL publicam planos voluntários; vale sempre a regulamentação do seu país.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#8a97a8; font-size:8pt")
        lay.addWidget(note)

        self.cb_cat.currentIndexChanged.connect(self._fill)
        self.lst.currentRowChanged.connect(self._show)
        self.btn_open.clicked.connect(self._open)
        self.tbl.cellDoubleClicked.connect(self._tune)
        self._shown: list[dict] = []
        self._fill()

    def _fill(self) -> None:
        cat = self.cb_cat.currentData()
        self._shown = [p for p in self.protocols if not cat or p["category"] == cat]
        self.lst.clear()
        for p in self._shown:
            self.lst.addItem(p["name"])
        if self._shown:
            self.lst.setCurrentRow(0)

    def _show(self, row: int) -> None:
        if not (0 <= row < len(self._shown)):
            return
        p = self._shown[row]
        parts = [f"<h2>{p['name']}</h2>", f"<p>{p['summary']}</p>",
                 f"<p><b>Categoria:</b> {p['category']} &nbsp; <b>Classe IARU:</b> {p['iaru']} &nbsp; <b>Largura típica:</b> {p['bw']}</p>"]
        if p.get("where"):
            parts.append(f"<p><b>Onde:</b> {p['where']}</p>")
        parts.append(f"<p><b>Reconhecimento:</b> {p['recognition']}</p>")
        parts.append(f"<p><b>Neste app:</b> {APP_LABEL[p['app']]}</p>")
        self.detail.setHtml("".join(parts))
        self._current = p
        if p["app"] in ("native", "engine"):
            self.btn_open.setText(f"Abrir {p['name']}")
            self.btn_open.show()
        elif p["app"] == "external":
            self.btn_open.setText("Ver programas externos")
            self.btn_open.show()
        else:
            self.btn_open.hide()

    def _open(self) -> None:
        p = getattr(self, "_current", None)
        if p:
            self.open_page.emit(p.get("page") or "ext")

    def _tune(self, row: int, _col: int) -> None:
        c = self.centers[row]
        mode, data = tune_mode(c["kind"], c["khz"])
        self.tune_requested.emit(int(round(c["khz"] * 1000)), mode, data)
