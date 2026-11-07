import os
import sys
import tempfile
import time

import pytest

os.environ.setdefault("IC7300_APPDATA", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ic7300 import rigs

EXE = rigs.find_rigctld()
needs_hamlib = pytest.mark.skipif(EXE is None, reason="rigctld (Hamlib) não instalado")


def test_s_meter_conversao():
    assert rigs.s_raw_from_db(0) == 120          # S9
    assert rigs.s_raw_from_db(-54) == 0          # S0
    assert rigs.s_raw_from_db(60) >= 240         # S9+60
    assert rigs.s_raw_from_db(-200) == 0 and rigs.s_raw_from_db(200) == 255


def test_lista_de_modelos_interpreta_a_saida(monkeypatch, tmp_path):
    class R:
        stdout = ("Rig #  Mfg                    Model                   Version         Status      Macro\n"
                  "  1  Hamlib                 Dummy                   20240709.0      Stable      RIG_MODEL_DUMMY\n"
                  "3073  Icom                   IC-7300                 20250107.14     Stable      RIG_MODEL_IC7300\n"
                  "1035  Yaesu                  FT-991                  20241118.18     Stable      RIG_MODEL_FT991\n"
                  "2037  Kenwood                TS-590SG                20250107.12     Stable      RIG_MODEL_TS590SG\n")
    monkeypatch.setattr(rigs.subprocess, "run", lambda *a, **k: R())
    models = rigs.list_models(tmp_path / "rigctld.exe")
    assert [(m.number, m.brand, m.name) for m in models if m.brand in rigs.BRANDS] == \
        [(3073, "Icom", "IC-7300"), (2037, "Kenwood", "TS-590SG"), (1035, "Yaesu", "FT-991")]


@needs_hamlib
def test_hamlib_rig_contra_rigctld_real():
    dummy = next(m for m in rigs.list_models(EXE) if m.name == "Dummy")
    rig = rigs.HamlibRig(port=4571, process=rigs.RigctldProcess(EXE, dummy.number, "", 38400, tcp_port=4571))
    msgs = []
    rig.on_message = msgs.append
    rig.start()
    try:
        assert rig.state.connected
        rig.set_freq(7_074_000)
        rig.set_mode("USB", True)
        time.sleep(0.8)
        assert (rig.state.freq, rig.state.mode, rig.state.data_mode) == (7_074_000, "USB", True)
        rig.set_mode("CW")
        rig.set_ptt(True)
        time.sleep(0.6)
        assert rig.state.mode == "CW" and rig.state.ptt
        rig.set_ptt(False)
        rig.set_level("af", 128)
        time.sleep(0.6)
        assert not rig.state.ptt and rig.state.levels["af"] == 128
        assert not msgs, msgs
    finally:
        rig.stop()
    assert rig.process.proc is None


@needs_hamlib
def test_janela_conecta_por_hamlib(monkeypatch):
    from PySide6 import QtWidgets

    from ic7300.ui.main_window import MainWindow
    from ic7300.ui.spacedata import SpaceData

    monkeypatch.setattr(SpaceData, "refresh", lambda self: None)
    errors = []
    old = sys.excepthook
    sys.excepthook = lambda t, v, tb: errors.append(f"{t.__name__}: {v}")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    try:
        w = MainWindow()
        w.show()
        i = w.cb_kind.findData("hamlib")
        w.cb_kind.setCurrentIndex(i)
        assert w.cb_model.count() >= 80                      # marca Icom: modelos do Hamlib
        w.cb_brand.setCurrentText("Todas as marcas")
        dummy = w.cb_model.findText("Hamlib Dummy")
        assert dummy >= 0
        w.cb_model.setCurrentIndex(dummy)
        w.btn_connect.click()
        end = time.time() + 3
        while time.time() < end:
            app.processEvents()
            time.sleep(0.02)
        assert w.radio is not None and w.state.connected
        w.radio.set_freq(14_200_000)
        end = time.time() + 1.5
        while time.time() < end:
            app.processEvents()
            time.sleep(0.02)
        assert w.state.freq == 14_200_000
        w.btn_connect.click()  # desconecta e encerra o rigctld
        w.close()
    finally:
        sys.excepthook = old
    assert not errors, errors
