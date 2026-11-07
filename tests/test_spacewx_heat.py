import os
import tempfile
from datetime import datetime, timezone

import numpy as np

os.environ.setdefault("IC7300_APPDATA", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ic7300 import hamqth, heatmap, satellites, spacewx, weather


def test_parse_kp_and_alerts():
    kp, when, series = spacewx.parse_kp([{"time_tag": "2026-11-07T03:00:00", "Kp": 2.0},
                                         {"time_tag": "2026-11-07T06:00:00", "Kp": "3.33"}, {"bad": 1}])
    assert kp == 3.33 and when == "2026-11-07 06:00" and series == [2.0, 3.33]
    rows = [{"product_id": "K04W", "issue_datetime": "2026-11-07 00:56:27.930",
             "message": "Space Weather Message Code: WARK04\r\nSerial Number: 5448\r\nWARNING: Geomagnetic K-index of 4 expected\r\n"},
            {"product_id": "X", "issue_datetime": "2026-11-06 10:00:00.0", "message": "texto livre"}]
    al = spacewx.parse_alerts(rows)
    assert al[0].severity == "warning" and "K-index of 4" in al[0].headline and al[0].issued == "2026-11-07 00:56"
    assert al[1].severity == "other"


def test_parse_drap_and_aurora():
    txt = ("# DRAP\n#\n      -178 -174\n-----------\n  89 |  0.0  0.0\n  87 |  2.5  3.0\n")
    lats, lons, z = spacewx.parse_drap(txt)
    assert list(lats) == [87.0, 89.0] and list(lons) == [-178.0, -174.0] and z[0, 1] == 3.0
    g, t = spacewx.parse_aurora({"Forecast Time": "T", "coordinates": [[10, 60, 21], [359, -90, 5], [400, 0, 9]]})
    assert g.shape == (181, 360) and g[150, 10] == 21 and g[0, 359] == 5 and t == "T"


def test_weather_parse():
    w = weather.parse_weather({"current": {"temperature_2m": 28.2, "relative_humidity_2m": 72, "cloud_cover": 1,
                                           "wind_speed_10m": 9.0, "precipitation": 0.0, "weather_code": 95,
                                           "pressure_msl": 1012.0}})
    assert w.stormy and "trovoada" in w.summary() and "ruído" in w.summary()


def test_hamqth_parse():
    sess = '<?xml version="1.0"?><HamQTH xmlns="https://www.hamqth.com"><session><session_id>abc123</session_id></session></HamQTH>'
    assert hamqth.parse_session(sess) == "abc123"
    rec = ('<HamQTH xmlns="https://www.hamqth.com"><search><callsign>OK2CQR</callsign><adr_name>Petr</adr_name>'
           '<qth>Brno</qth><grid>JN89</grid><lotw>Y</lotw></search></HamQTH>')
    assert hamqth.parse_callsign(rec)["qth"] == "Brno"
    err = '<HamQTH xmlns="https://www.hamqth.com"><session><error>Callsign not found</error></session></HamQTH>'
    try:
        hamqth.parse_callsign(err)
        assert False
    except hamqth.HamQTHError as exc:
        assert "not found" in str(exc)
    assert not hamqth.HamQTH().configured


def test_heatmap_behaviour():
    home = (-23.26, -47.3)
    noon = datetime(2026, 11, 7, 15, 0, tzinfo=timezone.utc)
    night = datetime(2026, 11, 7, 3, 0, tzinfo=timezone.utc)
    la, lo, z14 = heatmap.estimate_grid(home, 14.2e6, 140, 2, noon)
    assert z14.shape == (len(la), len(lo)) and 0 <= z14.min() and z14.max() <= 1
    assert heatmap.sample(la, lo, z14, 48, 10) > 0.5            # 20 m de dia: Europa aberta
    assert heatmap.sample(la, lo, z14, -20, -44) < 0.2           # 20 m perto: zona de silêncio
    la, lo, z28n = heatmap.estimate_grid(home, 28.4e6, 140, 2, night)
    assert heatmap.sample(la, lo, z28n, 48, 10) < 0.05           # 10 m de noite: fechada
    la, lo, z7n = heatmap.estimate_grid(home, 3.6e6, 140, 2, night)
    assert heatmap.sample(la, lo, z7n, -20, -44) > 0.5           # 80 m de noite: NVIS abre (acima da foF2 fecha)
    # Kp alto e absorção D-RAP reduzem a chance
    _, _, zk = heatmap.estimate_grid(home, 21.2e6, 140, 8, noon)
    _, _, z0 = heatmap.estimate_grid(home, 21.2e6, 140, 2, noon)
    assert zk.sum() < z0.sum()
    haf = (np.arange(-89, 90, 2.0), np.arange(-178, 179, 4.0), np.full((90, 90), 60.0, dtype=np.float32))
    _, _, zh = heatmap.estimate_grid(home, 14.2e6, 140, 2, noon, haf)
    assert zh.sum() < z14.sum() * 0.3
    assert heatmap.classify(0.9) == "boa" and heatmap.classify(0.01) == "fechada"
    assert heatmap.colorize(z14).shape == z14.shape + (4,)


def test_satellites_basic():
    iss = {"OBJECT_NAME": "ISS (ZARYA)", "NORAD_CAT_ID": 25544, "EPOCH": "2026-11-06T12:00:00", "MEAN_MOTION": 15.5,
           "ECCENTRICITY": 0.0005, "INCLINATION": 51.64, "RA_OF_ASC_NODE": 100.0, "ARG_OF_PERICENTER": 80.0,
           "MEAN_ANOMALY": 10.0}
    sat = satellites.parse_gp([iss, {"bad": 1}])[0]
    when = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
    lat, lon, alt = satellites.subpoint(sat, when)
    assert abs(lat) <= 51.7 and -180 <= lon <= 180 and 330 < alt < 450
    el, az = satellites.look_angles(sat, when, lat, lon)       # visto do ponto sob o satélite: quase no zênite
    assert el > 80
    passes = satellites.next_passes(sat, -23.26, -47.3, start=when, hours=24)
    assert passes and all(p.max_el >= 10 and p.aos < p.tca < p.los for p in passes)
    # Doppler: aproximando (range rate < 0) sobe a frequência, afastando desce
    p = passes[0]
    assert satellites.doppler(145.8e6, satellites.range_rate(sat, p.aos, -23.26, -47.3)) > 145.8e6
    assert satellites.doppler(145.8e6, satellites.range_rate(sat, p.los, -23.26, -47.3)) < 145.8e6


def _offline(monkeypatch):
    """Sem rede e sem threads soltas: evita travar o Qt em testes seguintes."""
    from ic7300 import propagation as prop, weather as wx
    from ic7300.ui.spacedata import SpaceData

    def boom(*a, **k):
        raise OSError("offline")

    monkeypatch.setattr(prop, "fetch_solar", boom)
    monkeypatch.setattr(wx, "fetch_weather", boom)
    monkeypatch.setattr(SpaceData, "refresh", lambda self: None)


def test_panel_and_map_heat_smoke(monkeypatch):
    import time
    from PySide6 import QtWidgets
    _offline(monkeypatch)
    from ic7300.bands import BandPlan
    from ic7300.dxcc import Cty
    from ic7300.settings import Settings
    from ic7300.stations import Station
    from ic7300.ui.contextpanel import ContextPanel
    from ic7300.ui.maptab import MapTab
    from ic7300.ui.spacedata import SpaceData
    from ic7300 import propagation

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    plan, cty, space = BandPlan("BR"), Cty(), SpaceData()
    space.set_solar(propagation.SolarData(sfi=140, k_index=2, bands={("30m-20m", "day"): "Good", ("30m-20m", "night"): "Fair"}))
    home = (-23.26, -47.3)
    panel = ContextPanel(Settings(), cty, plan, space, lambda: 14_074_000, lambda: home)
    tab = MapTab(plan, cty, space)
    tab.set_home(*home, "PY2XX")
    tab.dial = lambda: 14_074_000
    tab._on_solar(space.solar)
    tab.cb_heat.setCurrentIndex(1)           # propagação estimada
    assert tab.heatimg.image is not None
    tab.search("GG67")
    assert tab.selected.call == "Grid GG67"
    panel.set_station(Station("EA3FF", 14_074_000, "FT8", "psk_band", 41.4, 2.2))
    assert "Espanha" in panel.lbl_loc.text() or "Spain" in panel.lbl_loc.text()
    assert "Hora local" in panel.lbl_loc.text() and "FT8" in panel.lbl_op.text()
    assert "14.074" in panel.lbl_band.text() and "20m" in panel.lbl_band.text()
    time.sleep(0.3)
    app.processEvents()
    for t in (tab.timer, tab.rbn_timer, panel.timer, space.timer):
        t.stop()
    panel.deleteLater()
    tab.deleteLater()
    app.processEvents()


def test_satnogs_parse_and_range():
    from ic7300 import satnogs
    rows = [{"norad_cat_id": 7530, "description": "Mode A", "type": "Transponder", "mode": "USB", "uplink_low": 145850000,
             "uplink_high": 145950000, "downlink_low": 29400000, "downlink_high": 29500000, "invert": True},
            {"norad_cat_id": 25544, "description": "Voice", "type": "Transceiver", "mode": "FM", "uplink_low": 145990000,
             "uplink_high": None, "downlink_low": 437800000, "downlink_high": 437800000},
            {"bad": 1}]
    tx = satnogs.parse_transmitters(rows)
    assert len(tx) == 2 and tx[0].rx_in_range and not tx[1].rx_in_range
    assert tx[0].down_center == 29_450_000 and tx[1].up_center == 145_990_000
    assert satnogs.by_norad(tx)[7530][0].invert
    assert satnogs.radio_mode("FM") == ("FM", False) and satnogs.radio_mode("BPSK") == ("USB", True)


def test_satellites_tab_smoke(monkeypatch):
    import time
    from PySide6 import QtWidgets
    from ic7300 import satellites, satnogs
    from ic7300.ui.satellitestab import SatellitesTab

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    iss = {"OBJECT_NAME": "ISS (ZARYA)", "NORAD_CAT_ID": 25544, "EPOCH": datetime.now(timezone.utc).isoformat()[:19],
           "MEAN_MOTION": 15.5, "ECCENTRICITY": 0.0005, "INCLINATION": 51.64, "RA_OF_ASC_NODE": 100.0,
           "ARG_OF_PERICENTER": 80.0, "MEAN_ANOMALY": 10.0}
    monkeypatch.setattr(satellites, "fetch_sats", lambda *a, **k: satellites.parse_gp([iss]))
    monkeypatch.setattr(satnogs, "fetch_transmitters", lambda *a, **k: satnogs.parse_transmitters(
        [{"norad_cat_id": 25544, "description": "Voice", "type": "Transceiver", "mode": "FM", "uplink_low": 145990000,
          "downlink_low": 437800000, "downlink_high": 437800000}]))
    tab = SatellitesTab(lambda: (-23.26, -47.3))
    tab.sp_el.setValue(5)
    tab.cb_hours.setCurrentIndex(3)
    got = []
    tab.message.connect(got.append)
    tab.refresh()
    for _ in range(60):
        app.processEvents()
        time.sleep(0.05)
        if tab.shown:
            break
    assert tab.shown and tab.table.rowCount() == len(tab.shown)
    assert tab.tx_table.rowCount() == 1 and "Doppler" in tab.lbl_detail.text()
    tab._tune()                       # downlink em UHF: o IC-7300 não ouve, deve avisar
    assert got and "não recebe" in got[-1]
    tab.chk_rx.setChecked(True)       # filtro "só o que o IC-7300 ouve" esvazia a lista
    assert tab.table.rowCount() == 0
    tab.timer.stop()
    tab.deleteLater()
    app.processEvents()
