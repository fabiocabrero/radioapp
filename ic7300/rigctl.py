"""Servidor compatível com o protocolo `rigctld` do Hamlib (modelo "Hamlib NET rigctl").

WSJT-X, JS8Call, Fldigi, loggers etc. conectam em 127.0.0.1:4532 e controlam o rádio por este app.
"""
from __future__ import annotations

import socket
import threading
from typing import Callable, Optional

from .radio import Radio, RadioState

DEFAULT_PORT = 4532

# modo Hamlib -> (modo do IC-7300, DATA)
_SET_MODES = {
    "USB": ("USB", False), "LSB": ("LSB", False), "CW": ("CW", False), "CWR": ("CW-R", False),
    "RTTY": ("RTTY", False), "RTTYR": ("RTTY-R", False), "AM": ("AM", False), "FM": ("FM", False),
    "PKTUSB": ("USB", True), "PKTLSB": ("LSB", True), "PKTFM": ("FM", True),
}
_GET_MODES = {"CW-R": "CWR", "RTTY-R": "RTTYR"}
_WIDTHS = {"USB": 2400, "LSB": 2400, "CW": 500, "CW-R": 500, "AM": 6000, "FM": 12000, "RTTY": 500, "RTTY-R": 500}

RPRT_OK, RPRT_EINVAL, RPRT_EIO, RPRT_ENIMPL = 0, -1, -6, -4

# 0.03-74.8 MHz, todos os modos, 2-100 W; modos em máscara do Hamlib
_MODES_MASK = 0x1BFF
_DUMP_STATE = "\n".join([
    "0",                      # versão do protocolo
    "3073",                   # modelo (descartado pelo cliente)
    "0",                      # região ITU
    f"30000.000000 74800000.000000 {_MODES_MASK:x} 2000 100000 3 0x0",
    "0 0 0 0 0 0 0",
    f"1800000.000000 2000000.000000 {_MODES_MASK:x} 2000 100000 3 0x0",
    f"3500000.000000 4000000.000000 {_MODES_MASK:x} 2000 100000 3 0x0",
    f"5351500.000000 5366500.000000 {_MODES_MASK:x} 2000 100000 3 0x0",
    f"7000000.000000 7300000.000000 {_MODES_MASK:x} 2000 100000 3 0x0",
    f"10100000.000000 10150000.000000 {_MODES_MASK:x} 2000 100000 3 0x0",
    f"14000000.000000 14350000.000000 {_MODES_MASK:x} 2000 100000 3 0x0",
    f"18068000.000000 18168000.000000 {_MODES_MASK:x} 2000 100000 3 0x0",
    f"21000000.000000 21450000.000000 {_MODES_MASK:x} 2000 100000 3 0x0",
    f"24890000.000000 24990000.000000 {_MODES_MASK:x} 2000 100000 3 0x0",
    f"28000000.000000 29700000.000000 {_MODES_MASK:x} 2000 100000 3 0x0",
    f"50000000.000000 54000000.000000 {_MODES_MASK:x} 2000 100000 3 0x0",
    "0 0 0 0 0 0 0",
    f"{_MODES_MASK:x} 1",   # passos de sintonia
    "0 0",
    f"{_MODES_MASK:x} 2400",  # filtros
    "0 0",
    "0",                      # max RIT
    "0",                      # max XIT
    "0",                      # max IF shift
    "0",                      # announces
    "0",                      # preamp
    "0",                      # atenuador
    "0x0", "0x0",             # funções (get/set)
    "0x40005008", "0x5008",   # níveis: get = STRENGTH|AF|RFPOWER|KEYSPD, set = AF|RFPOWER|KEYSPD
    "0x0", "0x0",             # parâmetros (get/set)
]) + "\n"


