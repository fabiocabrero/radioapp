import os
import tempfile

os.environ.setdefault("IC7300_APPDATA", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ic7300 import extapps, thirdparty
from ic7300.thirdparty import OperatorInfo

INFO = OperatorInfo("PY2XX", "Fabio", "Itu", "GG67ob", -23.26, -47.3, "COM4", "USB Audio CODEC", "USB Audio CODEC")


def test_offered_apps_exist_and_have_instructions():
    for key in thirdparty.OFFERED:
        extapps.by_key(key)
        html = thirdparty.instructions_html(key, INFO)
        assert "Site oficial" in html
    for key in ("wsjtx", "js8call", "fldigi", "winlink_express", "varac", "n1mm"):
        html = thirdparty.instructions_html(key, INFO)
        assert "PY2XX" in html and "GG67ob" in html, key
    for key in ("wsjtx", "fldigi", "pat", "varac"):
        assert "127.0.0.1:4532" in thirdparty.instructions_html(key, INFO), key
    assert "COM4" in thirdparty.instructions_html("winlink_express", INFO)
    assert "<script" not in thirdparty.instructions_html("wsjtx", OperatorInfo(callsign="<script>x</script>"))


def test_winget_commands():
    assert set(thirdparty.WINGET_IDS) <= set(thirdparty.OFFERED)
    args = thirdparty.winget_args("wsjtx")
    assert args[:3] == ["install", "--id", "JoeTaylor.WSJT-X"] and "--exact" in args and "--silent" in args
    assert thirdparty.method("pat") == "página oficial" and thirdparty.method("fldigi") == "winget"
    html = thirdparty.all_instructions_html(["wsjtx", "pat"], INFO)
    assert html.count("<h3>") == 2 and "PY2XX" in html


def test_wizard_flow(tmp_path, monkeypatch):
    from PySide6 import QtWidgets
    from ic7300.settings import Settings
    from ic7300.ui.setupwizard import SetupWizard

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    s = Settings()
    wiz = SetupWizard(s)
    op = wiz.operator
    assert not op.isComplete()
    op.ed_call.setText("py2xx")
    assert op.isComplete()
    op.ed_name.setText("Fabio")
    op.ed_grid.setText("GG67")
    assert op.validatePage() and op.sp_lat.value() != 0 and op.sp_lon.value() != 0
    wiz.apps.table.item(0, 0).setCheckState(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.CheckState.Unchecked)
    assert wiz.apps.table.rowCount() == len(thirdparty.OFFERED)
    wiz.instr.initializePage()
    wiz.instr.list.setCurrentRow(0)
    assert wiz.instr.view.toPlainText().strip()
    wiz.apply()
    saved = Settings.load()
    assert saved.callsign == "PY2XX" and saved.grid == "GG67" and saved.setup_done and saved.lat < 0
    app.processEvents()
