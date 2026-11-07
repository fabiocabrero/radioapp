"""Assistente de primeiros passos: dados do operador, rádio e som, programas de terceiros e instruções personalizadas."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from .. import extapps, geo, thirdparty
from ..audio import list_input_devices, list_output_devices
from ..radio import list_serial_ports
from ..settings import Settings
from ..thirdparty import OperatorInfo

_CALL = re.compile(r"^[A-Z0-9]{1,3}\d[A-Z0-9]{0,3}[A-Z](/[A-Z0-9]+)?$")


def _combo(items: list[str], prefer: str = "") -> QtWidgets.QComboBox:
    cb = QtWidgets.QComboBox()
    cb.setEditable(True)
    cb.addItems(items)
    for i, t in enumerate(items):
        if prefer and prefer.lower() in t.lower():
            cb.setCurrentIndex(i)
            break
    return cb


class OperatorPage(QtWidgets.QWizardPage):
    def __init__(self, s: Settings) -> None:
        super().__init__()
        self.setTitle("Quem é o operador")
        self.setSubTitle("Estes dados vão para este app e para as instruções dos programas de terceiros.")
        form = QtWidgets.QFormLayout(self)
        self.ed_call = QtWidgets.QLineEdit(s.callsign)
        self.ed_name = QtWidgets.QLineEdit(s.op_name)
        self.ed_city = QtWidgets.QLineEdit(s.op_city)
        self.ed_grid = QtWidgets.QLineEdit(s.grid)
        self.ed_grid.setPlaceholderText("ex.: GG67 ou GG67ob")
        self.sp_lat = QtWidgets.QDoubleSpinBox()
        self.sp_lon = QtWidgets.QDoubleSpinBox()
        for sp, lim in ((self.sp_lat, 90), (self.sp_lon, 180)):
            sp.setRange(-lim, lim)
            sp.setDecimals(4)
        self.sp_lat.setValue(s.lat)
        self.sp_lon.setValue(s.lon)
        self.lbl_err = QtWidgets.QLabel("")
        self.lbl_err.setStyleSheet("color:#ef9a9a")
        form.addRow("Indicativo", self.ed_call)
        form.addRow("Nome", self.ed_name)
        form.addRow("Cidade / QTH", self.ed_city)
        form.addRow("Grid locator", self.ed_grid)
        form.addRow("Latitude", self.sp_lat)
        form.addRow("Longitude", self.sp_lon)
        form.addRow(QtWidgets.QLabel("Informe o grid ou a latitude/longitude: o outro é calculado."))
        form.addRow(self.lbl_err)
        self.ed_call.textChanged.connect(lambda: self.completeChanged.emit())

    def isComplete(self) -> bool:
        return bool(_CALL.match(self.ed_call.text().strip().upper()))

    def validatePage(self) -> bool:
        grid = self.ed_grid.text().strip()
        try:
            if grid and not (self.sp_lat.value() or self.sp_lon.value()):
                self.sp_lat.setValue(geo.grid_to_latlon(grid)[0])
                self.sp_lon.setValue(geo.grid_to_latlon(grid)[1])
            elif not grid and (self.sp_lat.value() or self.sp_lon.value()):
                self.ed_grid.setText(geo.latlon_to_grid(self.sp_lat.value(), self.sp_lon.value()))
        except ValueError as exc:
            self.lbl_err.setText(str(exc))
            return False
        return True


class RadioPage(QtWidgets.QWizardPage):
    def __init__(self, s: Settings) -> None:
        super().__init__()
        self.setTitle("Rádio e som")
        self.setSubTitle("Ligue o IC-7300 ao PC por USB e ligue o rádio. Escolha as portas encontradas.")
        form = QtWidgets.QFormLayout(self)
        ports = [f"{dev} — {desc}" for dev, desc in list_serial_ports()]
        self.cb_port = _combo(ports, "CP210")
        if s.port:
            self.cb_port.setCurrentText(next((p for p in ports if p.startswith(s.port)), s.port))
        self.cb_in = _combo(list_input_devices(), "USB Audio CODEC")
        self.cb_out = _combo(list_output_devices(), "USB Audio CODEC")
        self.chk_rigctl = QtWidgets.QCheckBox("Ativar o servidor rigctl (para WSJT-X, JS8Call, Fldigi, Pat... dividirem o rádio)")
        self.chk_rigctl.setChecked(True)
        form.addRow("Porta COM do rádio", self.cb_port)
        form.addRow("Entrada de áudio", self.cb_in)
        form.addRow("Saída de áudio", self.cb_out)
        form.addRow(self.chk_rigctl)
        form.addRow(QtWidgets.QLabel("O IC-7300 aparece como “Silicon Labs CP210x” (COM) e “USB Audio CODEC” (som)."))

    def port(self) -> str:
        return self.cb_port.currentText().split(" — ")[0].strip()


class AppsPage(QtWidgets.QWizardPage):
    def __init__(self, s: Settings) -> None:
        super().__init__()
        self.s = s
        self.setTitle("Programas de terceiros")
        self.setSubTitle("Marque o que quer instalar. Os instaladores vêm dos sites oficiais; nada é redistribuído por este app.")
        lay = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Instalar", "Programa", "Situação", "Como"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table, 1)
        self.lbl_note = QtWidgets.QLabel(
            "winget: instala em modo silencioso a partir do site do autor, com conferência do hash (pode pedir permissão de administrador). "
            "Página oficial: abre o site no navegador para você baixar e instalar. Licenças: VARA e VarAC são proprietários; "
            "Winlink Express exige conta gratuita no Winlink.")
        self.lbl_note.setWordWrap(True)
        lay.addWidget(self.lbl_note)
        row = QtWidgets.QHBoxLayout()
        self.btn_install = QtWidgets.QPushButton("Instalar / abrir os marcados")
        self.btn_recheck = QtWidgets.QPushButton("Verificar de novo")
        row.addWidget(self.btn_install)
        row.addWidget(self.btn_recheck)
        row.addStretch()
        lay.addLayout(row)
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(110)
        lay.addWidget(self.log)
        self.proc = QtCore.QProcess(self)
        self.proc.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
        self.proc.readyRead.connect(self._read)
        self.proc.finished.connect(self._next)
        self.queue: list[str] = []
        self.btn_install.clicked.connect(self._install)
        self.btn_recheck.clicked.connect(self.refresh)
        self.refresh()

    def installed(self, key: str) -> bool:
        return extapps.find(extapps.by_key(key), self.s.ext_paths.get(key, "")) is not None

    def refresh(self) -> None:
        marked = {self.table.item(r, 1).data(QtCore.Qt.ItemDataRole.UserRole): self.table.item(r, 0).checkState()
                  for r in range(self.table.rowCount())}
        self.table.setRowCount(len(thirdparty.OFFERED))
        for r, key in enumerate(thirdparty.OFFERED):
            app = extapps.by_key(key)
            have = self.installed(key)
            chk = QtWidgets.QTableWidgetItem()
            chk.setFlags(QtCore.Qt.ItemFlag.ItemIsUserCheckable | QtCore.Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(marked.get(key, QtCore.Qt.CheckState.Unchecked if have else QtCore.Qt.CheckState.Checked))
            name = QtWidgets.QTableWidgetItem(app.name)
            name.setData(QtCore.Qt.ItemDataRole.UserRole, key)
            name.setToolTip(app.summary + "\n" + thirdparty.LICENSE_NOTES.get(key, ""))
            state = QtWidgets.QTableWidgetItem("● instalado" if have else "○ não encontrado")
            state.setForeground(QtGui.QColor("#66bb6a" if have else "#9aa7b6"))
            how = thirdparty.method(key)
            if how == "winget" and not thirdparty.winget_path():
                how = "página oficial (winget indisponível)"
            for c, it in enumerate((chk, name, state, QtWidgets.QTableWidgetItem(how))):
                self.table.setItem(r, c, it)
        self.table.resizeColumnsToContents()

    def selected(self) -> list[str]:
        return [self.table.item(r, 1).data(QtCore.Qt.ItemDataRole.UserRole) for r in range(self.table.rowCount())
                if self.table.item(r, 0).checkState() == QtCore.Qt.CheckState.Checked]

    def _install(self) -> None:
        keys = [k for k in self.selected() if not self.installed(k)]
        if not keys:
            self.log.appendPlainText("Nada a instalar entre os marcados.")
            return
        names = "\n".join(f"• {extapps.by_key(k).name} ({thirdparty.method(k)})" for k in keys)
        if QtWidgets.QMessageBox.question(self, "Confirmar", f"Instalar/abrir a página destes programas?\n\n{names}") \
                != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self.btn_install.setEnabled(False)
        for k in keys:
            if k in thirdparty.WINGET_IDS and thirdparty.winget_path():
                self.queue.append(k)
            else:
                QtGui.QDesktopServices.openUrl(QtCore.QUrl(extapps.by_key(k).url))
                self.log.appendPlainText(f"{extapps.by_key(k).name}: página oficial aberta no navegador ({extapps.by_key(k).url}).")
        self._next()

    def _next(self, *_args) -> None:
        if self.proc.state() != QtCore.QProcess.ProcessState.NotRunning:
            return
        if not self.queue:
            self.btn_install.setEnabled(True)
            self.refresh()
            return
        key = self.queue.pop(0)
        self.log.appendPlainText(f"\n== Instalando {extapps.by_key(key).name} (winget {thirdparty.WINGET_IDS[key]})…")
        self.proc.start(thirdparty.winget_path(), thirdparty.winget_args(key))

    def _read(self) -> None:
        text = bytes(self.proc.readAll()).decode("utf-8", "replace")
        for line in text.replace("\r", "\n").splitlines():
            if re.search(r"[A-Za-z0-9]", line) and "%" not in line[:12]:
                self.log.appendPlainText(line.strip())


class InstructionsPage(QtWidgets.QWizardPage):
    def __init__(self, apps: AppsPage, operator: OperatorPage, radio: RadioPage) -> None:
        super().__init__()
        self.apps, self.operator, self.radio = apps, operator, radio
        self.setTitle("Instruções de configuração")
        self.setSubTitle("Passos personalizados com os seus dados para cada programa escolhido.")
        lay = QtWidgets.QHBoxLayout(self)
        self.list = QtWidgets.QListWidget()
        self.list.setMaximumWidth(210)
        self.view = QtWidgets.QTextBrowser()
        self.view.setOpenExternalLinks(True)
        side = QtWidgets.QVBoxLayout()
        side.addWidget(self.list, 1)
        self.btn_save = QtWidgets.QPushButton("Salvar tudo em HTML…")
        side.addWidget(self.btn_save)
        lay.addLayout(side)
        lay.addWidget(self.view, 1)
        self.list.currentRowChanged.connect(self._show)
        self.btn_save.clicked.connect(self._save)
        self.keys: list[str] = []

    def info(self) -> OperatorInfo:
        o, r = self.operator, self.radio
        return OperatorInfo(o.ed_call.text().strip().upper(), o.ed_name.text().strip(), o.ed_city.text().strip(),
                            o.ed_grid.text().strip(), o.sp_lat.value(), o.sp_lon.value(), r.port(),
                            r.cb_in.currentText(), r.cb_out.currentText())

    def initializePage(self) -> None:
        self.keys = [k for k in thirdparty.OFFERED if k in self.apps.selected() or self.apps.installed(k)]
        self.list.clear()
        self.list.addItems([extapps.by_key(k).name for k in self.keys])
        if self.keys:
            self.list.setCurrentRow(0)
        else:
            self.view.setHtml("<p>Nenhum programa escolhido ou instalado. Você pode reabrir o assistente depois (Apps > Assistente).</p>")

    def _show(self, row: int) -> None:
        if 0 <= row < len(self.keys):
            self.view.setHtml(thirdparty.instructions_html(self.keys[row], self.info()))

    def _save(self) -> None:
        docs = Path.home() / "Documents"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Salvar instruções", str(docs / "Configuracao-programas-IC7300.html"),
                                                        "HTML (*.html)")
        if path:
            Path(path).write_text(thirdparty.all_instructions_html(self.keys, self.info()), encoding="utf-8")


class SetupWizard(QtWidgets.QWizard):
    def __init__(self, settings: Settings, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("IC-7300 Station — assistente de primeiros passos")
        self.setWizardStyle(QtWidgets.QWizard.WizardStyle.ModernStyle)
        self.setMinimumSize(820, 560)
        intro = QtWidgets.QWizardPage()
        intro.setTitle("Bem-vindo")
        il = QtWidgets.QVBoxLayout(intro)
        txt = QtWidgets.QLabel(
            "Este assistente configura o app e prepara os programas de terceiros (WSJT-X, JS8Call, Fldigi, Winlink Express, Pat, VARA, "
            "VarAC...). Ele pergunta os seus dados, instala o que você marcar a partir dos sites oficiais e mostra, programa por programa, "
            "o que digitar em cada tela de configuração. Nada é enviado a ninguém: os dados ficam neste PC.")
        txt.setWordWrap(True)
        il.addWidget(txt)
        self.operator = OperatorPage(settings)
        self.radio = RadioPage(settings)
        self.apps = AppsPage(settings)
        self.instr = InstructionsPage(self.apps, self.operator, self.radio)
        for p in (intro, self.operator, self.radio, self.apps, self.instr):
            self.addPage(p)
        self.setButtonText(QtWidgets.QWizard.WizardButton.NextButton, "Avançar >")
        self.setButtonText(QtWidgets.QWizard.WizardButton.BackButton, "< Voltar")
        self.setButtonText(QtWidgets.QWizard.WizardButton.CancelButton, "Cancelar")
        self.setButtonText(QtWidgets.QWizard.WizardButton.FinishButton, "Concluir")

    def apply(self) -> None:
        s, o = self.settings, self.operator
        s.callsign, s.op_name, s.op_city = o.ed_call.text().strip().upper(), o.ed_name.text().strip(), o.ed_city.text().strip()
        s.grid, s.lat, s.lon = o.ed_grid.text().strip(), o.sp_lat.value(), o.sp_lon.value()
        s.port = self.radio.port()
        s.audio_input = "" if "USB Audio CODEC" in self.radio.cb_in.currentText() else self.radio.cb_in.currentText()
        s.audio_output = "" if "USB Audio CODEC" in self.radio.cb_out.currentText() else self.radio.cb_out.currentText()
        s.rigctl_enabled = self.radio.chk_rigctl.isChecked()
        s.setup_done = True
        s.save()

    def done(self, result: int) -> None:
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            self.apply()
        else:
            self.settings.setup_done = True   # não insistir a cada abertura; o assistente fica em Apps > Assistente
            self.settings.save()
        super().done(result)
