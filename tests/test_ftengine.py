import time

import numpy as np
import pytest

from ic7300 import ft8
from ic7300.ftengine import Decimator4, FtEngine, suggest_reply, upsample4

needs_dll = pytest.mark.skipif(not ft8.available(), reason="ft8.dll não compilada")


def test_suggest_reply_flow():
    assert suggest_reply("PY2XX", "CQ W1AW FN31", "GG66ab") == ("W1AW", "W1AW PY2XX GG66")
    assert suggest_reply("PY2XX", "PY2XX W1AW FN31", snr=-8) == ("W1AW", "W1AW PY2XX -08")
    assert suggest_reply("PY2XX", "PY2XX W1AW -12", snr=-5) == ("W1AW", "W1AW PY2XX R-05")
    assert suggest_reply("PY2XX", "PY2XX W1AW R-12") == ("W1AW", "W1AW PY2XX RR73")
    assert suggest_reply("PY2XX", "PY2XX W1AW RR73") == ("W1AW", "W1AW PY2XX 73")
    assert suggest_reply("PY2XX", "K1ABC W1AW -10") is None
    assert suggest_reply("PY2XX", "CQ PY2XX GG66") is None


@needs_dll
def test_engine_decodes_across_slot_boundary_and_resampling():
    got = []
    clock = {"t": 1_000_000_000.0 - (1_000_000_000.0 % 15)}  # início de um slot
    eng = FtEngine(got.extend, lambda m: None, lambda on: None, lambda a: None, clock=lambda: clock["t"])
    sig12 = ft8.encode_message("CQ PY2XX GG66", "FT8", 1000) * 0.3
    n = 15 * 48000
    audio = np.zeros(n, dtype=np.float32)
    up = np.repeat(sig12, 4)
    audio[24000:24000 + len(up)] = up
    audio += np.random.default_rng(0).normal(0, 0.01, n).astype(np.float32)
    for i in range(0, n, 2400):
        eng.feed(audio[i:i + 2400])
        clock["t"] += 2400 / 48000
    clock["t"] += 0.1
    eng.feed(np.zeros(2400, dtype=np.float32))  # cruza a fronteira do slot
    end = time.time() + 5
    while not got and time.time() < end:
        time.sleep(0.05)
    assert [l.decode.text for l in got] == ["CQ PY2XX GG66"]


@needs_dll
def test_engine_transmits_on_matching_slot_only():
    ptt, played = [], []
    clock = {"t": 1_000_000_005.0 - (1_000_000_005.0 % 30) + 29.9}  # fim de um slot ímpar
    eng = FtEngine(lambda l: None, lambda m: None, ptt.append, played.append, clock=lambda: clock["t"])
    eng.tx_enabled, eng.tx_text, eng.tx_even = True, "CQ PY2XX GG66", True
    eng.feed(np.zeros(2400, dtype=np.float32))
    clock["t"] += 0.2  # entra no slot par (0 s)
    eng.feed(np.zeros(2400, dtype=np.float32))
    end = time.time() + 5
    while (not played or len(ptt) < 2) and time.time() < end:
        time.sleep(0.05)
    assert ptt[0] is True and ptt[-1] is False and len(played) == 1
    assert len(played[0]) == 4 * len(ft8.encode_message("CQ PY2XX GG66"))


def test_resamplers_preserve_tone():
    t = np.arange(48000) / 48000
    x = np.sin(2 * np.pi * 1000 * t).astype(np.float32)
    y = Decimator4().process(x)
    spec = np.abs(np.fft.rfft(y[500:]))
    assert abs(np.fft.rfftfreq(len(y[500:]), 1 / 12000)[spec.argmax()] - 1000) < 5
    assert len(upsample4(y)) == 4 * len(y)
