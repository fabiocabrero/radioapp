"""Tela Fonia dentro da janela com o simulador: chamadas em CW, PTT do operador suspende e a caixa pergunta se retoma."""
import os
import sys
import tempfile
import time

os.environ.setdefault("IC7300_APPDATA", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def pump(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def test_fonia_chamadas_ptt_e_dialogo(monkeypatch):
    from dataclasses import replace

    from PySide6 import QtWidgets
    from ic7300.ui.main_window import MainWindow
    from ic7300.ui.spacedata import SpaceData

    monkeypatch.setattr(SpaceData, "refresh", lambda self: None)
    errors = []
    old_hook = sys.excepthook
    sys.excepthook = lambda t, v, tb: errors.append(f"{t.__name__}: {v}")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    try:
        w = MainWindow()
        w.show()
        w.btn_connect.click()
        pump(app, 1.2)
        v = w.voice
        w.show_page("voice")
        w.radio.set_mode("CW")
        pump(app, 0.5)
        v.store.add_cw("CQ CW", "cq de py2xx")
        v._refresh_messages()
        sent = []
        orig = w.radio.send_cw
        monkeypatch.setattr(w.radio, "send_cw", lambda t: (sent.append(t), orig(t)))
        v.sp_gap.setMinimum(1)
        v.sp_gap.setValue(5)
        v.sp_clear.setValue(1)
        v.sp_wpm.setValue(40)
        v.chk_end.setChecked(False)
        v.chk_abort_mic.setChecked(False)
        v.btn_calls.setChecked(True)  # simulador: sem confirmação
        pump(app, 4.0)
        assert v.caller.running and len(sent) >= 1, (sent, v.lbl_calls.text())
        # operador aciona o PTT do rádio fora da transmissão do app
        end = time.time() + 8
        while v.caller.is_own_tx() and time.time() < end:  # espera a lacuna entre as chamadas
            pump(app, 0.05)
        assert not v.caller.is_own_tx()
        n = len(sent)
        v.on_radio_state(replace(w.state, ptt=True))
        pump(app, 0.5)
        assert v.caller.paused and v._dialog is not None
        pump(app, 1.5)
        assert len(sent) == n  # suspenso: não transmite
        v.on_radio_state(replace(w.state, ptt=False))
        v._dialog.buttons()[0].click()  # "Retomar"
        pump(app, 3.0)
        assert len(sent) > n
        v.btn_calls.setChecked(False)
        pump(app, 0.3)
        assert not v.caller.running
        w._panic()
        w.close()
        pump(app, 0.3)
    finally:
        sys.excepthook = old_hook
    assert not errors, errors
