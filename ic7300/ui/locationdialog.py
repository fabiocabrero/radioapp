"""Pede e confirma a localização do operador: por coordenadas ou por grid locator, com o que foi detectado já preenchido."""
from __future__ import annotations

from typing import Optional

from PySide6 import QtWidgets

from .. import geo


class LocationDialog(QtWidgets.QDialog):
    def __init__(self, parent, detected: Optional[tuple[float, float]], source: str, current: tuple[float, float, str]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Confirme sua localização")
        self.setMinimumWidth(460)
        lat, lon, grid = current
        if detected:
            lat, lon, grid = detected[0], detected[1], geo.latlon_to_grid(*detected)
            intro = (f"Localização detectada ({source}). Ela serve para distâncias, direção da antena, propagação e satélites.\n"
                     "Confirme ou corrija abaixo.")
        else:
            intro = ("Não foi possível obter a localização deste computador (sem GPS ou o Windows não a informou).\n"
                     "Informe as coordenadas ou o grid locator (ex.: GG66).")
        lay = QtWidgets.QVBoxLayout(self)
        label = QtWidgets.QLabel(intro)
        label.setWordWrap(True)
        lay.addWidget(label)
        form = QtWidgets.QFormLayout()
        self.sp_lat = QtWidgets.QDoubleSpinBox()
        self.sp_lat.setRange(-90, 90)
        self.sp_lat.setDecimals(5)
        self.sp_lon = QtWidgets.QDoubleSpinBox()
        self.sp_lon.setRange(-180, 180)
        self.sp_lon.setDecimals(5)
        self.ed_grid = QtWidgets.QLineEdit(grid)
        self.ed_grid.setMaxLength(8)
        self.ed_grid.setPlaceholderText("ex.: GG66pf")
        self.sp_lat.setValue(lat)
        self.sp_lon.setValue(lon)
        form.addRow("Latitude (°, sul negativo)", self.sp_lat)
        form.addRow("Longitude (°, oeste negativo)", self.sp_lon)
        form.addRow("ou Grid locator", self.ed_grid)
        lay.addLayout(form)
        self.lbl_err = QtWidgets.QLabel("")
        self.lbl_err.setStyleSheet("color:#c0392b")
        lay.addWidget(self.lbl_err)
        btns = QtWidgets.QDialogButtonBox()
        self.btn_ok = btns.addButton("Confirmar localização", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        btns.addButton("Agora não", QtWidgets.QDialogButtonBox.ButtonRole.RejectRole)
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)
        self._sync = False
        self.ed_grid.textEdited.connect(self._from_grid)
        self.sp_lat.valueChanged.connect(self._from_latlon)
        self.sp_lon.valueChanged.connect(self._from_latlon)

    def _from_grid(self, text: str) -> None:
        if geo.valid_grid(text.strip()):
            self._sync = True
            lat, lon = geo.grid_to_latlon(text.strip())
            self.sp_lat.setValue(lat)
            self.sp_lon.setValue(lon)
            self._sync = False
            self.lbl_err.setText("")

    def _from_latlon(self) -> None:
        if not self._sync:
            self.ed_grid.setText(geo.latlon_to_grid(self.sp_lat.value(), self.sp_lon.value()))

    def _accept(self) -> None:
        grid = self.ed_grid.text().strip()
        if grid and not geo.valid_grid(grid):
            self.lbl_err.setText("Grid inválido. Use o formato de 4 ou 6 caracteres, ex.: GG66 ou GG66pf.")
            return
        if not (self.sp_lat.value() or self.sp_lon.value()) and not grid:
            self.lbl_err.setText("Informe as coordenadas ou o grid.")
            return
        self.accept()

    def result_location(self) -> tuple[float, float, str]:
        grid = self.ed_grid.text().strip()
        if geo.valid_grid(grid) and not (self.sp_lat.value() or self.sp_lon.value()):
            lat, lon = geo.grid_to_latlon(grid)
        else:
            lat, lon = self.sp_lat.value(), self.sp_lon.value()
        return lat, lon, grid or geo.latlon_to_grid(lat, lon)
