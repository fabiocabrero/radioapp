"""Controle do IC-7300 por CI-V (serial USB) e simulador para testes sem rádio."""
from __future__ import annotations

import math
import queue
import random
import threading
import time
from dataclasses import dataclass, field, replace
from typing import Callable, Optional, Protocol

from . import civ


class Transport(Protocol):
    def read(self, size: int = 1) -> bytes: ...
    def write(self, data: bytes) -> None: ...
    def close(self) -> None: ...


class SerialTransport:
    def __init__(self, port: str, baud: int = 115200) -> None:
        import serial

        self._ser = serial.Serial(port, baud, timeout=0.05, write_timeout=1)
        # Evita acionar PTT/KEY pelas linhas de controle da porta USB
        self._ser.dtr = False
        self._ser.rts = False

    def read(self, size: int = 1) -> bytes:
        return self._ser.read(max(size, self._ser.in_waiting))

    def write(self, data: bytes) -> None:
        self._ser.write(data)

    def close(self) -> None:
        self._ser.close()


def list_serial_ports() -> list[tuple[str, str]]:
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [(p.device, p.description) for p in list_ports.comports()]


@dataclass
class RadioState:
    connected: bool = False
    freq: int = 14_074_000
    mode: str = "USB"
    data_mode: bool = False
    filter: int = 1
    ptt: bool = False
    s_meter: int = 0
    power: int = 0
    swr: int = 0
    levels: dict = field(default_factory=dict)


def s_meter_text(raw: int) -> str:
    if raw <= 120:
        return f"S{round(raw / 120 * 9)}"
    return f"S9+{round((raw - 120) / 121 * 60)}"


def power_watts(raw: int) -> float:
    # 0 = 0 %, 143 = 50 %, 213 = 100 % (potência de saída, 100 W)
    if raw <= 143:
        return raw / 143 * 50
    return 50 + (raw - 143) / 70 * 50


def swr_value(raw: int) -> float:
    points = [(0, 1.0), (48, 1.5), (80, 2.0), (120, 3.0), (255, 6.0)]
    for (r0, v0), (r1, v1) in zip(points, points[1:]):
        if raw <= r1:
            return v0 + (v1 - v0) * (raw - r0) / (r1 - r0)
    return points[-1][1]


