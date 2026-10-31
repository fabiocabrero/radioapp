"""Spots: cliente de DX Cluster (telnet) e POTA (API pública)."""
from __future__ import annotations

import json
import re
import socket
import threading
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

_SPOT_RE = re.compile(r"DX de\s+([A-Z0-9/\-#]+):\s+([\d.]+)\s+([A-Z0-9/]+)\s+(.*?)\s+(\d{4})Z", re.I)


@dataclass
class Spot:
    source: str    # "DX" ou "POTA"
    call: str
    freq: int      # Hz
    info: str
    time: str
    spotter: str = ""
    mode: str = ""


def parse_dx_line(line: str) -> Optional[Spot]:
    m = _SPOT_RE.search(line)
    if not m:
        return None
    return Spot("DX", m.group(3).upper(), int(float(m.group(2)) * 1000), m.group(4).strip(), m.group(5) + "Z",
                spotter=m.group(1).rstrip(":"))


class ClusterClient:
    def __init__(self, host: str, port: int, login: str, on_spot: Callable[[Spot], None],
                 on_status: Callable[[str], None]) -> None:
        self.host, self.port, self.login = host, port, login
        self.on_spot, self.on_status = on_spot, on_status
        self._sock: Optional[socket.socket] = None
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass

    def _run(self) -> None:
        try:
            self._sock = socket.create_connection((self.host, self.port), timeout=15)
            self._sock.settimeout(1.0)
            self.on_status(f"Conectado a {self.host}")
            buf, sent_login = b"", False
            while not self._stop.is_set():
                try:
                    chunk = self._sock.recv(4096)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buf += chunk
                if not sent_login and re.search(rb"(login|call)[^\n]*:\s*$", buf[-200:], re.I):
                    self._sock.sendall(self.login.encode() + b"\r\n")
                    sent_login = True
                while b"\n" in buf:
                    line, _, buf = buf.partition(b"\n")
                    spot = parse_dx_line(line.decode("latin-1"))
                    if spot:
                        self.on_spot(spot)
        except OSError as exc:
            self.on_status(f"Cluster: {exc}")
        else:
            self.on_status("Cluster desconectado")


def fetch_pota() -> list[Spot]:
    req = urllib.request.Request("https://api.pota.app/spot/activator", headers={"User-Agent": "IC7300App/0.1"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.load(resp)
    spots = []
    for s in data:
        try:
            freq = int(float(s["frequency"]) * 1000)
        except (KeyError, ValueError, TypeError):
            continue
        spots.append(Spot("POTA", s.get("activator", ""), freq, f"{s.get('reference', '')} {s.get('name', '')}".strip(),
                          str(s.get("spotTime", ""))[-8:-3] + "Z", spotter=s.get("spotter", ""), mode=s.get("mode", "")))
    return spots
