"""Configurações do usuário, salvas em %APPDATA%/IC7300App/settings.json."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


def app_dir() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home())) / "IC7300App"
    base.mkdir(parents=True, exist_ok=True)
    return base


@dataclass
class Settings:
    callsign: str = ""
    grid: str = ""
    lat: float = 0.0
    lon: float = 0.0
    port: str = ""
    baud: int = 115200
    civ_address: int = 0x94
    audio_input: str = ""
    audio_output: str = ""
    gps_port: str = ""
    gps_baud: int = 4800
    cluster_host: str = "dxc.ve7cc.net"
    cluster_port: int = 23
    cw_macros: list = field(default_factory=lambda: [
        "CQ CQ CQ DE {call} {call} K", "{their} DE {call} UR 599 599 BK", "R R TNX {their} 73 DE {call} SK",
        "?", "QRZ? DE {call}", "TU 73 EE", "{call}", "AGN?"])
    last_freq_by_band: dict = field(default_factory=dict)
    simulator: bool = True
    rigctl_enabled: bool = False
    rigctl_port: int = 4532
    my_ref: str = ""
    wsjtx_dir: str = ""
    contest_name: str = ""
    cabrillo: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Settings":
        path = app_dir() / "settings.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        (app_dir() / "settings.json").write_text(json.dumps(asdict(self), indent=1, ensure_ascii=False), encoding="utf-8")