class Radio:
    """Mantém o estado do rádio e traduz comandos de alto nível em quadros CI-V."""

    def __init__(self, transport: Transport, address: int = civ.IC7300_ADDRESS,
                 controller: int = civ.CONTROLLER_ADDRESS) -> None:
        self.transport = transport
        self.address = address
        self.controller = controller
        self.state = RadioState()
        self.on_state: Callable[[RadioState], None] = lambda s: None
        self.on_scope: Callable[[civ.ScopeLine], None] = lambda s: None
        self.on_message: Callable[[str], None] = lambda m: None
        self._parser = civ.FrameParser()
        self._scope = civ.ScopeAssembler()
        self._tx_lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._last_reply = 0.0
        self._scope_on = False

    # ---- ciclo de vida ----
    def start(self) -> None:
        self._stop.clear()
        for target in (self._read_loop, self._poll_loop):
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self._threads.append(t)
        self._send(bytes([civ.CMD_READ_ID, 0x00]))

    def stop(self) -> None:
        self._stop.set()
        if self._scope_on:
            try:
                self.set_scope(False)
            except Exception:
                pass
        for t in self._threads:
            t.join(timeout=1)
        self._threads.clear()
        self.transport.close()
        self.state.connected = False
        self.on_state(replace(self.state))

    # ---- envio ----
    def _send(self, payload: bytes) -> None:
        with self._tx_lock:
            self.transport.write(civ.build(self.address, self.controller, payload))
            time.sleep(0.012)

    # ---- comandos de alto nível ----
    def set_freq(self, hz: int) -> None:
        self._send(bytes([civ.CMD_SET_FREQ]) + civ.freq_to_bcd(hz))
        self.state.freq = hz
        self.on_state(replace(self.state))

    def set_mode(self, mode: str, data: bool = False, filt: int = 1) -> None:
        filt = min(3, max(1, filt))  # o IC-7300 só aceita FIL1 a FIL3
        self._send(bytes([civ.CMD_SET_MODE, civ.MODE_CODES[mode], filt]))
        self._send(bytes([civ.CMD_MENU, 0x06, 1 if data else 0, filt]))
        self.state.mode, self.state.data_mode, self.state.filter = mode, data, filt
        self.on_state(replace(self.state))

    def set_ptt(self, on: bool) -> None:
        self._send(bytes([civ.CMD_TRANSMIT, 0x00, 1 if on else 0]))

    def set_level(self, name: str, value: int) -> None:
        self._send(bytes([civ.CMD_LEVEL, civ.LEVELS[name]]) + civ.int_to_bcd(value, 2))
        self.state.levels[name] = value  # vale já, até a próxima leitura confirmar

    def set_func(self, name: str, value: int) -> None:
        self._send(bytes([civ.CMD_FUNC, civ.FUNCS[name], value]))

    def send_cw(self, text: str) -> None:
        text = text.upper().encode("ascii", "ignore")
        for i in range(0, len(text), 30):
            self._send(bytes([civ.CMD_SEND_CW]) + text[i:i + 30])

    def stop_cw(self) -> None:
        self._send(bytes([civ.CMD_SEND_CW, 0xFF]))

    def set_scope(self, on: bool, span_hz: Optional[int] = None) -> None:
        self._send(bytes([civ.CMD_SCOPE, civ.SCOPE_ON_OFF, 1 if on else 0]))
        if on:
            self._send(bytes([civ.CMD_SCOPE, civ.SCOPE_WAVE_OUTPUT, 1]))
            self._send(bytes([civ.CMD_SCOPE, civ.SCOPE_MODE, 0x00, 0x00]))  # modo centrado
            if span_hz:
                self.set_scope_span(span_hz)
        self._scope_on = on

    def set_scope_span(self, span_hz: int) -> None:
        # Largura em modo centrado: valor em Hz de meia-largura, formato BCD de frequência
        self._send(bytes([civ.CMD_SCOPE, civ.SCOPE_SPAN, 0x00]) + civ.freq_to_bcd(span_hz))

    # ---- recepção ----
    def _read_loop(self) -> None:
        while not self._stop.is_set():
            try:
                chunk = self.transport.read(64)
            except Exception as exc:  # porta desconectada
                self.on_message(f"Erro de leitura: {exc}")
                break
            for frame in self._parser.feed(chunk):
                if frame.src == self.controller:
                    continue  # eco
                self._handle(frame)

    def _poll_loop(self) -> None:
        tick = 0
        while not self._stop.is_set():
            try:
                self._send(bytes([civ.CMD_READ_FREQ]))
                self._send(bytes([civ.CMD_METER, civ.METERS["s"]]))
                if tick % 3 == 0:
                    self._send(bytes([civ.CMD_READ_MODE]))
                    self._send(bytes([civ.CMD_MENU, 0x06]))
                    self._send(bytes([civ.CMD_TRANSMIT, 0x00]))
                if self.state.ptt or tick % 3 == 1:
                    self._send(bytes([civ.CMD_METER, civ.METERS["po"]]))
                    self._send(bytes([civ.CMD_METER, civ.METERS["swr"]]))
                if tick % 20 == 0:
                    for name in ("af", "rf", "sql", "power", "key_speed"):
                        self._send(bytes([civ.CMD_LEVEL, civ.LEVELS[name]]))
            except Exception as exc:
                self.on_message(f"Erro de escrita: {exc}")
                break
            tick += 1
            self._stop.wait(0.12)
            alive = time.time() - self._last_reply < 2.0
            if alive != self.state.connected:
                self.state.connected = alive
                self.on_state(replace(self.state))

    def _handle(self, frame: civ.Frame) -> None:
        self._last_reply = time.time()
        cmd, data, st = frame.cmd, frame.data, self.state
        changed = True
        if cmd == civ.ACK or cmd == civ.NAK:
            if cmd == civ.NAK:
                self.on_message("Rádio recusou um comando (NAK)")
            return
        if cmd in (civ.CMD_FREQ_NOTIFY, civ.CMD_READ_FREQ) and len(data) >= 5:
            st.freq = civ.bcd_to_freq(data)
        elif cmd in (civ.CMD_MODE_NOTIFY, civ.CMD_READ_MODE) and data:
            st.mode = civ.MODES.get(data[0], st.mode)
            if len(data) > 1:
                st.filter = data[1]
        elif cmd == civ.CMD_MENU and len(data) >= 3 and data[0] == 0x06:
            st.data_mode = bool(data[1])
            if 1 <= data[2] <= 3:  # com DATA desligado o IC-7300 responde filtro 00: mantém o filtro já conhecido
                st.filter = data[2]
        elif cmd == civ.CMD_METER and len(data) >= 3:
            raw = civ.bcd_to_int(data[1:3])
            key = {civ.METERS["s"]: "s_meter", civ.METERS["po"]: "power", civ.METERS["swr"]: "swr"}.get(data[0])
            if key:
                setattr(st, key, raw)
            else:
                changed = False
        elif cmd == civ.CMD_LEVEL and len(data) >= 3:
            name = next((n for n, c in civ.LEVELS.items() if c == data[0]), None)
            if name:
                st.levels[name] = civ.bcd_to_int(data[1:3])
        elif cmd == civ.CMD_TRANSMIT and len(data) >= 2 and data[0] == 0x00:
            st.ptt = bool(data[1])
        elif cmd == civ.CMD_SCOPE and data and data[0] == civ.SCOPE_WAVE:
            line = self._scope.feed(data[1:])
            if line:
                self.on_scope(line)
            return
        else:
            changed = False
        if changed:
            self.on_state(replace(st, levels=dict(st.levels)))


