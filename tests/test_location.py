import os
import socket
import sys
import tempfile
import threading
import time

os.environ.setdefault("IC7300_APPDATA", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ic7300 import geo, rotator


def test_compass_e_caminho_longo():
    assert geo.compass(0) == "N" and geo.compass(90) == "L" and geo.compass(225) == "SO" and geo.compass(359) == "N"
    # Itu (SP) -> Espanha: nordeste, ~9 000 km; o caminho longo é o oposto
    info = geo.bearing_info(-23.26, -47.30, 41.4, 2.2)
    assert 30 < info["short_az"] < 45 and 8000 < info["short_km"] < 10500
    assert abs(info["long_az"] - (info["short_az"] + 180) % 360) < 1e-6
    assert abs(info["short_km"] + info["long_km"] - 40030) < 1


def test_rotor_cliente_contra_servidor_falso():
    got = []
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def serve():
        for _ in range(2):
            c, _ = srv.accept()
            line = c.makefile("rb").readline().decode().strip()
            got.append(line)
            c.sendall(b"RPRT 0\n" if line.startswith("P") else b"123.5\n0.0\n")
            c.close()

    threading.Thread(target=serve, daemon=True).start()
    r = rotator.RotatorClient.from_text(f"127.0.0.1:{port}")
    r.set_azimuth(48.6)
    assert r.get_azimuth() == 123.5 and got[0] == "P 48.6 0.0" and got[1] == "p"
    srv.close()


def test_windows_location_nao_quebra(monkeypatch):
    monkeypatch.setattr("subprocess.run", lambda *a, **k: (_ for _ in ()).throw(OSError("sem powershell")))
    assert geo.windows_location(1) is None


def test_dialogo_de_localizacao_e_cartao_na_janela(monkeypatch):
    from PySide6 import QtWidgets

    from ic7300.ui.locationdialog import LocationDialog
    from ic7300.ui.main_window import MainWindow
    from ic7300.ui.spacedata import SpaceData

    monkeypatch.setattr(SpaceData, "refresh", lambda self: None)
    errors = []
    old = sys.excepthook
    sys.excepthook = lambda t, v, tb: errors.append(f"{t.__name__}: {v}")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    try:
        d = LocationDialog(None, None, "", (0.0, 0.0, ""))
        d.ed_grid.setText("GG66pf")
        d._from_grid("GG66pf")
        exp = geo.grid_to_latlon("GG66pf")
        assert abs(d.sp_lat.value() - exp[0]) < 1e-4 and abs(d.sp_lon.value() - exp[1]) < 1e-4
        d.ed_grid.setText("ZZ99")
        d._accept()
        assert "inválido" in d.lbl_err.text() and not d.result()
        d2 = LocationDialog(None, (-23.26, -47.30), "GPS", (0.0, 0.0, ""))
        assert d2.ed_grid.text().upper().startswith("GG6") and "detectada" in d2.findChild(QtWidgets.QLabel).text()

        w = MainWindow()
        w.show()
        # detectada pelo Windows: o operador confirma (diálogo aceito) e a localização é gravada
        monkeypatch.setattr(LocationDialog, "exec", lambda self: 1)
        assert w._ask_location((-23.26, -47.30), "Windows")
        assert w.settings.loc_confirmed and abs(w.settings.lat + 23.26) < 0.01 and w.settings.grid.upper().startswith("GG6")
        # recusado: nada muda
        w.settings.loc_confirmed = False
        monkeypatch.setattr(LocationDialog, "exec", lambda self: 0)
        assert not w._ask_location(None, "")
        assert not w.settings.loc_confirmed
        # card de direção: indicativo -> centro do país; grid do contato -> mais preciso
        w.ed_call.setText("EA3FF")
        assert "°" in w.bearing_radio.lbl_short.text() and w.bearing_ft.lbl_short.text() == w.bearing_radio.lbl_short.text()
        az_country = w.bearing_radio.azimuth()
        assert 30 < az_country < 70
        w.ed_qgrid.setText("JN11")
        assert "grid" in w.bearing_radio.lbl_note.text().lower() and w.bearing_radio.azimuth() != az_country
        w.ed_call.setText("")
        w.ed_qgrid.setText("")
        assert w.bearing_radio.lbl_short.text() == ""
        w.close()
        end = time.time() + 0.2
        while time.time() < end:
            app.processEvents()
    finally:
        sys.excepthook = old
    assert not errors, errors


def test_verificar_rotor_no_card():
    from PySide6 import QtWidgets

    from ic7300.ui.bearingcard import BearingCard

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def serve():
        c, _ = srv.accept()
        c.makefile("rb").readline()
        c.sendall(b"212.4\n0.0\n")
        c.close()

    threading.Thread(target=serve, daemon=True).start()
    card = BearingCard(lambda: (-23.26, -47.30))
    # rotor sem endereço válido: erro claro, sem travar
    card._check()
    assert "host:porta" in card.lbl_rotor.text() and card.btn_check.isEnabled()
    # rotor respondendo
    card.ed_rotor.setText(f"127.0.0.1:{port}")
    card._check()
    end = time.time() + 5
    while time.time() < end and "conectado" not in card.lbl_rotor.text():
        app.processEvents()
        time.sleep(0.02)
    assert "Rotor conectado: antena em 212" in card.lbl_rotor.text() and card.dial.rotor == 212.4
    # rotor fora do ar (porta fechada)
    srv.close()
    card._check()
    end = time.time() + 6
    while time.time() < end and not card.btn_check.isEnabled():
        app.processEvents()
        time.sleep(0.02)
    assert "sem resposta" in card.lbl_rotor.text() and card.dial.rotor is None
