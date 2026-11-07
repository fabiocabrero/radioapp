import time

import numpy as np

from ic7300 import voice
from ic7300.dsp.vad import VoiceDetector
from ic7300.dsp.voicefx import FS, PRESETS_RX, PRESETS_TX, FxSettings, VoiceFX, process_all

RNG = np.random.default_rng(1)


def speechlike(sec, amp=0.3):
    """Ruído de banda de voz modulado a 4 Hz (como sílabas)."""
    t = np.arange(int(sec * FS)) / FS
    n = RNG.normal(0, 1, len(t)).astype(np.float32)
    spec = np.fft.rfft(n)
    f = np.fft.rfftfreq(len(n), 1 / FS)
    spec[(f < 300) | (f > 3000)] = 0
    band = np.fft.irfft(spec, len(n)).astype(np.float32)
    band /= band.std()
    return (amp * band * (0.5 + 0.5 * np.sin(2 * np.pi * 4 * t)) ** 2).astype(np.float32)


def noise(sec, amp=0.01):
    return RNG.normal(0, amp, int(sec * FS)).astype(np.float32)


def run_blocks(fx, x, block=2400):
    return np.concatenate([fx.process(x[i:i + block]) for i in range(0, len(x), block)])


def test_fx_sem_efeito_preserva_sinal():
    x = speechlike(1.0)
    y = run_blocks(VoiceFX(FxSettings(hp_hz=20)), x)
    assert np.isfinite(y).all() and abs(y).max() <= 0.9 + 1e-6 and y.std() > 0.3 * x.std()


def test_compressao_reduz_dinamica():
    x = np.concatenate([speechlike(1.0, 0.02), speechlike(1.0, 0.5)])
    y_off = run_blocks(VoiceFX(FxSettings(hp_hz=20)), x)
    y_on = run_blocks(VoiceFX(FxSettings(hp_hz=20, comp=80)), x)
    def ratio(y):
        return y[FS:].std() / (y[:FS].std() + 1e-9)
    assert ratio(y_on) < ratio(y_off)


