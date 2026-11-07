"""Tela Fonia: efeitos de áudio (TX e RX), gravação das conversas, mensagens gravadas e chamadas automáticas com escuta do canal."""
from __future__ import annotations

import os
import time
from dataclasses import fields
from typing import Callable, Optional

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from .. import audio, callid, voice
from ..dsp.vad import VoiceDetector
from ..dsp.voicefx import PRESETS_RX, PRESETS_TX, FxSettings, VoiceFX
from ..settings import Settings

BIG = "font: bold 13pt; padding: 10px 16px;"


def _slider(lo: int, hi: int, val: int, suffix: str = "") -> tuple[QtWidgets.QSlider, QtWidgets.QLabel]:
    s = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
    s.setRange(lo, hi)
    s.setValue(val)
    lab = QtWidgets.QLabel(f"{val}{suffix}")
    lab.setMinimumWidth(62)
    s.valueChanged.connect(lambda v: lab.setText(f"{v}{suffix}"))
    return s, lab


class FxPanel(QtWidgets.QWidget):
    """Predefinidos e controles de efeitos; `changed` dispara a cada ajuste."""

    changed = QtCore.Signal()

    def __init__(self, presets: dict[str, FxSettings], tip: str) -> None:
        super().__init__()
        self.presets = presets
        self._loading = False
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.cb = QtWidgets.QComboBox()
        self.cb.addItems(list(presets))
        self.cb.currentTextChanged.connect(lambda n: self.set_settings(self.presets[n]))
        lay.addWidget(QtWidgets.QLabel("Predefinido:"))
        lay.addWidget(self.cb)
        form = QtWidgets.QFormLayout()
        self.ctl: dict[str, QtWidgets.QSlider] = {}

        def add(key: str, label: str, lo: int, hi: int, suffix: str, tooltip: str) -> None:
            s, lab = _slider(lo, hi, 0, suffix)
            s.setToolTip(tooltip)
            s.valueChanged.connect(self._emit)
            row = QtWidgets.QHBoxLayout()
            row.addWidget(s)
            row.addWidget(lab)
            form.addRow(label, row)
            self.ctl[key] = s

        add("comp", "Compressão", 0, 100, " %", "Nivela a voz: eleva as partes fracas e segura as fortes. É o que mais ajuda a ser entendido com sinal fraco.")
        add("presence_db", "Presença (2,5 kHz)", 0, 10, " dB", "Realça as consoantes para a fala ficar mais inteligível.")
        add("hp_hz", "Cortar graves", 20, 500, " Hz", "Tira o ronco e libera potência para a faixa útil da voz.")
        add("gate_db", "Porta de ruído", -90, -30, " dB", "Silencia o fundo quando você não fala (-90 = desligada).")
        add("echo_mix", "Eco", 0, 80, " %", "Repete a voz. Prejudica a compreensão em HF: use para testes ou conversa local.")
        add("echo_ms", "  atraso do eco", 80, 600, " ms", "Tempo entre a voz e o eco.")
        add("reverb_mix", "Reverb", 0, 60, " %", "Som de sala. Prejudica a compreensão em HF: use com moderação.")
        add("reverb_size", "  tamanho da sala", 0, 100, " %", "Duração do reverb.")
        add("out_db", "Ganho de saída", -12, 12, " dB", "Nível final. No TX ajuste o ALC do rádio, não este controle.")
        lay.addLayout(form)
        self.chk_band = QtWidgets.QCheckBox("Limitar à faixa de voz SSB (300 a 2700 Hz)")
        self.chk_band.toggled.connect(self._emit)
        lay.addWidget(self.chk_band)
        note = QtWidgets.QLabel(tip)
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addStretch()
        self.set_settings(presets[self.cb.currentText()])

    def _emit(self) -> None:
        if not self._loading:
            self.changed.emit()

    def settings(self) -> FxSettings:
        s = FxSettings(**{f.name: getattr(FxSettings(), f.name) for f in fields(FxSettings)})
        for key, sl in self.ctl.items():
            setattr(s, key, float(sl.value()))
        s.band_on = self.chk_band.isChecked()
        return s

    def set_settings(self, s: FxSettings) -> None:
        self._loading = True
        for key, sl in self.ctl.items():
            sl.setValue(int(round(getattr(s, key))))
        self.chk_band.setChecked(s.band_on)
        self._loading = False
        self.changed.emit()


