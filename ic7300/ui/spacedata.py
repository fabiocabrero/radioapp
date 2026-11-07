"""Dados compartilhados de clima espacial e tempo (NOAA SWPC, D-RAP, aurora, Open-Meteo), atualizados em segundo plano."""
from __future__ import annotations

import threading
import time
from typing import Optional

from PySide6 import QtCore

from .. import propagation, spacewx, weather


class SpaceData(QtCore.QObject):
    changed = QtCore.Signal()          # clima espacial, D-RAP ou índices solares atualizados
    layer_ready = QtCore.Signal(str)   # "aurora", "cloud", "rain" carregados
    status = QtCore.Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.solar: Optional[propagation.SolarData] = None
        self.sw: Optional[spacewx.SpaceWeather] = None
        self.drap = None        # (lats, lons, matriz) em MHz
        self.aurora = None      # (matriz[lat][lon 0..359], horário)
        self.wx: dict[str, tuple] = {}   # variável -> (lats, lons, matriz, época)
        self._busy: set[str] = set()
        self.timer = QtCore.QTimer(self, interval=15 * 60_000, timeout=self.refresh)
        self.timer.start()

    def set_solar(self, solar: propagation.SolarData) -> None:
        self.solar = solar
        self.changed.emit()

    def _bg(self, key: str, fn) -> None:
        if key in self._busy:
            return
        self._busy.add(key)

        def run() -> None:
            try:
                fn()
            except Exception as exc:
                self.status.emit(f"{key}: {exc}")
            finally:
                self._busy.discard(key)

        threading.Thread(target=run, daemon=True).start()

    def refresh(self) -> None:
        def work() -> None:
            self.sw = spacewx.fetch_spacewx()
            self.changed.emit()

        def drap() -> None:
            self.drap = spacewx.fetch_drap()
            self.changed.emit()

        self._bg("NOAA SWPC", work)
        self._bg("D-RAP", drap)

    def ensure_aurora(self) -> None:
        def work() -> None:
            self.aurora = spacewx.fetch_aurora()
            self.layer_ready.emit("aurora")

        self._bg("Aurora", work)

    WX_VARS = {"cloud": "cloud_cover", "rain": "precipitation"}

    def ensure_weather(self, key: str) -> None:
        cached = self.wx.get(key)
        if cached and time.time() - cached[3] < 1800:
            self.layer_ready.emit(key)
            return

        def work() -> None:
            lats, lons, z = weather.fetch_grid(self.WX_VARS[key], 10)
            self.wx[key] = (lats, lons, z, time.time())
            self.layer_ready.emit(key)

        self._bg("Tempo", work)
