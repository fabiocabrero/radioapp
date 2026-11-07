"""Percorre a janela principal inteira com o simulador: cada tela abre, ações do mapa e sintonia funcionam, sem exceções em slots."""
import os
import sys
import tempfile
import time

os.environ.setdefault("IC7300_APPDATA", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def pump(app, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def test_all_pages_and_actions(monkeypatch):
    from PySide6 import QtWidgets
    from ic7300 import propagation, spacewx, weather
    from ic7300.stations import Station
    from ic7300.ui.appmenu import SECTIONS
    from ic7300.ui.main_window import MainWindow
    from ic7300.ui.spacedata import SpaceData

    def offline(*a, **k):
        raise OSError("offline")

    for mod, name in ((propagation, "fetch_solar"), (propagation, "fetch_psk"), (weather, "fetch_weather"),
                      (spacewx, "fetch_spacewx"), (spacewx, "fetch_drap"), (spacewx, "fetch_aurora")):
        monkeypatch.setattr(mod, name, offline)
    monkeypatch.setattr(SpaceData, "refresh", lambda self: None)

    errors = []
    old_hook = sys.excepthook
    sys.excepthook = lambda t, v, tb: errors.append(f"{t.__name__}: {v}")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    try:
        w = MainWindow()
        w.settings.lat, w.settings.lon, w.settings.callsign = -23.26, -47.30, "PY2XX"
        w.map.set_home(-23.26, -47.30, "PY2XX")
        w.show()
        w.btn_connect.click()
        pump(app, 1.5)
        assert w.radio is not None
        keys = [e.key for _, entries in SECTIONS for e in entries]
        assert set(keys) <= set(w.pages), set(keys) - set(w.pages)
        for key in list(w.pages):
            w.show_page(key)
            pump(app, 0.15)
            assert w._current_page == key
        # clique no mapa -> ações
        st = Station("EA3FF", 14_074_000, "FT8", "psk_band", 41.4, 2.2)
        w.map.add_station("psk_band", st)
        w.map.select_station(st)
        assert "Spain" in w.panel.lbl_loc.text()
        w._station_action(st, "page:ft8")
        assert w._current_page == "ft8"
        pump(app, 0.5)
        assert w.state.freq == 14_074_000 and w.state.data_mode
        w._station_action(Station("PY2ABC", 7_030_000, "CW"), "page:cw")
        pump(app, 0.5)
        assert w.state.freq == 7_030_000 and w.state.mode == "CW"
        w._station_action(st, "copy")
        assert app.clipboard().text() == "EA3FF"
        w._station_action(st, "app:varac")        # VarAC não está instalado: leva à página de programas
        assert w._current_page == "ext"
        w.map.search("GG67")
        assert w.panel.lbl_loc.text()
        w.btn_panel.click()
        assert not w.panel.isVisible()
        w.btn_panel.click()
        w._panic()
        w.close()
        pump(app, 0.3)
    finally:
        sys.excepthook = old_hook
    assert not errors, errors