class VoiceTab(QtWidgets.QWidget):
    status = QtCore.Signal(str)           # da thread das chamadas para a interface
    suspended = QtCore.Signal(str)
    finished = QtCore.Signal()
    saved = QtCore.Signal(object, float)
    candidate = QtCore.Signal(object)
    message = QtCore.Signal(str)

    def __init__(self, settings: Settings, cty, get_state: Callable, hooks: dict) -> None:
        super().__init__()
        self.settings, self.cty, self.get_state, self.h = settings, cty, get_state, hooks
        self.cfg = settings.voice_cfg
        self.store = voice.MessageStore()
        self.vad = VoiceDetector()
        self.rx_fx = VoiceFX(PRESETS_RX["Natural"])
        self.rx_mon = voice.RxMonitor()
        self.live = voice.LiveVoice(self._levels)
        self.mic_watch = voice.MicWatcher()
        self.mic_cap = voice.MicCapture()
        self.recorder = voice.ConversationRecorder(lambda p, s: self.saved.emit(p, s))
        self.listener = callid.CallsignListener(cty, lambda c: self.candidate.emit(c))
        self.caller = voice.AutoCaller(self.h["ptt"], self._play, self.h["send_cw"], self.h["stop_cw"], lambda: self.vad.active,
                                       lambda: self.mic_watch.voice, self.status.emit, self.finished.emit,
                                       op_ptt=self._op_ptt, on_suspended=self.suspended.emit)
        self._pc_ptt = False
        self._radio_ptt = False
        self._talking = False
        self._dialog: Optional[QtWidgets.QMessageBox] = None
        self._meters = (-90.0, -90.0, 0.0)
        self._build()
        self.status.connect(self._set_status)
        self.suspended.connect(self._ask_resume)
        self.finished.connect(self._calls_finished)
        self.saved.connect(self._recording_saved)
        self.candidate.connect(self._show_candidate)
        self.message.connect(self.h["message"])
        self._load_cfg()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(200)

    # ------------------------------------------------------------ interface
    def _build(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        self.btn_rec = QtWidgets.QPushButton("●  GRAVAR CONVERSA")
        self.btn_rec.setCheckable(True)
        self.btn_rec.setStyleSheet(BIG)
        self.btn_rec.toggled.connect(self._rec_toggled)
        self.btn_talk = QtWidgets.QPushButton("🎙  FALAR (segure)")
        self.btn_talk.setStyleSheet(BIG + "background:#2e6b3a; color:white;")
        self.btn_talk.pressed.connect(lambda: self._talk(True))
        self.btn_talk.released.connect(lambda: self._talk(False))
        self.btn_test = QtWidgets.QPushButton("🎧  TESTAR MEU ÁUDIO (fones)")
        self.btn_test.setCheckable(True)
        self.btn_test.setStyleSheet(BIG)
        self.btn_test.toggled.connect(self._test_toggled)
        self.btn_stop = QtWidgets.QPushButton("■  PARAR TX")
        self.btn_stop.setStyleSheet(BIG + "background:#a02020; color:white;")
        self.btn_stop.clicked.connect(self.halt)
        for b in (self.btn_rec, self.btn_talk, self.btn_test, self.btn_stop):
            top.addWidget(b)
        root.addLayout(top)
        self.lbl_state = QtWidgets.QLabel("")
        self.lbl_state.setStyleSheet("font: 11pt;")
        root.addWidget(self.lbl_state)

        cols = QtWidgets.QHBoxLayout()
        root.addLayout(cols, 1)
        cols.addWidget(self._box_effects(), 4)
        cols.addWidget(self._box_record(), 3)
        cols.addWidget(self._box_calls(), 4)

    def _box_effects(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Efeitos de áudio")
        lay = QtWidgets.QVBoxLayout(box)
        tabs = QtWidgets.QTabWidget()
        lay.addWidget(tabs)
        self.fx_tx = FxPanel(PRESETS_TX, "TX: o que sai do seu microfone para o rádio. Para ser entendido em HF use "
                                          "'Compreensão DX'. Ajuste o ALC do rádio sem acionar.")
        self.fx_rx = FxPanel(PRESETS_RX, "RX: melhora o áudio recebido para você ouvir no PC (não altera o que o rádio recebe).")
        self.fx_tx.changed.connect(self._tx_fx_changed)
        self.fx_rx.changed.connect(lambda: self.rx_fx.configure(self.fx_rx.settings()))
        tabs.addTab(self.fx_tx, "Meu microfone (TX)")
        tabs.addTab(self.fx_rx, "Áudio recebido (RX)")
        form = QtWidgets.QFormLayout()
        self.cb_mic = QtWidgets.QComboBox()
        self.cb_mic.addItems([""] + audio.list_input_devices())
        self.cb_phones = QtWidgets.QComboBox()
        self.cb_phones.addItems([""] + audio.list_output_devices())
        self.chk_rxmon = QtWidgets.QCheckBox("Ouvir o áudio recebido melhorado nesta saída")
        self.chk_rxmon.toggled.connect(self._rxmon_toggled)
        self.sl_vol, lab = _slider(0, 100, 80, " %")
        self.sl_vol.valueChanged.connect(lambda v: setattr(self.rx_mon, "volume", v / 100))
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.sl_vol)
        row.addWidget(lab)
        form.addRow("Microfone do PC:", self.cb_mic)
        form.addRow("Fones/alto-falantes:", self.cb_phones)
        form.addRow(self.chk_rxmon)
        form.addRow("Volume:", row)
        lay.addLayout(form)
        self.bar_in, self.bar_out, self.bar_gr = (QtWidgets.QProgressBar() for _ in range(3))
        for bar, name, hi in ((self.bar_in, "Entrada", 90), (self.bar_out, "Saída", 90), (self.bar_gr, "Compressão", 24)):
            bar.setRange(0, hi)
            bar.setFormat(f"{name}  %v")
            bar.setTextVisible(True)
            lay.addWidget(bar)
        warn = QtWidgets.QLabel("Para falar pelo PC: no rádio, menu SET > Connectors > MOD Input, selecione USB para SSB. "
                                "Escolha como saída o 'USB Audio CODEC' só no TX; nos testes use fones.")
        warn.setWordWrap(True)
        lay.addWidget(warn)
        return box

    def _box_record(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Gravação das conversas")
        lay = QtWidgets.QVBoxLayout(box)
        self.chk_auto = QtWidgets.QCheckBox("Gravar automaticamente quando houver voz")
        self.chk_auto.toggled.connect(self._auto_toggled)
        lay.addWidget(self.chk_auto)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Sensibilidade da detecção:"))
        self.sl_sens = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.sl_sens.setRange(4, 20)
        self.sl_sens.setValue(9)
        self.sl_sens.setToolTip("Quantos dB acima do ruído para considerar voz. Menor = mais sensível.")
        self.sl_sens.valueChanged.connect(lambda v: setattr(self.vad, "margin_db", float(v)))
        row.addWidget(self.sl_sens)
        lay.addLayout(row)
        self.lbl_lamp = QtWidgets.QLabel("● canal livre")
        lay.addWidget(self.lbl_lamp)
        self.lst_rec = QtWidgets.QListWidget()
        lay.addWidget(self.lst_rec, 1)
        row = QtWidgets.QHBoxLayout()
        for text, slot in (("▶ Ouvir", self._play_recording), ("📁 Pasta", self._open_rec_dir), ("🗑 Excluir", self._del_recording)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        lay.addLayout(row)
        self._refresh_recordings()
        return box

    def _box_calls(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Mensagens e chamadas automáticas")
        lay = QtWidgets.QVBoxLayout(box)
        self.lst_msg = QtWidgets.QListWidget()
        lay.addWidget(self.lst_msg, 1)
        row = QtWidgets.QHBoxLayout()
        self.btn_recmsg = QtWidgets.QPushButton("🎙 Gravar voz")
        self.btn_recmsg.setCheckable(True)
        self.btn_recmsg.toggled.connect(self._recmsg_toggled)
        b_cw = QtWidgets.QPushButton("＋ Texto CW")
        b_cw.clicked.connect(self._new_cw)
        b_send = QtWidgets.QPushButton("▶ Enviar agora")
        b_send.clicked.connect(self._send_now)
        b_del = QtWidgets.QPushButton("🗑")
        b_del.clicked.connect(self._del_message)
        for b in (self.btn_recmsg, b_cw, b_send, b_del):
            row.addWidget(b)
        lay.addLayout(row)
        form = QtWidgets.QFormLayout()
        self.sp_gap = QtWidgets.QSpinBox()
        self.sp_gap.setRange(3, 900)
        self.sp_gap.setValue(20)
        self.sp_gap.setSuffix(" s")
        self.sp_gap.setToolTip("Tempo de escuta entre o fim de uma chamada e o início da próxima.")
        self.sp_clear = QtWidgets.QSpinBox()
        self.sp_clear.setRange(1, 30)
        self.sp_clear.setValue(3)
        self.sp_clear.setSuffix(" s")
        self.sp_clear.setToolTip("Canal livre exigido antes de cada chamada.")
        self.sp_max = QtWidgets.QSpinBox()
        self.sp_max.setRange(0, 999)
        self.sp_max.setSpecialValueText("até parar")
        self.sp_wpm = QtWidgets.QSpinBox()
        self.sp_wpm.setRange(5, 40)
        self.sp_wpm.setValue(20)
        self.sp_wpm.setSuffix(" wpm")
        self.sp_wpm.setToolTip("Velocidade do manipulador do rádio (só para estimar a duração do CW).")
        form.addRow("Intervalo entre chamadas:", self.sp_gap)
        form.addRow("Canal livre antes de chamar:", self.sp_clear)
        form.addRow("Repetições:", self.sp_max)
        form.addRow("Velocidade CW:", self.sp_wpm)
        lay.addLayout(form)
        self.chk_end = QtWidgets.QCheckBox("Encerrar tudo se alguém responder (voz no canal)")
        self.chk_end.setChecked(True)
        self.chk_abort_rx = QtWidgets.QCheckBox("Interromper a chamada se houver voz no receptor")
        self.chk_abort_rx.setChecked(True)
        self.chk_abort_mic = QtWidgets.QCheckBox("Interromper se eu falar no microfone do PC")
        self.chk_abort_mic.setChecked(True)
        for c in (self.chk_end, self.chk_abort_rx, self.chk_abort_mic):
            lay.addWidget(c)
        self.btn_calls = QtWidgets.QPushButton("▶  INICIAR CHAMADAS")
        self.btn_calls.setCheckable(True)
        self.btn_calls.setStyleSheet(BIG)
        self.btn_calls.toggled.connect(self._calls_toggled)
        lay.addWidget(self.btn_calls)
        self.lbl_calls = QtWidgets.QLabel("Parado.")
        self.lbl_calls.setWordWrap(True)
        lay.addWidget(self.lbl_calls)
        note = QtWidgets.QLabel("O PTT do operador (botão do app, microfone do rádio ou outro programa) suspende as chamadas e "
                                "pergunta se deve retomar.")
        note.setWordWrap(True)
        lay.addWidget(note)

        ident = QtWidgets.QGroupBox("Identificar indicativo pela voz (offline)")
        il = QtWidgets.QVBoxLayout(ident)
        self.chk_id = QtWidgets.QCheckBox("Tentar reconhecer o indicativo de quem fala (alfabeto fonético)")
        self.chk_id.toggled.connect(self._id_toggled)
        self.lbl_id = QtWidgets.QLabel("Desligado.")
        self.lbl_id.setWordWrap(True)
        row = QtWidgets.QHBoxLayout()
        self.btn_model = QtWidgets.QPushButton("Baixar modelo de voz")
        self.btn_model.clicked.connect(self._download_model)
        self.btn_useid = QtWidgets.QPushButton("Usar no log")
        self.btn_useid.clicked.connect(self._use_candidate)
        self.btn_useid.setEnabled(False)
        row.addWidget(self.btn_model)
        row.addWidget(self.btn_useid)
        il.addWidget(self.chk_id)
        il.addWidget(self.lbl_id)
        il.addLayout(row)
        lay.addWidget(ident)
        self._candidate: Optional[callid.Candidate] = None
        self._refresh_messages()
        return box

    # ------------------------------------------------------------ configuração salva
    def _load_cfg(self) -> None:
        c = self.cfg
        for cb, key in ((self.cb_mic, "mic"), (self.cb_phones, "phones")):
            i = cb.findText(c.get(key, ""))
            cb.setCurrentIndex(max(0, i))
        if c.get("tx_fx"):
            self.fx_tx.set_settings(FxSettings.from_dict(c["tx_fx"]))
        if c.get("rx_fx"):
            self.fx_rx.set_settings(FxSettings.from_dict(c["rx_fx"]))
        self.sp_gap.setValue(int(c.get("gap", 20)))
        self.sp_clear.setValue(int(c.get("clear", 3)))
        self.sp_wpm.setValue(int(c.get("wpm", 20)))
        self.rx_fx.configure(self.fx_rx.settings())

    def save_cfg(self) -> None:
        self.cfg.update(mic=self.cb_mic.currentText(), phones=self.cb_phones.currentText(), tx_fx=self.fx_tx.settings().to_dict(),
                        rx_fx=self.fx_rx.settings().to_dict(), gap=self.sp_gap.value(), clear=self.sp_clear.value(), wpm=self.sp_wpm.value())
        self.settings.save()

    # ------------------------------------------------------------ áudio recebido (thread de áudio)
    def feed(self, x: np.ndarray) -> None:
        active = self.vad.feed(x)
        self.recorder.feed(x, active)
        self.listener.feed(x, active)
        if self.rx_mon.running:
            self.rx_mon.push(self.rx_fx.process(x))

    # ------------------------------------------------------------ PTT do operador
    def on_radio_state(self, st) -> None:
        rising = st.ptt and not self._radio_ptt
        self._radio_ptt = st.ptt
        if rising and self.caller.running and not self.caller.is_own_tx() and not self._talking:
            self.caller.suspend("PTT acionado no rádio")

    def on_pc_ptt(self, on: bool) -> None:
        self._pc_ptt = on
        if on and self.caller.running and not self._talking:
            self.caller.suspend("PTT acionado no app")

    def _op_ptt(self) -> bool:
        return self._pc_ptt or self._talking or (self._radio_ptt and not self.caller.is_own_tx())

    def _ask_resume(self, reason: str) -> None:
        if self._dialog is not None:
            return
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Icon.Question)
        box.setWindowTitle("Chamadas suspensas")
        box.setText(f"{reason}. As chamadas automáticas foram suspensas.\n\nRetomar as chamadas?")
        yes = box.addButton("Retomar", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Encerrar chamadas", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(yes)
        box.setModal(False)  # não bloqueia: o operador continua usando o PTT
        self._dialog = box

        def done() -> None:
            self._dialog = None
            if box.clickedButton() is yes:
                self.caller.resume()
                self._set_status("Retomando: aguardando canal livre...")
            else:
                self.btn_calls.setChecked(False)
        box.finished.connect(lambda _=0: done())
        box.show()

    # ------------------------------------------------------------ botões
    def halt(self) -> None:
        """Para tudo o que transmite: chamadas, voz ao vivo e o PTT."""
        self.caller.stop()
        if self.btn_calls.isChecked():
            self.btn_calls.setChecked(False)
        self._talk(False)
        if self.btn_test.isChecked():
            self.btn_test.setChecked(False)
        try:
            self.h["ptt"](False)
            self.h["stop_cw"]()
        except Exception:  # noqa: BLE001
            pass

    def shutdown(self) -> None:
        self.halt()
        self.recorder.stop()
        self.listener.stop()
        self.live.stop()
        self.mic_watch.stop()
        self.rx_mon.stop()
        self.timer.stop()
        self.save_cfg()

    def _tx_fx_changed(self) -> None:
        if self.live.running:
            self.live.fx.configure(self.fx_tx.settings())

    def _levels(self, a: float, b: float, c: float) -> None:
        self._meters = (a, b, c)

    def _tick(self) -> None:
        a, b, c = self._meters
        self.bar_in.setValue(int(max(0, min(90, a + 90))))
        self.bar_out.setValue(int(max(0, min(90, b + 90))))
        self.bar_gr.setValue(int(max(0, min(24, c))))
        self.lbl_lamp.setText("● VOZ NO CANAL" if self.vad.active else "● canal livre")
        self.lbl_lamp.setStyleSheet("color:#d03030; font-weight:bold" if self.vad.active else "color:#3a9a4a")
        parts = []
        if self.recorder.recording:
            parts.append(f"GRAVANDO {self.recorder.seconds:.0f} s")
        if self.live.running:
            parts.append("microfone com efeitos ativo")
        if self.caller.running:
            parts.append("chamadas automáticas")
        self.lbl_state.setText(" · ".join(parts) if parts else "Pronto.")

    def _set_status(self, text: str) -> None:
        self.lbl_calls.setText(text)

    def _need_device(self, cb: QtWidgets.QComboBox, what: str) -> bool:
        if cb.currentText():
            return True
        QtWidgets.QMessageBox.information(self, "Fonia", f"Escolha {what} em 'Efeitos de áudio'.")
        return False

    def _voice_mode_ok(self) -> bool:
        st = self.get_state()
        if st.mode in ("USB", "LSB", "AM", "FM"):
            return True
        QtWidgets.QMessageBox.information(self, "Fonia", "Coloque o rádio em USB, LSB, AM ou FM para falar.")
        return False

    def _talk(self, on: bool) -> None:
        if on == self._talking:
            return
        if not on:
            self._talking = False
            if self.live.running and not self.btn_test.isChecked():
                self.live.stop()
                self.h["ptt"](False)
            return
        if self.caller.running:
            self.caller.suspend("Você acionou FALAR")
        if not (self.h["connected"]() and self._need_device(self.cb_mic, "o microfone")) or not self._voice_mode_ok():
            return
        if not self.h["sim"]() and not self.h["tx_guard"]("SSB"):
            return
        try:
            out = "" if self.h["sim"]() else (self.settings.audio_output or audio.find_radio_output())
            self.live.start(self.cb_mic.currentText(), out if not self.h["sim"]() else self.cb_phones.currentText(), self.fx_tx.settings())
        except Exception as exc:  # noqa: BLE001
            self.message.emit(f"Voz ao vivo: {exc}")
            return
        self._talking = True
        self.h["ptt"](True)

    def _test_toggled(self, on: bool) -> None:
        if on:
            if not self._need_device(self.cb_mic, "o microfone") or not self._need_device(self.cb_phones, "os fones"):
                self.btn_test.setChecked(False)
                return
            try:
                self.live.start(self.cb_mic.currentText(), self.cb_phones.currentText(), self.fx_tx.settings())
            except Exception as exc:  # noqa: BLE001
                self.message.emit(f"Teste de áudio: {exc}")
                self.btn_test.setChecked(False)
        elif not self._talking:
            self.live.stop()

    def _rxmon_toggled(self, on: bool) -> None:
        if on:
            dev = self.cb_phones.currentText()
            if not dev or "USB Audio CODEC" in dev:
                QtWidgets.QMessageBox.information(self, "Fonia", "Escolha fones ou alto-falantes do PC (não o 'USB Audio CODEC').")
                self.chk_rxmon.setChecked(False)
                return
            try:
                self.rx_mon.start(dev)
            except Exception as exc:  # noqa: BLE001
                self.message.emit(f"Monitor RX: {exc}")
                self.chk_rxmon.setChecked(False)
        else:
            self.rx_mon.stop()

    # ------------------------------------------------------------ gravação
    def _label(self) -> str:
        st = self.get_state()
        return f"{st.freq / 1e6:.4f}MHz_{st.mode}"

    def _rec_toggled(self, on: bool) -> None:
        self.recorder.label = self._label()
        self.recorder.set_mode("manual" if on else ("auto" if self.chk_auto.isChecked() else "off"))
        self.btn_rec.setText("■  PARAR GRAVAÇÃO" if on else "●  GRAVAR CONVERSA")

    def _auto_toggled(self, on: bool) -> None:
        if not self.btn_rec.isChecked():
            self.recorder.label = self._label()
            self.recorder.set_mode("auto" if on else "off")

    def _recording_saved(self, path, secs: float) -> None:
        self._refresh_recordings()
        self.message.emit(f"Gravação salva: {path.name} ({secs:.0f} s)")

    def _refresh_recordings(self) -> None:
        self.lst_rec.clear()
        for p in sorted(voice.recordings_dir().glob("*.wav"), reverse=True)[:100]:
            item = QtWidgets.QListWidgetItem(p.stem)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, str(p))
            self.lst_rec.addItem(item)

    def _selected_recording(self) -> Optional[str]:
        it = self.lst_rec.currentItem()
        return it.data(QtCore.Qt.ItemDataRole.UserRole) if it else None

    def _play_recording(self) -> None:
        path = self._selected_recording()
        if path:
            import sounddevice as sd

            from pathlib import Path
            sd.play(voice.read_wav(Path(path)), audio.FS, device=audio.resolve_device(self.cb_phones.currentText(), "output"))

    def _open_rec_dir(self) -> None:
        folder = voice.recordings_dir()
        if hasattr(os, "startfile"):
            os.startfile(folder)  # noqa: S606 (pasta do próprio app)
        else:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(folder)))

    def _del_recording(self) -> None:
        path = self._selected_recording()
        if path and QtWidgets.QMessageBox.question(self, "Excluir", "Excluir esta gravação?") == QtWidgets.QMessageBox.StandardButton.Yes:
            try:
                os.remove(path)
            except OSError:
                pass
            self._refresh_recordings()

    # ------------------------------------------------------------ mensagens
    def _refresh_messages(self) -> None:
        self.lst_msg.clear()
        for m in self.store.items:
            icon = "🎙" if m.kind == "voz" else "〰"
            item = QtWidgets.QListWidgetItem(f"{icon} {m.name}" + (f"  —  {m.text}" if m.kind == "cw" else ""))
            item.setData(QtCore.Qt.ItemDataRole.UserRole, m.id)
            self.lst_msg.addItem(item)
        if self.lst_msg.count():
            self.lst_msg.setCurrentRow(0)

    def _recmsg_toggled(self, on: bool) -> None:
        if on:
            if not self._need_device(self.cb_mic, "o microfone"):
                self.btn_recmsg.setChecked(False)
                return
            try:
                self.mic_cap.start(self.cb_mic.currentText())
            except Exception as exc:  # noqa: BLE001
                self.message.emit(f"Gravação: {exc}")
                self.btn_recmsg.setChecked(False)
                return
            self.btn_recmsg.setText("■ Parar e salvar")
            return
        self.btn_recmsg.setText("🎙 Gravar voz")
        data = self.mic_cap.stop()
        if len(data) < audio.FS // 2:
            self.message.emit("Gravação muito curta, descartada.")
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Nova mensagem de voz", "Nome da mensagem:", text=f"CQ {self.settings.callsign}".strip())
        if ok and name.strip():
            self.store.add_voice(name.strip(), data)
            self._refresh_messages()

    def _new_cw(self) -> None:
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Nova mensagem em CW")
        form = QtWidgets.QFormLayout(dlg)
        ed_name = QtWidgets.QLineEdit("CQ CW")
        ed_text = QtWidgets.QLineEdit(f"CQ CQ CQ DE {self.settings.callsign or '{call}'} {self.settings.callsign or '{call}'} K")
        form.addRow("Nome:", ed_name)
        form.addRow("Texto:", ed_text)
        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)
        if dlg.exec() and ed_text.text().strip():
            self.store.add_cw(ed_name.text().strip() or "CW", ed_text.text().strip())
            self._refresh_messages()

    def _del_message(self) -> None:
        mid = self._selected_message_id()
        if mid and QtWidgets.QMessageBox.question(self, "Excluir", "Excluir esta mensagem?") == QtWidgets.QMessageBox.StandardButton.Yes:
            self.store.remove(mid)
            self._refresh_messages()

    def _selected_message_id(self) -> Optional[str]:
        it = self.lst_msg.currentItem()
        return it.data(QtCore.Qt.ItemDataRole.UserRole) if it else None

    def _current_message(self) -> Optional[voice.Message]:
        mid = self._selected_message_id()
        if not mid:
            QtWidgets.QMessageBox.information(self, "Fonia", "Grave ou crie uma mensagem primeiro.")
            return None
        return self.store.get(mid)

    def _prepare(self, msg: voice.Message) -> Optional[np.ndarray]:
        if msg.kind == "cw":
            return None
        return voice.prepare_for_tx(self.store.samples(msg), self.fx_tx.settings())

    def _play(self, samples: np.ndarray, should_stop: Callable[[], bool]) -> bool:  # thread das chamadas
        if self.h["sim"]():
            end = time.time() + len(samples) / audio.FS
            while time.time() < end:
                if should_stop():
                    return False
                time.sleep(0.05)
            return True
        return audio.play_chunked(samples, self.settings.audio_output or audio.find_radio_output(), should_stop)

    def _check_ready(self, msg: voice.Message) -> bool:
        if not self.h["connected"]():
            QtWidgets.QMessageBox.information(self, "Fonia", "Conecte ao rádio (ou ao simulador) antes.")
            return False
        st = self.get_state()
        if msg.kind == "cw":
            if st.mode not in ("CW", "CW-R"):
                QtWidgets.QMessageBox.information(self, "Fonia", "Coloque o rádio em CW para enviar mensagens em CW.")
                return False
            category = "CW"
        else:
            if st.mode not in ("USB", "LSB", "AM", "FM"):
                QtWidgets.QMessageBox.information(self, "Fonia", "Coloque o rádio em USB, LSB, AM ou FM para enviar voz.")
                return False
            category = "SSB"
        return self.h["sim"]() or self.h["tx_guard"](category)

    def _send_now(self) -> None:
        msg = self._current_message()
        if not msg or not self._check_ready(msg):
            return
        plan = voice.CallPlan(gap_s=1, clear_s=0.1, max_calls=1, end_on_voice=False, wpm=self.sp_wpm.value(),
                              abort_on_mic_voice=False, abort_on_rx_voice=False)
        self._start_calls(msg, plan)

    # ------------------------------------------------------------ chamadas automáticas
    def _plan(self) -> voice.CallPlan:
        return voice.CallPlan(gap_s=float(self.sp_gap.value()), clear_s=float(self.sp_clear.value()), max_calls=self.sp_max.value(),
                              end_on_voice=self.chk_end.isChecked(), abort_on_rx_voice=self.chk_abort_rx.isChecked(),
                              abort_on_mic_voice=self.chk_abort_mic.isChecked() and bool(self.cb_mic.currentText()),
                              wpm=self.sp_wpm.value())

    def _start_calls(self, msg: voice.Message, plan: voice.CallPlan) -> None:
        samples = self._prepare(msg)
        if plan.abort_on_mic_voice:
            try:
                self.mic_watch.start(self.cb_mic.currentText())
            except Exception as exc:  # noqa: BLE001
                self.message.emit(f"Microfone: {exc}")
        self.caller.start(msg, samples, plan)

    def _calls_toggled(self, on: bool) -> None:
        if not on:
            self.caller.stop()
            self.mic_watch.stop()
            self.btn_calls.setText("▶  INICIAR CHAMADAS")
            if self._dialog is not None:
                self._dialog.close()
            return
        msg = self._current_message()
        if not msg or not self._check_ready(msg):
            self.btn_calls.setChecked(False)
            return
        if not self.h["sim"]():
            ok = QtWidgets.QMessageBox.question(
                self, "Chamadas automáticas",
                "O rádio vai TRANSMITIR automaticamente, repetidas vezes, enquanto o canal estiver livre.\n\n"
                "Confirme: frequência livre e permitida, antena ou carga conectada, ALC sem acionar, e fique ao lado do rádio. "
                "O PTT ou o botão PARAR TX interrompem.\n\nIniciar?")
            if ok != QtWidgets.QMessageBox.StandardButton.Yes:
                self.btn_calls.setChecked(False)
                return
        self.btn_calls.setText("■  PARAR CHAMADAS")
        self.vad.reset()
        self._start_calls(msg, self._plan())

    def _calls_finished(self) -> None:
        self.mic_watch.stop()
        if self.btn_calls.isChecked():
            self.btn_calls.blockSignals(True)
            self.btn_calls.setChecked(False)
            self.btn_calls.blockSignals(False)
            self.btn_calls.setText("▶  INICIAR CHAMADAS")

    # ------------------------------------------------------------ identificação do indicativo
    def _id_toggled(self, on: bool) -> None:
        if not on:
            self.listener.stop()
            self.lbl_id.setText("Desligado.")
            return
        try:
            self.listener.start()
            self.lbl_id.setText(self.listener.status + ". Funciona melhor com o alfabeto fonético, falado devagar.")
        except RuntimeError as exc:
            self.lbl_id.setText(str(exc))
            self.chk_id.blockSignals(True)
            self.chk_id.setChecked(False)
            self.chk_id.blockSignals(False)

    def _download_model(self) -> None:
        if not callid.engine_available():
            QtWidgets.QMessageBox.information(
                self, "Reconhecedor offline",
                "O reconhecedor de voz offline (Vosk) não está instalado neste computador.\n\n"
                "Se você roda pelo código, instale com: pip install vosk. A versão do instalador já o inclui.")
            return
        ok = QtWidgets.QMessageBox.question(
            self, "Baixar modelo de voz",
            "Baixar o modelo pequeno de voz em inglês (cerca de 40 MB) de alphacephei.com?\n\n"
            "É só uma vez; depois o reconhecimento funciona sem internet. O modelo fica em %APPDATA%\\IC7300App\\modelos.")
        if ok != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self.btn_model.setEnabled(False)
        self.lbl_id.setText("Baixando o modelo...")
        QtWidgets.QApplication.processEvents()
        try:
            callid.download_model("en", lambda p: (self.lbl_id.setText(f"Baixando o modelo... {p}%"), QtWidgets.QApplication.processEvents()))
            self.lbl_id.setText("Modelo instalado. Marque a opção acima para ligar.")
        except Exception as exc:  # noqa: BLE001
            self.lbl_id.setText(f"Falha ao baixar: {exc}")
        self.btn_model.setEnabled(True)

    def _show_candidate(self, cand: callid.Candidate) -> None:
        self._candidate = cand
        self.btn_useid.setEnabled(True)
        self.lbl_id.setText(f"Ouvi: {cand.label()}. Confirme de ouvido antes de usar.")

    def _use_candidate(self) -> None:
        if self._candidate:
            self.h["use_call"](self._candidate.call)
            QtWidgets.QApplication.clipboard().setText(self._candidate.call)
            self.message.emit(f"{self._candidate.call} copiado e enviado ao log.")
