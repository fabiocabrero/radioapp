import time

from ic7300 import civ
from ic7300.bands import BandPlan
from ic7300.dxcc import Cty
from ic7300.geo import distance_bearing, grid_to_latlon, latlon_to_grid, parse_nmea
from ic7300.radio import Radio, SimTransport, s_meter_text


def wait_for(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_bcd_roundtrip():
    assert civ.freq_to_bcd(14_074_000) == bytes([0x00, 0x40, 0x07, 0x14, 0x00])
    assert civ.bcd_to_freq(civ.freq_to_bcd(7_123_456)) == 7_123_456
    assert civ.int_to_bcd(128, 2) == b"\x01\x28"
    assert civ.bcd_to_int(b"\x02\x55") == 255


def test_frame_parser_handles_split_and_noise():
    p = civ.FrameParser()
    raw = civ.build(0xE0, 0x94, b"\x03\x00\x40\x07\x14\x00")
    assert p.feed(b"\x01\x02" + raw[:5]) == []
    frames = p.feed(raw[5:] + raw)
    assert len(frames) == 2 and frames[0].cmd == 0x03


def test_radio_with_simulator():
    sim = SimTransport()
    radio = Radio(sim)
    lines = []
    radio.on_scope = lines.append
    radio.start()
    try:
        assert wait_for(lambda: radio.state.connected and radio.state.freq == 14_074_000)
        radio.set_freq(7_040_000)
        radio.set_mode("CW", False)
        assert wait_for(lambda: sim.freq == 7_040_000 and sim.mode == 3)
        radio.set_mode("USB", True)
        assert wait_for(lambda: sim.data == 1)
        radio.set_ptt(True)
        assert wait_for(lambda: sim.ptt)
        radio.set_ptt(False)
        radio.send_cw("CQ DE PY2XX")
        assert wait_for(lambda: sim.sent_cw == ["CQ DE PY2XX"])
        radio.set_scope(True, 25000)
        assert wait_for(lambda: len(lines) >= 2, 5)
        assert len(lines[0].values) == civ.SCOPE_POINTS
        assert lines[0].high_hz - lines[0].low_hz == 50000
    finally:
        radio.stop()


def test_geo():
    lat, lon = grid_to_latlon("GG67")
    assert latlon_to_grid(lat, lon, 4).upper() == "GG67"
    d, b = distance_bearing(-23.26, -47.30, 40.7, -74.0)
    assert 7500 < d < 8000 and 0 < b < 360
    fix = parse_nmea("$GPGGA,123519,2315.58,S,04717.95,W,1,08,0.9,545.4,M,46.9,M,,*" +
                     format(__import__("functools").reduce(
                         lambda a, c: a ^ ord(c), "GPGGA,123519,2315.58,S,04717.95,W,1,08,0.9,545.4,M,46.9,M,,", 0), "02X"))
    assert fix and abs(fix[0] + 23.2597) < 0.01 and abs(fix[1] + 47.2992) < 0.01


def test_dxcc_and_bands():
    cty = Cty()
    assert cty.lookup("PY2XX").name == "Brazil"
    assert cty.lookup("W1AW").name == "United States"
    assert cty.lookup("W1AW/KH6").name == "Hawaii"
    assert cty.lookup("PY2XX/P").name == "Brazil"
    plan = BandPlan()
    assert plan.band_for(14_074_000) == "20m"
    assert plan.suggest_mode(14_074_000) == ("USB", True)
    assert plan.suggest_mode(7_030_000) == ("CW", False)
    assert plan.suggest_mode(7_150_000) == ("LSB", False)
    assert s_meter_text(120) == "S9"
