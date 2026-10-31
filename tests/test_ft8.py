import numpy as np
import pytest

from ic7300 import ft8

pytestmark = pytest.mark.skipif(not ft8.available(), reason="ft8.dll não compilada (python build_native.py)")


def slot(signals, mode="FT8", noise=0.0, offset_s=0.5, seed=0):
    n = int(ft8.SLOT_SECONDS[mode] * ft8.SAMPLE_RATE)
    buf = np.zeros(n, dtype=np.float32)
    start = int(offset_s * ft8.SAMPLE_RATE)
    for s in signals:
        end = min(n, start + len(s))
        buf[start:end] += s[: end - start]
    buf += np.random.default_rng(seed).normal(0, noise, n).astype(np.float32)
    return buf


@pytest.mark.parametrize("mode", ["FT8", "FT4"])
def test_roundtrip_clean(mode):
    msg = "CQ PY2XX GG66"
    audio = ft8.encode_message(msg, mode, 1200)
    res = ft8.decode_slot(slot([audio * 0.3], mode), mode)
    assert [r.text for r in res] == [msg]
    assert abs(res[0].freq - 1200) <= 6


def test_multiple_stations_with_noise():
    msgs = [("CQ PY2XX GG66", 800), ("PY2XX W1AW -10", 1500), ("W1AW PY2XX R-05", 2100)]
    sigs = [ft8.encode_message(m, "FT8", f) * 0.15 for m, f in msgs]
    res = ft8.decode_slot(slot(sigs, noise=0.05), "FT8")
    assert {r.text for r in res} == {m for m, _ in msgs}


def test_invalid_message():
    with pytest.raises(ValueError):
        ft8.encode_message("ISTO NAO E UMA MENSAGEM FT8 VALIDA DE JEITO NENHUM", "FT8", 1000)