def test_corte_de_graves_e_limite_de_banda():
    t = np.arange(FS) / FS
    low = (0.3 * np.sin(2 * np.pi * 60 * t)).astype(np.float32)
    mid = (0.3 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    s = FxSettings(hp_hz=250, band_on=True, band_lo=300, band_hi=2700)
    assert run_blocks(VoiceFX(s), low)[FS // 2:].std() < 0.2 * run_blocks(VoiceFX(s), mid)[FS // 2:].std()


def test_eco_e_reverb_estendem_o_som():
    x = np.zeros(FS, np.float32)
    x[:2400] = speechlike(0.05, 0.5)
    for s in (FxSettings(hp_hz=20, echo_mix=60, echo_ms=300), FxSettings(hp_hz=20, reverb_mix=60)):
        y = run_blocks(VoiceFX(s), x)
        assert np.isfinite(y).all() and abs(y[int(0.2 * FS):]).max() > 0.02


def test_presets_rodam_e_process_all():
    x = speechlike(0.6)
    for p in list(PRESETS_TX.values()) + list(PRESETS_RX.values()):
        y = run_blocks(VoiceFX(p), x)
        assert np.isfinite(y).all() and abs(y).max() <= 1.0
    assert len(process_all(x, PRESETS_TX["Eco divertido"])) >= len(x)
    assert FxSettings.from_dict(FxSettings(comp=33).to_dict()).comp == 33


def feed_vad(v, x):
    states = []
    for i in range(0, len(x), 960):
        states.append(v.feed(x[i:i + 960]))
    return states


def test_vad_detecta_voz_e_ignora_ruido_e_portadora():
    v = VoiceDetector()
    assert not any(feed_vad(v, noise(3)))
    assert any(feed_vad(v, noise(2) + speechlike(2)))
    v = VoiceDetector()
    t = np.arange(4 * FS) / FS
    carrier = (0.2 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    assert not any(feed_vad(v, noise(1) + 0 * carrier[:FS]) + feed_vad(v, carrier + noise(4)))


def test_cw_duracao():
    assert abs(voice.cw_duration_s("PARIS", 20) - 3.0) < 0.6  # PARIS a 20 wpm = 3 s


def test_gravador_auto_e_manual(tmp_path, monkeypatch):
    monkeypatch.setenv("IC7300_APPDATA", str(tmp_path))
    saved = []
    rec = voice.ConversationRecorder(lambda p, s: saved.append(p))
    rec.set_mode("manual")
    for _ in range(40):
        rec.feed(speechlike(0.1), True)
    rec.set_mode("off")
    assert len(saved) == 1 and saved[0].exists()
    assert len(voice.read_wav(saved[0])) > 3 * FS
    rec.set_mode("auto")
    for _ in range(10):
        rec.feed(noise(0.5), False)
    for _ in range(6):
        rec.feed(speechlike(0.5), True)
    for _ in range(12):
        rec.feed(noise(0.5), False)
    assert len(saved) == 2


def test_mensagens(tmp_path, monkeypatch):
    monkeypatch.setenv("IC7300_APPDATA", str(tmp_path))
    st = voice.MessageStore()
    m1 = st.add_voice("CQ", speechlike(1.0))
    m2 = st.add_cw("CQ CW", "cq de py2xx")
    again = voice.MessageStore()
    assert [m.name for m in again.items] == ["CQ", "CQ CW"] and again.get(m2.id).text == "CQ DE PY2XX"
    assert len(again.samples(m1)) == FS
    again.remove(m1.id)
    assert not (voice.messages_dir() / m1.file).exists() and len(again.items) == 1


class Fake:
    def __init__(self):
        self.events, self.busy, self.mic = [], False, False
        self.status = []

    def make(self, play_len=0.3):
        def play(samples, should_stop):
            self.events.append("play")
            end = time.time() + play_len
            while time.time() < end:
                if should_stop():
                    self.events.append("abort")
                    return False
                time.sleep(0.01)
            return True
        return voice.AutoCaller(lambda on: self.events.append(f"ptt{int(on)}"), play, lambda t: self.events.append("cw:" + t),
                                lambda: self.events.append("stopcw"), lambda: self.busy, lambda: self.mic, self.status.append)


def wait(caller, timeout=8):
    end = time.time() + timeout
    while caller.running and time.time() < end:
        time.sleep(0.02)
    assert not caller.running


def test_chamadas_com_intervalo():
    f = Fake()
    c = f.make()
    msg = voice.Message("a", "voz", "CQ")
    c.start(msg, np.zeros(10, np.float32), voice.CallPlan(gap_s=0.3, clear_s=0.1, max_calls=3))
    wait(c)
    assert c.calls == 3 and f.events.count("play") == 3 and f.events.count("ptt1") == 3 and f.events[-1] == "ptt0"


def test_chamada_interrompida_por_voz_no_rx_e_encerra():
    f = Fake()
    c = f.make(play_len=2.0)
    c.start(voice.Message("a", "voz", "CQ"), np.zeros(10, np.float32), voice.CallPlan(gap_s=5, clear_s=0.1))
    time.sleep(0.5)
    f.busy = True
    wait(c)
    assert "abort" in f.events and f.events[-1] == "ptt0" and c.calls == 1


def test_canal_ocupado_adia_e_retoma():
    f = Fake()
    f.busy = True
    c = f.make()
    plan = voice.CallPlan(gap_s=0.2, clear_s=0.2, max_calls=1, end_on_voice=False)
    c.start(voice.Message("a", "voz", "CQ"), np.zeros(10, np.float32), plan)
    time.sleep(0.5)
    assert "play" not in f.events
    f.busy = False
    wait(c)
    assert f.events.count("play") == 1


def test_resposta_durante_a_escuta_encerra():
    f = Fake()
    c = f.make(play_len=0.1)
    c.start(voice.Message("a", "voz", "CQ"), np.zeros(10, np.float32), voice.CallPlan(gap_s=5, clear_s=0.1))
    time.sleep(0.6)
    f.busy = True
    wait(c)
    assert c.calls == 1


def test_cw_interrompido_pelo_microfone_e_parar():
    f = Fake()
    c = f.make()
    c.start(voice.Message("a", "cw", "CQ", text="CQ CQ CQ DE PY2XX"), None, voice.CallPlan(gap_s=5, clear_s=0.1, wpm=10))
    time.sleep(0.4)
    f.mic = True
    wait(c)
    assert "stopcw" in f.events and any(e.startswith("cw:") for e in f.events)
    f2 = Fake()
    c2 = f2.make(play_len=5)
    c2.start(voice.Message("a", "voz", "CQ"), np.zeros(10, np.float32), voice.CallPlan(gap_s=5, clear_s=0.1))
    time.sleep(0.4)
    c2.stop()
    assert not c2.running and f2.events[-1] == "ptt0"


def test_indicativo_pela_fala():
    from ic7300 import callid
    from ic7300.dxcc import Cty

    cty = Cty()
    assert callid.tokens_to_calls("papa yankee dois xray xray") == ["PY2XX"]
    assert callid.tokens_to_calls("aqui é papa yankee dois xray xray câmbio") == ["PY2XX"]
    assert callid.tokens_to_calls("whiskey one alpha whiskey") == ["W1AW"]
    assert callid.tokens_to_calls("papa yankee two ex ray x ray") == ["PY2XX"]
    assert callid.tokens_to_calls("papa yankee dois xray xray barra portable") == ["PY2XX"]
    assert callid.tokens_to_calls("bom dia a todos") == []
    assert callid.tokens_to_calls("alfa bravo") == []  # sem dígito não é indicativo
    c = callid.score("PY2XX", cty)
    assert c.country and c.confidence > callid.score("PY2XX", None).confidence
    assert callid.score("PY2XX", cty, votes=3).confidence > c.confidence
    assert len(callid.to_16k(np.zeros(4800, np.float32))) == 1600 * 2


def test_listener_com_motor_falso(monkeypatch):
    from ic7300 import callid

    got = []
    lis = callid.CallsignListener(None, got.append)
    lis.handle_text("papa yankee dois xray xray", True)
    assert got and got[0].call == "PY2XX"
    lis.enabled = False
    lis.feed(np.zeros(2400, np.float32), True)  # desligado: não enfileira
    assert lis._q.empty()


def test_ptt_do_operador_suspende_e_pergunta_para_retomar():
    f = Fake()
    asked = []
    holder = {}
    caller = voice.AutoCaller(lambda on: f.events.append(f"ptt{int(on)}"), f.make(play_len=2.0).play,
                              lambda t: None, lambda: None, lambda: False, lambda: False, f.status.append,
                              on_suspended=asked.append)
    holder["c"] = caller
    caller.start(voice.Message("a", "voz", "CQ"), np.zeros(10, np.float32), voice.CallPlan(gap_s=0.2, clear_s=0.1, max_calls=2))
    time.sleep(0.5)
    assert caller.is_own_tx()
    caller.suspend("PTT do operador no rádio")
    time.sleep(0.5)
    assert asked == ["PTT do operador no rádio"] and caller.paused and "abort" in f.events and f.events[-1] == "ptt0"
    n = f.events.count("play")
    time.sleep(0.5)
    assert f.events.count("play") == n  # parado enquanto não responde
    caller.resume()
    wait(caller, 12)
    assert f.events.count("play") >= n + 1 and not caller.paused


def test_ptt_do_operador_adia_chamada_e_encerrar_na_pausa():
    f = Fake()
    state = {"op": True}
    caller = voice.AutoCaller(lambda on: f.events.append(f"ptt{int(on)}"), f.make(0.1).play, lambda t: None, lambda: None,
                              lambda: False, lambda: False, f.status.append, op_ptt=lambda: state["op"])
    caller.start(voice.Message("a", "voz", "CQ"), np.zeros(10, np.float32), voice.CallPlan(gap_s=0.1, clear_s=0.1, max_calls=1))
    time.sleep(0.5)
    assert "play" not in f.events  # operador transmitindo: não chama
    state["op"] = False
    wait(caller)
    assert f.events.count("play") == 1
    f2 = Fake()
    c2 = voice.AutoCaller(lambda on: None, f2.make(2.0).play, lambda t: None, lambda: None, lambda: False, lambda: False, f2.status.append)
    c2.start(voice.Message("a", "voz", "CQ"), np.zeros(10, np.float32), voice.CallPlan(gap_s=5, clear_s=0.1))
    time.sleep(0.4)
    c2.suspend("PTT")
    c2.stop()  # "Encerrar" no diálogo
    assert not c2.running
