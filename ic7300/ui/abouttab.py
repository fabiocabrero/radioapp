"""Tela "Sobre e log": a proposta do projeto, as fontes usadas, o que ainda não foi testado e o registro de eventos."""
from __future__ import annotations

import os

from PySide6 import QtCore, QtGui, QtWidgets

from .. import __version__, applog

REPO = "https://github.com/fabiocabrero/radioapp"

PROPOSAL_HTML = f"""
<h2>IC-7300 Station <small>v{__version__} · versão de teste</small></h2>
<p><b>Um app de radioamadores, para radioamadores, aberto e completo.</b></p>
<p>Hoje, para operar bem, o radioamador precisa de um programa para cada coisa: um para o rádio, outro para FT8, outro para
CW, outro para Winlink, um site para propagação, outro para spots, outro para satélites, outro para o calendário de
concursos, outro para o log. Cada um com a sua sopa de letrinhas (VARA, ARDOP, FST4, Q65, ACDS, D-RAP, SFI, K, A...),
cada um com a sua instalação, a sua configuração e as suas armadilhas (porta COM ocupada, áudio trocado, relógio errado).</p>
<p><b>A proposta é acabar com isso:</b></p>
<ul>
<li><b>Centralizar a informação.</b> Rádio, espectro, modos, mapa de estações ao vivo, propagação, satélites, ondas curtas,
concursos, POTA/SOTA/WWFF e log numa só janela, sem longas buscas.</li>
<li><b>Traduzir as letrinhas.</b> Cada modo, protocolo e índice vem explicado em português, com o que ele é, onde usar e
em que frequência (catálogo de protocolos com IARU, ARRL e FCC).</li>
<li><b>Um clique até a operação.</b> Clicou no indicativo: o app sintoniza o rádio no modo certo, copia o indicativo e abre a
ferramenta correta.</li>
<li><b>Instalar uma vez.</b> Um instalador e um assistente que pergunta seus dados, instala o que você precisar e gera as
instruções de cada programa já com o seu indicativo, porta e áudio.</li>
<li><b>Aberto e da comunidade.</b> Código aberto, feito por radioamadores e melhorado com o que a comunidade encontrar:
bugs, ideias e planos de banda do seu país.</li>
</ul>
<p>Não substitui o que já é bom: orquestra WSJT-X, JS8Call, Fldigi, Winlink, VARA e outros, e embute o que pode ser aberto
(FT8/FT4, CW, RTTY, SSTV, mapa, propagação, satélites). O que é proprietário (VARA, VarAC) continua separado.</p>

<h3>Fontes de dados</h3>
<p>PSK Reporter · wspr.live · Reverse Beacon Network · DX Cluster · POTA · WWFF · NOAA SWPC · Open-Meteo · HamQTH ·
CelesTrak · SatNOGS DB · EiBi · WA7BNM (concursos) · N0NBH/HamQSL · Natural Earth · cty.dat (DXCC) · IARU R2 · ARRL · FCC ·
Plano de Bandas BR (PR7GA/LABRE). Cada fonte é consultada respeitando os limites que ela publica.</p>

<h3>Estado honesto</h3>
<ul>
<li>Validado no IC-7300 real: <b>somente recepção</b> (conexão, frequência, modo, scope, áudio).</li>
<li><b>Nunca testado no ar: toda a transmissão</b> (PTT, FT8, CW, RTTY, SSTV). Teste só em carga fantasma, baixa potência.</li>
<li>O mapa de calor é uma <b>estimativa simplificada</b>, não é VOACAP; as passagens de satélite têm erro de minutos.</li>
<li>O app avisa sobre limites do plano de bandas, mas a responsabilidade da operação é sempre do operador.</li>
</ul>

<h3>Participe</h3>
<p>Código, instalador, guia rápido e questionário de teste: <a href="{REPO}">{REPO}</a>. Dúvidas, bugs e sugestões:
abra uma <i>issue</i> no repositório ou responda ao questionário de teste. Anexe o log abaixo quando algo falhar.</p>
<p>73, <b>Fabio Cabrero, PR2FAB</b> (Itu-SP)</p>
"""


class AboutTab(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 10)
        tabs = QtWidgets.QTabWidget()
        lay.addWidget(tabs)

        about = QtWidgets.QTextBrowser()
        about.setOpenExternalLinks(True)
        about.setHtml(PROPOSAL_HTML)
        tabs.addTab(about, "Sobre e proposta")

        box = QtWidgets.QWidget()
        bl = QtWidgets.QVBoxLayout(box)
        self.lbl_path = QtWidgets.QLabel()
        self.lbl_path.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_path.setWordWrap(True)
        bl.addWidget(self.lbl_path)
        self.view = QtWidgets.QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont))
        bl.addWidget(self.view, 1)
        row = QtWidgets.QHBoxLayout()
        for text, slot in (("Atualizar", self.refresh), ("Copiar tudo", self._copy), ("Abrir pasta do log", self._open_folder)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch()
        bl.addLayout(row)
        note = QtWidgets.QLabel("O log guarda versão, mensagens do app e erros. Não grava senhas nem credenciais. "
                                "Confira o conteúdo antes de enviar a alguém.")
        note.setWordWrap(True)
        bl.addWidget(note)
        tabs.addTab(box, "Log de eventos")
        tabs.currentChanged.connect(lambda i: self.refresh() if i == 1 else None)

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        self.lbl_path.setText(f"Arquivo: {applog.log_path()}")
        self.view.setPlainText(applog.tail() or "(o log ainda está vazio)")
        self.view.moveCursor(QtGui.QTextCursor.MoveOperation.End)

    def _copy(self) -> None:
        QtWidgets.QApplication.clipboard().setText(self.view.toPlainText())

    def _open_folder(self) -> None:
        folder = applog.log_path().parent
        if hasattr(os, "startfile"):
            os.startfile(folder)  # noqa: S606 (pasta do próprio app)
        else:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(folder)))
