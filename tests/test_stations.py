import os
import tempfile

os.environ.setdefault("IC7300_APPDATA", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ic7300 import propagation, stations
from ic7300.stations import Station


def keys(st):
    main, other = stations.actions_for(st)
    return [a.key for a in main], [a.key for a in other]


def test_mode_family():
    assert stations.mode_family("FT8") == "ft8"
    assert stations.mode_family("CW") == "cw"
    assert stations.mode_family("RTTY") == "rtty"
    assert stations.mode_family("JS8") == "js8"
    assert stations.mode_family("WSPR") == "wspr"
    assert stations.mode_family("SSB") == "phone"
    assert stations.mode_family("") == "unknown"


def test_radio_mode():
    assert stations.mode_for_radio("ft8", 14_074_000) == ("USB", True)
    assert stations.mode_for_radio("phone", 7_100_000) == ("LSB", False)
    assert stations.mode_for_radio("phone", 14_200_000) == ("USB", False)
    assert stations.mode_for_radio("phone", 29_600_000, "FM") == ("FM", False)
    assert stations.mode_for_radio("cw", 7_030_000) == ("CW", False)


def test_actions_per_mode():
    main, other = keys(Station("PY2XX", 14_074_000, "FT8"))
    assert main[0] == "page:ft8" and "app:wsjtx" in main
    main, _ = keys(Station("PY2XX", 7_030_000, "CW"))
    assert main[0] == "page:cw"
    assert "page:cw" in main
    main, _ = keys(Station("K1ABC", 14_240_000, "SSB", source="pota", ref="K-0001"))
    assert "pota" in main
    main, other = keys(Station("EA1ABC"))  # só indicativo: só ferramentas de conexão
    assert main == [] and "app:varac" in other and "app:winlink_express" in other and "copy" in other


def test_web_url():
    assert stations.web_url("qrz", "py2xx-1") == "https://www.qrz.com/db/PY2XX"


def test_split_cluster_info():
    assert stations.split_cluster_info("CW 24 dB 22 WPM CQ")[0] == "CW"
    assert stations.split_cluster_info("FT8 -10 dB")[0] == "FT8"
    assert stations.split_cluster_info("up 2 SSB")[0] == "SSB"
    assert stations.split_cluster_info("nada")[0] == ""


def test_parse_wspr():
    payload = {"data": [
        {"time": "2026-11-07 10:00:00", "tx_sign": "DL2NL", "tx_loc": "JO31", "tx_lat": 51.4, "tx_lon": 6.9,
         "frequency": 7040090, "snr": -5, "rx_sign": "KU4BD"},
        {"time": "2026-11-07 09:59:00", "tx_sign": "DL2NL", "tx_loc": "JO31", "tx_lat": 51.4, "tx_lon": 6.9,
         "frequency": 7040090, "snr": -9, "rx_sign": "X"},
        {"tx_sign": "BAD"}]}
    got = stations.parse_wspr(payload)
    assert [s.call for s in got] == ["DL2NL"] and got[0].mode == "WSPR" and got[0].freq == 7040090
    assert "FORMAT JSON" in stations.wspr_query(600, 20)


def test_psk_to_stations():
    reps = [propagation.Report("EA3FF", "JN11cj", "IW9FRA", "JM68", 14075966, "FT8", -15, 100),
            propagation.Report("EA3FF", "JN11cj", "K1ABC", "FN31", 14075966, "FT8", -5, 200),
            propagation.Report("NOGRID", "", "X", "", 14074000, "FT8", 0, 1)]
    got = stations.psk_reports_to_stations(reps)
    assert [s.call for s in got] == ["EA3FF"] and got[0].spotter == "K1ABC"


def test_map_tab_click_and_actions():
    from PySide6 import QtWidgets
    from ic7300.bands import BandPlan
    from ic7300.dxcc import Cty
    from ic7300.ui.maptab import MapTab

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    plan = BandPlan("BR")
    tab = MapTab(plan, Cty())
    got = []
    tab.action_requested.connect(lambda st, key: got.append((st.call, key)))
    tab.set_home(-23.26, -47.3, "PY2XX")
    tab.add_spot("K1ABC", 14_074_000, "FT8 -10 dB")
    assert tab.points["spots"][0].station.mode == "FT8"
    tab.select_station(tab.points["spots"][0].station)
    first = tab.actions_box.itemAt(0).widget()
    first.click()
    assert got == [("K1ABC", "page:ft8")]
    tab.ed_search.setText("PY2XX")
    tab.search_call()
    assert tab.points["busca"] and tab.selected.call == "PY2XX"
    tab._on_stations([Station("DL2NL", 7_040_090, "WSPR", "wspr", 51.4, 6.9)], "wspr")
    assert len(tab.points["wspr"]) == 1
    app.processEvents()


def test_parse_station_list_csv_and_text():
    csv = "Callsign,Frequency (kHz),Mode,Grid,Name\nPY2ABC-10,14101.5,VARA,GG67,Itu\nXX,1,2,3,4\nK1ABC,7101.5,ARDOP,FN31pr,\n"
    got = stations.parse_station_list(csv)
    assert [s.call for s in got] == ["PY2ABC-10", "K1ABC"]
    assert got[0].freq == 14_101_500 and got[0].mode == "VARA" and got[0].lat is not None
    txt = "PY2ABC-10  GG67  14101.5  VARA HF\nlixo sem nada\nK1ABC FN31 7.1015 ARDOP\n"
    got = stations.parse_station_list(txt)
    assert [s.call for s in got] == ["PY2ABC-10", "K1ABC"]
    assert got[0].freq == 14_101_500 and got[0].mode == "VARA HF" and got[1].freq == 7_101_500
    assert stations.mode_family("VARA HF") == "winlink"
    main, _ = keys(got[0])
    assert "app:varac" in main