class SimTransport:
    """IC-7300 virtual: responde ao CI-V e gera scope com sinais fictícios."""

    def __init__(self, address: int = civ.IC7300_ADDRESS) -> None:
        self.address = address
        self._out: queue.Queue[bytes] = queue.Queue()
        self._parser = civ.FrameParser()
        self._closed = threading.Event()
        self.freq, self.mode, self.data, self.filter, self.ptt = 14_074_000, 1, 0, 1, False
        self.levels = {"af": 80, "rf": 255, "sql": 0, "power": 128, "key_speed": 100}
        self._scope_on = False
        self._span = 25_000
        self._t0 = time.time()
        self.sent_cw: list[str] = []
        threading.Thread(target=self._scope_loop, daemon=True).start()

    def read(self, size: int = 1) -> bytes:
        try:
            return self._out.get(timeout=0.05)
        except queue.Empty:
            return b""

    def close(self) -> None:
        self._closed.set()

    def _reply(self, payload: bytes, dst: int = civ.CONTROLLER_ADDRESS) -> None:
        self._out.put(civ.build(dst, self.address, payload))

    def write(self, data: bytes) -> None:
        for f in self._parser.feed(data):
            if f.dst == self.address:
                self._handle(f)

    def _handle(self, f: civ.Frame) -> None:
        cmd, d = f.cmd, f.data
        ack = bytes([civ.ACK])
        if cmd == civ.CMD_READ_FREQ:
            self._reply(bytes([civ.CMD_READ_FREQ]) + civ.freq_to_bcd(self.freq))
        elif cmd == civ.CMD_READ_MODE:
            self._reply(bytes([civ.CMD_READ_MODE, self.mode, self.filter]))
        elif cmd == civ.CMD_SET_FREQ:
            self.freq = civ.bcd_to_freq(d)
            self._reply(ack)
        elif cmd == civ.CMD_SET_MODE:
            self.mode, self.filter = d[0], d[1] if len(d) > 1 else 1
            self._reply(ack)
        elif cmd == civ.CMD_MENU and d[:1] == b"\x06":
            if len(d) >= 3:
                self.data, self.filter = d[1], d[2]
                self._reply(ack)
            else:
                self._reply(bytes([civ.CMD_MENU, 0x06, self.data, self.filter]))
        elif cmd == civ.CMD_TRANSMIT and d[:1] == b"\x00":
            if len(d) >= 2:
                self.ptt = bool(d[1])
                self._reply(ack)
            else:
                self._reply(bytes([civ.CMD_TRANSMIT, 0x00, int(self.ptt)]))
        elif cmd == civ.CMD_METER:
            t = time.time() - self._t0
            if d[0] == civ.METERS["s"]:
                raw = 0 if self.ptt else int(60 + 50 * math.sin(t * 1.3) ** 2 + random.randint(0, 8))
            elif d[0] == civ.METERS["po"]:
                raw = int(self.levels["power"] * 213 / 255) if self.ptt else 0
            else:
                raw = random.randint(10, 30) if self.ptt else 0
            self._reply(bytes([civ.CMD_METER, d[0]]) + civ.int_to_bcd(raw, 2))
        elif cmd == civ.CMD_LEVEL:
            name = next((n for n, c in civ.LEVELS.items() if c == d[0]), None)
            if len(d) >= 3 and name:
                self.levels[name] = civ.bcd_to_int(d[1:3])
                self._reply(ack)
            elif name:
                self._reply(bytes([civ.CMD_LEVEL, d[0]]) + civ.int_to_bcd(self.levels.get(name, 0), 2))
        elif cmd == civ.CMD_SEND_CW:
            if d[:1] != b"\xff":
                self.sent_cw.append(d.decode("ascii", "ignore"))
            self._reply(ack)
        elif cmd == civ.CMD_SCOPE:
            if d[0] == civ.SCOPE_ON_OFF:
                self._scope_on = bool(d[1])
            elif d[0] == civ.SCOPE_SPAN and len(d) >= 7:
                self._span = max(1000, civ.bcd_to_freq(d[2:7]))
            self._reply(ack)
        else:
            self._reply(ack)

    def _scope_loop(self) -> None:
        carriers = [-0.8, -0.35, 0.1, 0.55]  # fração da meia-largura
        while not self._closed.wait(0.1):
            if not self._scope_on:
                continue
            low, high = self.freq - self._span, self.freq + self._span
            n = civ.SCOPE_POINTS
            t = time.time() - self._t0
            vals = bytearray()
            for i in range(n):
                x = (i / (n - 1)) * 2 - 1
                level = 12 + random.random() * 6
                for k, c in enumerate(carriers):
                    amp = 70 + 20 * math.sin(t * (0.7 + k * 0.3))
                    level += amp * math.exp(-((x - c) / 0.012) ** 2)
                level += 40 * math.exp(-((x - 0.0) / 0.01) ** 2)
                vals.append(min(160, int(level)))
            header = bytes([0x00]) + civ.freq_to_bcd(self.freq) + civ.freq_to_bcd(self._span) + b"\x00"  # centrado: centro e meia-largura
            sizes = [25] + [45] * 10  # 25 + 450 = 475
            pos = 0
            for seq in range(1, civ.SCOPE_DIVISIONS + 1):
                chunk = bytes(vals[pos:pos + sizes[seq - 1]])
                pos += sizes[seq - 1]
                body = bytes([civ.CMD_SCOPE, civ.SCOPE_WAVE, 0x00, int_bcd(seq), int_bcd(civ.SCOPE_DIVISIONS)])
                if seq == 1:
                    body += header
                self._reply(body + chunk, dst=civ.CONTROLLER_ADDRESS)


def int_bcd(n: int) -> int:
    return civ.int_to_bcd(n, 1)[0]
