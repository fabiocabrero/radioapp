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


def test_data_mode_reply_with_filter_zero_keeps_filter():
    radio = Radio(SimTransport())
    radio.state.filter = 2
    radio._handle(civ.Frame(civ.CONTROLLER_ADDRESS, civ.IC7300_ADDRESS, bytes([civ.CMD_MENU, 0x06, 0x00, 0x00])))
    assert radio.state.filter == 2 and radio.state.data_mode is False
    radio._handle(civ.Frame(civ.CONTROLLER_ADDRESS, civ.IC7300_ADDRESS, bytes([civ.CMD_MENU, 0x06, 0x01, 0x03])))
    assert radio.state.filter == 3 and radio.state.data_mode is True


def test_scope_header_center_and_fixed_modes():
    center = civ.freq_to_bcd(14_074_000) + civ.freq_to_bcd(25_000)

    def line(mode):
        asm = civ.ScopeAssembler()
        out = None
        for seq in range(1, 12):
            body = bytes([0x00, civ.int_to_bcd(seq, 1)[0], civ.int_to_bcd(11, 1)[0]])
            if seq == 1:
                body += bytes([mode]) + center + b"\x00"
            out = asm.feed(body + bytes([10]) * 5) or out
        return out

    c = line(0)   # centrado: centro 14.074.000 e meia-largura 25.000
    assert (c.low_hz, c.high_hz) == (14_049_000, 14_099_000)
    f = line(1)   # fixo: o mesmo par de campos são as bordas
    assert (f.low_hz, f.high_hz) == (14_074_000, 25_000)


def _connected(sim):
    radio = Radio(sim)
    radio.start()
    assert wait_for(lambda: radio.state.connected and radio.state.freq == sim.freq)
    return radio


def test_scope_is_restored_to_what_it_was_on_stop():
    sim = SimTransport()
    sim.scope_mode, sim._span, sim._scope_on, sim.scope_out = 1, 100_000, False, False   # scope "fixo", largura 100 kHz, desligado
    radio = _connected(sim)
    radio.set_scope(True, 25_000)                                                       # o app muda tudo
    assert wait_for(lambda: sim._scope_on and sim.scope_mode == 0 and sim._span == 25_000 and sim.scope_out)
    assert radio.saved_scope == {"on": False, "output": False, "mode": 1, "span": 100_000}
    radio.set_scope_span(50_000)                                                        # e o usuário mexe na largura
    radio.stop()
    assert (sim._scope_on, sim.scope_out, sim.scope_mode, sim._span) == (False, False, 1, 100_000)


def test_scope_that_was_on_stays_on_after_stop():
    sim = SimTransport()
    sim.scope_mode, sim._span, sim._scope_on, sim.scope_out = 0, 50_000, True, True
    radio = _connected(sim)
    radio.set_scope(True, 25_000)
    radio.stop()
    assert (sim._scope_on, sim.scope_out, sim.scope_mode, sim._span) == (True, True, 0, 50_000)


def test_nothing_is_touched_if_scope_was_never_used():
    sim = SimTransport()
    sim.scope_mode, sim._span = 1, 100_000
    radio = _connected(sim)
    radio.stop()
    assert (sim.scope_mode, sim._span, sim._scope_on) == (1, 100_000, False)


def test_frequency_and_mode_restore_is_optional():
    for restore in (False, True):
        sim = SimTransport()
        sim.freq, sim.mode, sim.data, sim.filter = 3_156_000, 2, 0, 2                     # AM, filtro 2
        radio = _connected(sim)
        radio.restore_on_exit = restore
        radio.set_freq(14_074_000)
        radio.set_mode("USB", True, 1)
        assert wait_for(lambda s=sim: s.freq == 14_074_000 and s.data == 1)
        radio.stop()
        if restore:
            assert (sim.freq, sim.mode, sim.data, sim.filter) == (3_156_000, 2, 0, 2)
        else:
            assert (sim.freq, sim.mode, sim.data) == (14_074_000, 1, 1)


def test_unreadable_scope_falls_back_to_turning_output_off():
    class Mute(SimTransport):
        def _handle(self, f):                       # rádio que não responde às leituras do scope
            sub = f.data[:1]
            is_read = (sub in (bytes([civ.SCOPE_ON_OFF]), bytes([civ.SCOPE_WAVE_OUTPUT])) and len(f.data) == 1) or                       (sub in (bytes([civ.SCOPE_MODE]), bytes([civ.SCOPE_SPAN])) and len(f.data) == 2)
            if f.cmd == civ.CMD_SCOPE and is_read:
                return
            super()._handle(f)

    sim = Mute()
    radio = Radio(sim)
    messages = []
    radio.on_message = messages.append       # o aviso sai já ao conectar (leitura do estado inicial)
    radio.start()
    assert wait_for(lambda: radio.state.connected)
    radio.set_scope(True, 25_000)
    assert wait_for(lambda: sim._scope_on)
    radio.stop()
    assert sim._scope_on is False and any("scope" in m for m in messages)
