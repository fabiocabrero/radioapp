"""Tela Satélites: passagens previstas sobre o QTH do radioperador, frequências (SatNOGS DB) e Doppler."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from .. import satellites, satnogs
from ..satellites import Pass, Sat
from ..satnogs import Transmitter


def _local(dt: datetime) -> datetime:
    return dt.astimezone()


class SatellitesTab(QtWidgets.QWidget):
    tune_requested = QtCore.Signal(int, str, bool)   # Hz, modo do rádio, DATA
    message = QtCore.Signal(str)
    _loaded = QtCore.Signal(object, object)
    _passes_ready = QtCore.Signal(object)
    _failed = QtCore.Signal(str)

    def __init__(self, get_home: Callable[[], Optional[tuple[float, float]]]) -> None:
        super().__init__()
        self.get_home = get_home
        self.sats: list[Sat] = []
        self.tx: dict[int, list[Transmitter]] = {}
        self.passes: list[Pass] = []
        self.shown: list[Pass] = []
        self.current: Optional[Pass] = None
        self._busy = False
        outer = QtWidgets.QVBoxLayout(self)

        bar = QtWidgets.QHBoxLayout()
        self.btn_refresh = QtWidgets.QPushButton("Atualizar dados e passagens")
        self.sp_el = QtWidgets.QSpinBox()
        self.sp_el.setRange(0, 80)
        self.sp_el.setValue(10)
        self.sp_el.setSuffix("° mín.")
        self.cb_hours = QtWidgets.QComboBox()
        for h in (12, 24, 48, 72):
            self.cb_hours.addItem(f"próximas {h} h", h)
        self.cb_hours.setCurrentIndex(1)
        self.chk_rx = QtWidgets.QCheckBox("Só o que o IC-7300 ouve")
        self.chk_rx.setToolTip("O IC-7300 recebe de 30 kHz a 74,8 MHz: pega downlinks em HF (ex.: 29 MHz) e 6 m, "
                               "mas não 145/435 MHz (VHF/UHF), onde está a maioria dos satélites.")
        self.chk_tx = QtWidgets.QCheckBox("Só com transmissor ativo conhecido")
        for w in (self.btn_refresh, self.sp_el, self.cb_hours, self.chk_rx, self.chk_tx):
            bar.addWidget(w)
        bar.addStretch()
        outer.addLayout(bar)
        self.lbl_status = QtWidgets.QLabel("Defina seu local (Local / GPS) e atualize para ver as passagens.")
        self.lbl_status.setWordWrap(True)
        outer.addWidget(self.lbl_status)

        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        outer.addWidget(split, 1)
        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Satélite", "Início (local)", "Dur.", "El. máx", "Az início → fim", "Sinais"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        split.addWidget(self.table)

        right = QtWidgets.QWidget()
        rl = QtWidgets.QVBoxLayout(right)
        self.polar = pg.PlotWidget(background="#0b1220")
        self.polar.setMenuEnabled(False)
        self.polar.hideButtons()
        self.polar.setMouseEnabled(False, False)
        self.polar.setAspectLocked(True)
        self.polar.showAxis("left", False)
        self.polar.showAxis("bottom", False)
        self.polar.setRange(xRange=(-100, 100), yRange=(-100, 100), padding=0)
        self.polar.setMinimumHeight(260)
        th = np.linspace(0, 2 * np.pi, 120)
        for el in (0, 30, 60):
            r = 90 - el
            self.polar.plot(r * np.sin(th), r * np.cos(th), pen=pg.mkPen("#2e3b50", width=1))
        for txt, x, y in (("N", 0, 96), ("L", 96, 0), ("S", 0, -96), ("O", -96, 0)):
            t = pg.TextItem(txt, color="#9aa7b6", anchor=(0.5, 0.5))
            t.setPos(x, y)
            self.polar.addItem(t)
        self.track_curve = self.polar.plot(pen=pg.mkPen("#ffd54a", width=2))
        self.aos_dot = pg.ScatterPlotItem(size=10, brush=pg.mkBrush("#66bb6a"), pen=pg.mkPen("w"))
        self.los_dot = pg.ScatterPlotItem(size=10, brush=pg.mkBrush("#ef5350"), pen=pg.mkPen("w"))
        self.now_dot = pg.ScatterPlotItem(size=14, symbol="star", brush=pg.mkBrush("#ffffff"), pen=pg.mkPen("#ff5252"))
        for d in (self.aos_dot, self.los_dot, self.now_dot):
            self.polar.addItem(d)
        rl.addWidget(self.polar)
        self.lbl_detail = QtWidgets.QLabel("Selecione uma passagem.")
        self.lbl_detail.setWordWrap(True)
        rl.addWidget(self.lbl_detail)
        self.tx_table = QtWidgets.QTableWidget(0, 4)
        self.tx_table.setHorizontalHeaderLabels(["Transmissor", "↑ subida (MHz)", "↓ descida (MHz)", "Modo / IC-7300"])
        self.tx_table.verticalHeader().setVisible(False)
        self.tx_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tx_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.tx_table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.tx_table.horizontalHeader().setStretchLastSection(True)
        rl.addWidget(self.tx_table, 1)
        row = QtWidgets.QHBoxLayout()
        self.btn_tune = QtWidgets.QPushButton("Sintonizar o rádio no downlink (com Doppler)")
        self.btn_amsat = QtWidgets.QPushButton("Status no AMSAT")
        row.addWidget(self.btn_tune)
        row.addWidget(self.btn_amsat)
        rl.addLayout(row)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)

        src = QtWidgets.QLabel("Fontes: elementos orbitais do CelesTrak (grupo amateur); transmissores, frequências e modos do SatNOGS DB "
                               "(dados abertos); status de operação reportado pelos usuários no AMSAT. Passagens calculadas aqui com "
                               "modelo simplificado (erro de minutos). Horários na hora do seu PC.")
        src.setWordWrap(True)
        src.setObjectName("cardTips")
        outer.addWidget(src)

        self.btn_refresh.clicked.connect(self.refresh)
        for w in (self.sp_el,):
            w.valueChanged.connect(self._recompute)
        self.cb_hours.currentIndexChanged.connect(self._recompute)
        self.chk_rx.toggled.connect(self._fill_table)
        self.chk_tx.toggled.connect(self._fill_table)
        self.table.itemSelectionChanged.connect(self._select)
        self.tx_table.itemSelectionChanged.connect(self._update_doppler)
        self.btn_tune.clicked.connect(self._tune)
        self.btn_amsat.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl("https://www.amsat.org/status/")))
        self._loaded.connect(self._on_loaded)
        self._passes_ready.connect(self._on_passes)
        self._failed.connect(lambda m: (setattr(self, "_busy", False), self.lbl_status.setText(m)))
        self.timer = QtCore.QTimer(self, interval=1000, timeout=self._tick)
        self.timer.start()
        self._first = True

    def showEvent(self, e: QtGui.QShowEvent) -> None:
        super().showEvent(e)
        if self._first:
            self._first = False
            QtCore.QTimer.singleShot(200, self.refresh)

    # ------------------------------------------------------------------ dados
    def refresh(self) -> None:
        if self._busy:
            return
        if not self.get_home():
            self.lbl_status.setText("Defina seu local (aba Local / GPS) para calcular as passagens.")
            return
        self._busy = True
        self.lbl_status.setText("Baixando elementos orbitais (CelesTrak) e transmissores (SatNOGS)…")

        def work() -> None:
            try:
                sats = satellites.fetch_sats()
                try:
                    tx = satnogs.by_norad(satnogs.fetch_transmitters())
                except Exception as exc:  # passagens ainda valem sem as frequências
                    self.message.emit(f"SatNOGS: {exc}")
                    tx = {}
                self._loaded.emit(sats, tx)
            except Exception as exc:
                self._failed.emit(f"Satélites: {exc}")

        threading.Thread(target=work, daemon=True).start()

    def _on_loaded(self, sats: list, tx: dict) -> None:
        self.sats, self.tx = sats, tx
        self._busy = False
        self._recompute()

    def _recompute(self) -> None:
        home = self.get_home()
        if not (self.sats and home) or self._busy:
            return
        self._busy = True
        hours, min_el, sats = self.cb_hours.currentData(), self.sp_el.value(), list(self.sats)
        self.lbl_status.setText(f"Calculando passagens de {len(sats)} satélites…")

        def work() -> None:
            try:
                out: list[Pass] = []
                for s in sats:
                    out += satellites.next_passes(s, home[0], home[1], hours=hours, min_el=min_el)
                out.sort(key=lambda p: p.aos)
                self._passes_ready.emit(out)
            except Exception as exc:
                self._failed.emit(f"Passagens: {exc}")

        threading.Thread(target=work, daemon=True).start()

    def _on_passes(self, passes: list) -> None:
        self.passes = passes
        self._busy = False
        self._fill_table()

    def _usable(self, p: Pass) -> list[Transmitter]:
        return self.tx.get(p.sat.norad, [])

    def _fill_table(self) -> None:
        shown = []
        for p in self.passes:
            txs = self._usable(p)
            if self.chk_tx.isChecked() and not txs:
                continue
            if self.chk_rx.isChecked() and not any(t.rx_in_range for t in txs):
                continue
            shown.append(p)
        self.shown = shown
        self.table.setRowCount(len(shown))
        for r, p in enumerate(shown):
            txs = self._usable(p)
            heard = [t for t in txs if t.rx_in_range]
            sinais = ", ".join(sorted({f"{t.mode} {t.down_center / 1e6:.3f}" for t in heard}))[:80] if heard else \
                (f"{len(txs)} transmissor(es), nenhum no alcance do IC-7300" if txs else "sem dados de frequência")
            vals = [p.sat.name, f"{_local(p.aos):%d/%m %H:%M:%S}", f"{int(p.seconds // 60)}:{int(p.seconds % 60):02d}",
                    f"{p.max_el:.0f}°", f"{p.az_aos:.0f}° → {p.az_los:.0f}°", sinais]
            for c, v in enumerate(vals):
                item = QtWidgets.QTableWidgetItem(v)
                if heard:
                    item.setForeground(QtGui.QColor("#7CFC9A"))
                if p.aos <= datetime.now(timezone.utc) <= p.los:
                    item.setBackground(QtGui.QColor("#2e4a2e"))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        home = self.get_home()
        age = max((s.age_days for s in self.sats), default=0)
        self.lbl_status.setText(f"{len(shown)} passagens em {self.cb_hours.currentData()} h sobre {home[0]:.2f}, {home[1]:.2f}"
                                f" (de {len(self.passes)}; elementos de até {age:.1f} dias)." if home else "")
        if shown:
            self.table.selectRow(0)
        else:
            self.current = None

    # ------------------------------------------------------------------ detalhe
    def _select(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows or rows[0].row() >= len(self.shown):
            return
        self.current = p = self.shown[rows[0].row()]
        home = self.get_home()
        times, el, az, _ = satellites.track(p.sat, p.aos, p.los, home[0], home[1], 10.0)
        r = 90 - el
        x, y = r * np.sin(np.radians(az)), r * np.cos(np.radians(az))
        self.track_curve.setData(x, y)
        self.aos_dot.setData(x=[x[0]], y=[y[0]])
        self.los_dot.setData(x=[x[-1]], y=[y[-1]])
        self.now_dot.setData(x=[], y=[])
        self.lbl_detail.setText(f"{p.sat.name}: início {_local(p.aos):%H:%M:%S} (verde, az {p.az_aos:.0f}°), "
                                f"máximo {_local(p.tca):%H:%M:%S} a {p.max_el:.0f}° (az {p.az_tca:.0f}°), "
                                f"fim {_local(p.los):%H:%M:%S} (vermelho, az {p.az_los:.0f}°).")
        txs = self._usable(p)
        self.tx_table.setRowCount(len(txs))
        for rr, t in enumerate(sorted(txs, key=lambda t: (not t.rx_in_range, t.description))):
            fmt = lambda v: f"{v / 1e6:.4f}" if v else "—"  # noqa: E731
            vals = [t.description or t.kind, fmt(t.up_center), fmt(t.down_center),
                    f"{t.mode}{' inv.' if t.invert else ''} · " + ("IC-7300 ouve" if t.rx_in_range else "fora do alcance do IC-7300")]
            for c, v in enumerate(vals):
                it = QtWidgets.QTableWidgetItem(v)
                it.setData(QtCore.Qt.ItemDataRole.UserRole, t)
                if t.rx_in_range:
                    it.setForeground(QtGui.QColor("#7CFC9A"))
                self.tx_table.setItem(rr, c, it)
        self.tx_table.resizeColumnsToContents()
        if txs:
            self.tx_table.selectRow(0)
        self._update_doppler()

    def _selected_tx(self) -> Optional[Transmitter]:
        rows = self.tx_table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.tx_table.item(rows[0].row(), 0)
        return item.data(QtCore.Qt.ItemDataRole.UserRole) if item else None

    def _doppler_at(self, p: Pass, tx: Transmitter, when: datetime) -> Optional[float]:
        home = self.get_home()
        if not (home and tx.down_center):
            return None
        return satellites.doppler(tx.down_center, satellites.range_rate(p.sat, when, *home))

    def _update_doppler(self) -> None:
        p, tx = self.current, self._selected_tx()
        if not p or not tx or not tx.down_center:
            return
        pts = [self._doppler_at(p, tx, t) for t in (p.aos, p.tca, p.los)]
        if None in pts:
            return
        self.lbl_detail.setText(self.lbl_detail.text().split("\nDoppler")[0] +
                                f"\nDoppler em {tx.down_center / 1e6:.4f} MHz: início {pts[0] / 1e6:.4f}, máximo {pts[1] / 1e6:.4f}, "
                                f"fim {pts[2] / 1e6:.4f} MHz (variação {abs(pts[0] - pts[2]) / 1e3:.1f} kHz).")

    def _tick(self) -> None:
        p = self.current
        home = self.get_home()
        if not (p and home) or not self.isVisible():
            return
        now = datetime.now(timezone.utc)
        if p.aos <= now <= p.los:
            el, az = satellites.look_angles(p.sat, now, *home)
            r = 90 - el
            self.now_dot.setData(x=[r * np.sin(np.radians(az))], y=[r * np.cos(np.radians(az))])
        else:
            self.now_dot.setData(x=[], y=[])

    def _tune(self) -> None:
        p, tx = self.current, self._selected_tx()
        if not p or not tx:
            self.message.emit("Escolha uma passagem e um transmissor.")
            return
        if not tx.rx_in_range:
            self.message.emit(f"O IC-7300 não recebe {tx.down_center / 1e6:.3f} MHz (alcance 0,03 a 74,8 MHz). "
                              "Use um receptor VHF/UHF (SDR, outro rádio) com esta frequência.")
            return
        now = datetime.now(timezone.utc)
        when = now if p.aos <= now <= p.los else p.aos
        freq = self._doppler_at(p, tx, when) or tx.down_center
        mode, data = satnogs.radio_mode(tx.mode)
        self.tune_requested.emit(int(round(freq)), mode, data)
        self.message.emit(f"Sintonizado em {freq / 1e6:.4f} MHz ({'Doppler agora' if when is now else 'Doppler no início da passagem'}).")
