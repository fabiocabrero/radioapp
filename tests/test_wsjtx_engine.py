import subprocess
import time
from pathlib import Path

import numpy as np
import pytest

from ic7300 import wsjtx_engine as wx

BIN = wx.find_bin()
needs_wsjtx = pytest.mark.skipif(BIN is None, reason="WSJT-X não instalado")


def test_parsers():
    out = ("0000 -23  0.1 1500 :  CQ PY2XX GG66                         q0 \n"
           "0001 -12  0.0 1500 `  CQ PY2XX GG66                                   \n"
           "<DecodeFinished>   0   1     1000\n")
    d = wx.parse_jt9(out, "Q65", 0)
    assert [(x.snr, x.dt, x.freq, x.text, x.extra) for x in d] == [
        (-23, 0.1, 1500, "CQ PY2XX GG66", "q0"), (-12, 0.0, 1500, "CQ PY2XX GG66", "")]
    w = wx.parse_wsprd("2340 -24  0.5  14.0971620  0  PY2XX GG66 37\nlixo\n", 0)
    assert w[0].text == "PY2XX GG66 37" and w[0].freq == 14_097_162 and w[0].snr == -24


def _simulate(tmp_path, cmd, name_prefix):
    subprocess.run(cmd, cwd=tmp_path, capture_output=True, timeout=120)
    return sorted(Path(tmp_path).glob("*.wav"))


def _read_wav(path):
    import wave

    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768


@needs_wsjtx
def test_fst4_and_q65_decode_signals_from_wsjtx_simulators(tmp_path):
    fst = _simulate(tmp_path, [str(BIN / "fst4sim.exe"), "CQ PY2XX GG66", "60", "1500", "0.0", "0.1", "1.0", "1", "-12", "F"], "f")
    assert fst
    got = wx.decode("FST4", _read_wav(fst[0]), 0, 60, BIN)
    assert [d.text for d in got] == ["CQ PY2XX GG66"] and abs(got[0].freq - 1500) <= 2
    for f in fst:
        f.unlink()
    q65 = _simulate(tmp_path, [str(BIN / "q65sim.exe"), "CQ PY2XX GG66", "A", "1500", "0.0", "0.0", "0.0", "1", "60", "1", "1", "-22"], "q")
    assert q65
    got = wx.decode("Q65", _read_wav(q65[0]), 0, 60, BIN)
    assert [d.text for d in got] == ["CQ PY2XX GG66"]


@needs_wsjtx
def test_noise_decodes_nothing_and_wsprd_runs(tmp_path):
    noise = np.random.default_rng(1).normal(0, 0.1, 12000 * 120).astype(np.float32)
    assert wx.decode("WSPR", noise, 0, 120, BIN, dial_mhz=14.0956) == []
    assert wx.decode("FST4", noise[:12000 * 60], 0, 60, BIN) == []


@needs_wsjtx
def test_slot_engine_aligns_to_clock_and_decodes(tmp_path):
    fst = _simulate(tmp_path, [str(BIN / "fst4sim.exe"), "CQ PY2XX GG66", "60", "1500", "0.0", "0.1", "1.0", "1", "-10", "F"], "f")
    sig12 = _read_wav(fst[0])
    audio48 = np.repeat(sig12, 4)  # 12 -> 48 kHz (o decimador filtra as imagens)
    got = []
    status = []
    clock = {"t": 1_000_000_000.0 - (1_000_000_000.0 % 60)}
    eng = wx.SlotEngine(got.extend, status.append, clock=lambda: clock["t"])
    eng.bin_dir, eng.enabled = BIN, True
    eng.set_mode("FST4", 60)
    for i in range(0, len(audio48), 4800):
        eng.feed(audio48[i:i + 4800])
        clock["t"] += 4800 / 48000
    clock["t"] += 0.2
    eng.feed(np.zeros(4800, dtype=np.float32))  # cruza a fronteira do slot
    end = time.time() + 60
    while not got and time.time() < end:
        time.sleep(0.2)
    assert [d.text for d in got] == ["CQ PY2XX GG66"]
    assert got[0].start % 60 == 0  # o slot decodificado começa num minuto cheio UTC
