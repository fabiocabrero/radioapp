"""Configurações do usuário, salvas em %APPDATA%/IC7300App/settings.json."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


def app_dir() -> Path:
    override = os.environ.get("IC7300_APPDATA")  # pasta alternativa (testes, instalação portátil)
    base = Path(override) if override else Path(os.environ.get("APPDATA", Path.home())) / "IC7300App"
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
    restore_on_exit: bool = False
    ext_paths: dict = field(default_factory=dict)
    wsjtx_dir: str = ""
    band_plan: str = "auto"
    license_class: str = ""  # legado: classe do plano brasileiro (migrada para classes_by_plan)
    classes_by_plan: dict = field(default_factory=dict)
    contest_name: str = ""
    hamqth_user: str = ""
    hamqth_pass: str = ""  # guardada em texto no perfil local do usuário
    panel_open: bool = True
    op_name: str = ""
    op_city: str = ""
    setup_done: bool = False
    cabrillo: dict = field(default_factory=dict)
    rig_kind: str = "ic7300"   # ic7300 (CI-V nativo), hamlib (qualquer modelo) ou rigctld (já em execução)
    rig_model: int = 0
    rig_brand: str = "Icom"
    rig_host: str = "127.0.0.1:4533"
    loc_confirmed: bool = False  # o operador confirmou a localização (detectada ou digitada)
    rotor_host: str = ""         # rotctld do Hamlib (host:porta) para girar a antena
    voice_cfg: dict = field(default_factory=dict)  # tela Fonia: dispositivos, efeitos e chamadas

    @classmethod
    def load(cls) -> "Settings":
        path = app_dir() / "settings.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            st = cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})
            if st.license_class and "BR" not in st.classes_by_plan:  # migra a classe salva antes dos planos por país
                st.classes_by_plan["BR"] = st.license_class
            return st
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        (app_dir() / "settings.json").write_text(json.dumps(asdict(self), indent=1, ensure_ascii=False), encoding="utf-8")
