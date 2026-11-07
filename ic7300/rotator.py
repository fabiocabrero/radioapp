"""Rotor de antena pelo rotctld do Hamlib (TCP, texto simples): gira para um azimute e lê a posição."""
from __future__ import annotations

import socket
from typing import Optional


class RotatorClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 4533, timeout: float = 3.0) -> None:
        self.host, self.port, self.timeout = host, port, timeout

    @classmethod
    def from_text(cls, text: str) -> "RotatorClient":
        host, _, port = text.strip().partition(":")
        if not port.isdigit():
            raise ValueError("Informe o rotctld como host:porta (ex.: 127.0.0.1:4533).")
        return cls(host or "127.0.0.1", int(port))

    def _ask(self, command: str, lines: int = 1) -> list[str]:
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as s:
            s.settimeout(self.timeout)
            s.sendall((command + "\n").encode())
            f = s.makefile("rb")
            return [f.readline().decode("utf-8", "replace").strip() for _ in range(lines)]

    def set_azimuth(self, az: float, el: float = 0.0) -> None:
        r = self._ask(f"P {az % 360:.1f} {el:.1f}")[0]
        if not r.startswith("RPRT 0"):
            raise RuntimeError(f"O rotor recusou o comando ({r}).")

    def check(self) -> float:
        """Testa a conexão: devolve o azimute atual do rotor ou levanta RuntimeError com o motivo."""
        try:
            lines = self._ask("p", 2)
        except OSError as exc:
            raise RuntimeError(f"sem resposta de {self.host}:{self.port} ({exc}). Confira se o rotctld está rodando.") from exc
        try:
            return float(lines[0])
        except ValueError as exc:
            raise RuntimeError(f"resposta inesperada do rotor: {lines[0] or 'vazia'}") from exc

    def get_azimuth(self) -> Optional[float]:
        try:
            return float(self._ask("p", 2)[0])
        except (OSError, ValueError):
            return None
