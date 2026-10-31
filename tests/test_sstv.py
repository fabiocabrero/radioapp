import numpy as np
import pytest

from ic7300.dsp import sstv


def make_image(w=320, h=256):
    y, x = np.mgrid[0:h, 0:w]
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[..., 0] = (x * 255 // (w - 1))                      # R: rampa horizontal
    img[..., 1] = (y * 255 // (h - 1))                      # G: rampa vertical
    img[..., 2] = (128 + 100 * np.sin(x / 25.0) * np.cos(y / 20.0)).astype(np.uint8)  # B: padrão suave
    return img


def decode(audio, chunk=4800, **kw):
    got = {"start": [], "image": None, "lines": 0}
    dec = sstv.SstvDecoder(
        on_start=lambda m: got["start"].append(m.name),
        on_line=lambda y, r: got.__setitem__("lines", got["lines"] + 1),
        on_image=lambda m, img: got.__setitem__("image", img), **kw)
    for i in range(0, len(audio), chunk):
        dec.feed(audio[i:i + chunk])
    dec.feed(np.zeros(sstv.FS, dtype=np.float32))
    return got


def error(a, b):
    return float(np.mean(np.abs(a.astype(float) - b.astype(float))))


def test_line_times_match_published_specs():
    assert round(sstv.MODES["Martin M1"].line_ms, 3) == 446.446
    assert round(sstv.MODES["Martin M2"].line_ms, 3) == 226.798
    assert round(sstv.MODES["Scottie S1"].line_ms, 2) == 428.22
    assert round(sstv.MODES["Scottie S2"].line_ms, 3) == 277.692


@pytest.mark.parametrize("name", ["Martin M2", "Scottie S2"])
def test_roundtrip_clean(name):
    mode = sstv.MODES[name]
    img = make_image()
    audio = sstv.encode(img, mode)
    got = decode(np.concatenate([np.zeros(6000, dtype=np.float32), audio]))
    assert got["start"] == [name] and got["lines"] == 256
    assert got["image"] is not None and error(got["image"], img) < 6


def test_roundtrip_with_noise_and_odd_chunks():
    mode = sstv.MODES["Martin M2"]
    img = make_image()
    audio = sstv.encode(img, mode, amp=0.5)
    audio = audio + np.random.default_rng(2).normal(0, 0.05, len(audio)).astype(np.float32)
    got = decode(np.concatenate([np.zeros(9000, dtype=np.float32), audio]), chunk=1777)
    assert got["image"] is not None and error(got["image"], img) < 18


def test_clock_drift_is_tracked_by_line_sync():
    mode = sstv.MODES["Martin M2"]
    img = make_image()
    audio = sstv.encode(img, mode)
    ratio = 1.0003  # 300 ppm entre as placas de som do transmissor e do receptor
    idx = np.arange(0, len(audio) - 1, ratio)
    stretched = np.interp(idx, np.arange(len(audio)), audio).astype(np.float32)
    got = decode(np.concatenate([np.zeros(6000, dtype=np.float32), stretched]))
    assert got["image"] is not None and error(got["image"], img) < 10


def test_no_header_in_noise_starts_nothing():
    rng = np.random.default_rng(4)
    got = decode(rng.normal(0, 0.1, sstv.FS * 20).astype(np.float32))
    assert got["start"] == [] and got["image"] is None


def test_vis_parity_error_is_rejected():
    mode = sstv.MODES["Martin M2"]
    img = make_image(320, 16)
    audio = sstv.encode(img, sstv.Mode("Martin M2", 41, 320, 16, mode.scan_ms, "martin"))  # VIS 41 não existe
    got = decode(np.concatenate([np.zeros(6000, dtype=np.float32), audio]))
    assert got["start"] == []
