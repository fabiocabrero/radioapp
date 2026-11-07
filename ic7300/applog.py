"""Registro (log) do app em %APPDATA%/IC7300App/logs/ic7300.log, com rotação. Não grava senhas nem credenciais."""
from __future__ import annotations

import logging
import platform
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import __version__
from .settings import app_dir

log = logging.getLogger("ic7300")
_FORMAT = "%(asctime)s %(levelname)-7s %(message)s"


def log_path() -> Path:
    d = app_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / "ic7300.log"


def setup() -> Path:
    """Liga o log em arquivo e captura exceções não tratadas. Chamado uma vez em main()."""
    path = log_path()
    if not any(isinstance(h, RotatingFileHandler) for h in log.handlers):
        handler = RotatingFileHandler(path, maxBytes=500_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter(_FORMAT, "%Y-%m-%d %H:%M:%S"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
    log.info("IC-7300 Station %s | Python %s | %s", __version__, platform.python_version(), platform.platform())

    previous = sys.excepthook

    def hook(exc_type, exc, tb) -> None:
        log.error("Exceção não tratada", exc_info=(exc_type, exc, tb))
        previous(exc_type, exc, tb)

    sys.excepthook = hook
    return path


def tail(max_lines: int = 400) -> str:
    """Últimas linhas do log atual (vazio se ainda não existe)."""
    path = log_path()
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-max_lines:])