class RigctlServer:
    def __init__(self, get_radio: Callable[[], Optional[Radio]], get_state: Callable[[], RadioState],
                 host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                 on_message: Callable[[str], None] = lambda m: None) -> None:
        self.get_radio, self.get_state, self.host, self.port, self.on_message = get_radio, get_state, host, port, on_message
        self._sock: Optional[socket.socket] = None
        self._stop = threading.Event()
        self._clients: list[socket.socket] = []

    def start(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(4)
        self._sock.settimeout(0.5)
        self.port = self._sock.getsockname()[1]
        self._stop.clear()
        threading.Thread(target=self._accept_loop, daemon=True).start()
        self.on_message(f"rigctl ouvindo em {self.host}:{self.port}")

    def stop(self) -> None:
        self._stop.set()
        for c in list(self._clients):
            try:
                c.close()
            except OSError:
                pass
        if self._sock:
            self._sock.close()
            self._sock = None

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self._clients.append(conn)
            threading.Thread(target=self._client_loop, args=(conn,), daemon=True).start()

    def _client_loop(self, conn: socket.socket) -> None:
        conn.settimeout(1.0)
        buf = b""
        try:
            while not self._stop.is_set():
                try:
                    chunk = conn.recv(1024)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, _, buf = buf.partition(b"\n")
                    reply, close = self.handle_line(line.decode("latin-1").strip())
                    if reply:
                        conn.sendall(reply.encode("latin-1"))
                    if close:
                        return
        except OSError:
            pass
        finally:
            if conn in self._clients:
                self._clients.remove(conn)
            conn.close()

    # ---- protocolo ----
    def handle_line(self, line: str) -> tuple[str, bool]:
        """Executa um comando; devolve (resposta, encerrar conexão)."""
        if not line:
            return "", False
        extended = line[0] in "+;|"
        if extended:
            line = line[1:].lstrip()
        parts = line.split()
        cmd, args = parts[0], [p for p in parts[1:] if not _is_vfo(p)]
        if cmd.startswith("\\"):
            cmd = cmd[1:]
        state, radio = self.get_state(), self.get_radio()
        if cmd in ("q", "Q", "quit"):
            return "", True
        if cmd == "chk_vfo":
            return "0\n", False
        if cmd == "dump_state":
            return _DUMP_STATE, False
        if cmd == "stream_caps":
            return f"RPRT {RPRT_OK}\n", False
        if cmd in ("get_info", "_"):
            return "IC-7300 Station\n", False
        if cmd in ("get_powerstat", "\x00"):
            return "1\n", False
        if cmd == "get_lock_mode":
            return f"0\nRPRT {RPRT_OK}\n", False  # o cliente Hamlib lê duas linhas
        if cmd == "set_lock_mode":
            return f"RPRT {RPRT_OK}\n", False
        if radio is None:
            return f"RPRT {RPRT_EIO}\n", False

        if cmd in ("f", "get_freq"):
            return f"{state.freq}\n", False
        if cmd in ("F", "set_freq") and args:
            try:
                radio.set_freq(int(round(float(args[0]))))
            except ValueError:
                return f"RPRT {RPRT_EINVAL}\n", False
            return f"RPRT {RPRT_OK}\n", False
        if cmd in ("m", "get_mode"):
            name = _GET_MODES.get(state.mode, state.mode)
            if state.data_mode and name in ("USB", "LSB", "FM"):
                name = "PKT" + name
            return f"{name}\n{_WIDTHS.get(state.mode, 2400)}\n", False
        if cmd in ("M", "set_mode") and args:
            target = _SET_MODES.get(args[0].upper())
            if not target:
                return f"RPRT {RPRT_EINVAL}\n", False
            radio.set_mode(target[0], target[1], state.filter)
            return f"RPRT {RPRT_OK}\n", False
        if cmd in ("t", "get_ptt"):
            return f"{int(state.ptt)}\n", False
        if cmd in ("T", "set_ptt") and args:
            radio.set_ptt(args[0] not in ("0",))
            return f"RPRT {RPRT_OK}\n", False
        if cmd in ("v", "get_vfo"):
            return "VFOA\n", False
        if cmd in ("V", "set_vfo"):
            return f"RPRT {RPRT_OK}\n", False
        if cmd in ("s", "get_split_vfo"):
            return "0\nVFOA\n", False
        if cmd in ("S", "set_split_vfo"):
            return f"RPRT {RPRT_OK}\n", False
        if cmd in ("i", "get_split_freq"):
            return f"{state.freq}\n", False
        if cmd in ("l", "get_level") and args:
            return self._get_level(args[0].upper(), state), False
        if cmd in ("L", "set_level") and len(args) >= 2:
            return self._set_level(radio, args[0].upper(), args[1]), False
        return f"RPRT {RPRT_ENIMPL}\n", False

    @staticmethod
    def _get_level(name: str, state: RadioState) -> str:
        if name == "STRENGTH":
            raw = state.s_meter
            db = -54 + raw / 120 * 54 if raw <= 120 else (raw - 120) / 121 * 60
            return f"{round(db)}\n"
        if name == "RFPOWER":
            return f"{state.levels.get('power', 0) / 255:.3f}\n"
        if name == "AF":
            return f"{state.levels.get('af', 0) / 255:.3f}\n"
        if name == "KEYSPD":
            return f"{6 + round(state.levels.get('key_speed', 0) / 255 * 42)}\n"
        return f"RPRT {RPRT_ENIMPL}\n"

    @staticmethod
    def _set_level(radio: Radio, name: str, value: str) -> str:
        try:
            v = float(value)
        except ValueError:
            return f"RPRT {RPRT_EINVAL}\n"
        if name == "RFPOWER":
            radio.set_level("power", int(max(0, min(1, v)) * 255))
        elif name == "AF":
            radio.set_level("af", int(max(0, min(1, v)) * 255))
        elif name == "KEYSPD":
            radio.set_level("key_speed", int(max(0, min(255, (v - 6) / 42 * 255))))
        else:
            return f"RPRT {RPRT_ENIMPL}\n"
        return f"RPRT {RPRT_OK}\n"


def _is_vfo(token: str) -> bool:
    return token.upper().startswith(("VFO", "MAIN", "SUB", "MEM", "CURR"))
