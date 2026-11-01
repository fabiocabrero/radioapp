import socket
import time

import pytest

from ic7300.radio import Radio, SimTransport
from ic7300.rigctl import RigctlServer


class Client:
    def __init__(self, port):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=3)
        self.f = self.s.makefile("rwb", buffering=0)

    def send(self, text):
        self.f.write((text + "\n").encode())

    def line(self):
        return self.f.readline().decode().rstrip("\n")

    def ask(self, text, n=1):
        self.send(text)
        return [self.line() for _ in range(n)]


def read_range_list(c):
    count = 0
    while True:
        fields = c.line().split()
        assert len(fields) == 7
        if float(fields[1]) == 0:
            return count
        count += 1


@pytest.fixture()
def rig():
    sim = SimTransport()
    radio = Radio(sim)
    radio.start()
    end = time.time() + 3
    while not radio.state.connected and time.time() < end:
        time.sleep(0.02)
    srv = RigctlServer(lambda: radio, lambda: radio.state, port=0)
    srv.start()
    yield sim, radio, srv
    srv.stop()
    radio.stop()


def test_dump_state_matches_hamlib_client_parser(rig):
    _, _, srv = rig
    c = Client(srv.port)
    assert c.ask("\\chk_vfo") == ["0"]
    c.send("\\dump_state")
    assert c.line() == "0"          # versão do protocolo (0 = sem bloco chave=valor)
    c.line()                        # modelo
    assert c.line() == "0"          # região ITU
    assert read_range_list(c) >= 1  # RX
    assert read_range_list(c) >= 1  # TX
    for _ in range(2):              # passos e filtros: 2 campos até "0 0"
        while True:
            f = c.line().split()
            assert len(f) == 2
            if f == ["0", "0"]:
                break
    for _ in range(4 + 2 + 4 + 2):  # rit, xit, ifshift, announces, preamp, att, funcs, levels, parms
        c.line()
    assert c.ask("f")[0].isdigit()  # o servidor segue em sincronia depois do dump


def test_wsjtx_style_session(rig):
    sim, radio, srv = rig
    c = Client(srv.port)
    assert c.ask("F 14074000") == ["RPRT 0"]
    end = time.time() + 3
    while sim.freq != 14_074_000 and time.time() < end:
        time.sleep(0.02)
    assert sim.freq == 14_074_000
    assert c.ask("f") == ["14074000"]
    assert c.ask("M PKTUSB 0") == ["RPRT 0"]
    end = time.time() + 3
    while not (sim.mode == 1 and sim.data == 1) and time.time() < end:
        time.sleep(0.02)
    assert sim.mode == 1 and sim.data == 1
    assert c.ask("m", 2) == ["PKTUSB", "2400"]
    assert c.ask("T 1") == ["RPRT 0"]
    end = time.time() + 3
    while not sim.ptt and time.time() < end:
        time.sleep(0.02)
    assert sim.ptt
    assert c.ask("T 0") == ["RPRT 0"]
    assert c.ask("s", 2) == ["0", "VFOA"]
    assert c.ask("f VFOA") == ["14074000"]
    assert c.ask("l STRENGTH")[0].lstrip("-").isdigit()
    assert c.ask(r"\get_lock_mode", 2) == ["0", "RPRT 0"]  # o cliente Hamlib lê duas linhas
    assert c.ask("xyz") == ["RPRT -4"]


def test_no_radio_connected():
    srv = RigctlServer(lambda: None, lambda: None, port=0)
    srv.start()
    try:
        c = Client(srv.port)
        assert c.ask("f") == ["RPRT -6"]
    finally:
        srv.stop()
