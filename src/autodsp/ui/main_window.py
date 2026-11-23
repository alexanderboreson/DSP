"""Huvudfönster: Dashboard, Equalizer, Analyzer och Preset Manager (Fas 1).

GUI:t innehåller ingen signalbehandling. Alla ändringar går via `_commit`, som först
låter AudioEngine/Safety Engine validera och därefter sparar i SettingsStore.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QTableWidget,
    QVBoxLayout,
    QWidget,
    QTabWidget,
    QHeaderView,
)

from ..analysis import compute_spectrum_db
from ..audio.engine import AudioBackendUnavailable, AudioEngine, SettingsRejected
from ..dsp.params import ChainSettings, EQBand
from ..presets import PresetError, PresetLibrary
from ..safety import SafetyError, Severity
from ..store import SettingsStore
from .theme import COLORS
from .widgets import EqGraph, LevelMeter, SpectrumPlot

log = logging.getLogger(__name__)

KIND_LABELS = {"peak": "Peak/Bell", "low_shelf": "Low Shelf", "high_shelf": "High Shelf"}
KINDS = list(KIND_LABELS)
SEVERITY_COLORS = {
    Severity.INFO: COLORS["muted"],
    Severity.WARNING: COLORS["orange"],
    Severity.CRITICAL: COLORS["red"],
}


def _spin(lo: float, hi: float, value: float, step: float, decimals: int, suffix: str = "") -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setSuffix(suffix)
    s.setValue(value)
    s.setKeyboardTracking(False)
    return s


def _group(title: str, layout) -> QGroupBox:
    box = QGroupBox(title)
    box.setLayout(layout)
    return box


class MainWindow(QMainWindow):
    def __init__(
        self,
        engine: AudioEngine,
        store: SettingsStore,
        library: PresetLibrary,
        autosave_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.engine = engine
        self.store = store
        self.library = library
        self.autosave_path = autosave_path
        self._building = False
        self.setWindowTitle("AutoDSP Studio")

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addLayout(self._build_top_bar())
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_dashboard(), "Dashboard")
        self.tabs.addTab(self._build_eq_tab(), "Equalizer")
        self.analyzer_tab = self._build_analyzer_tab()
        self.tabs.addTab(self.analyzer_tab, "Analyzer")
        self.tabs.addTab(self._build_presets_tab(), "Presets")
        layout.addWidget(self.tabs)
        self.setCentralWidget(root)
        self.statusBar().showMessage("Redo. Utgången är avstängd (säker start).")

        QShortcut(QKeySequence("Ctrl+M"), self).activated.connect(self._emergency)
        QShortcut(QKeySequence("Ctrl+Z"), self).activated.connect(self._undo)
        QShortcut(QKeySequence("Ctrl+Y"), self).activated.connect(self._redo)

        self._refresh_devices()
        self._sync_widgets()
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ------------------------------------------------------------------
    # Uppbyggnad
    # ------------------------------------------------------------------
    def _build_top_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        title = QLabel("AutoDSP Studio")
        title.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {COLORS['cyan']};")
        bar.addWidget(title)
        bar.addStretch(1)
        self.output_status = QLabel()
        self.output_status.setStyleSheet("font-weight: 600;")
        bar.addWidget(self.output_status)
        self.arm_button = QPushButton("Aktivera utgång…")
        self.arm_button.setObjectName("arm")
        self.arm_button.clicked.connect(self._arm_or_disarm)
        bar.addWidget(self.arm_button)
        self.emergency_button = QPushButton("NÖDSTOPP (Ctrl+M)")
        self.emergency_button.setObjectName("emergency")
        self.emergency_button.clicked.connect(self._emergency)
        bar.addWidget(self.emergency_button)
        return bar

    def _build_dashboard(self) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)

        # Ljudenhet
        dev = QGridLayout()
        self.device_combo = QComboBox()
        refresh = QPushButton("Uppdatera lista")
        refresh.clicked.connect(self._refresh_devices)
        self.start_button = QPushButton("Starta ljudmotor")
        self.start_button.clicked.connect(self._start_engine)
        self.engine_label = QLabel("Ljudmotor: stoppad")
        dev.addWidget(QLabel("Utgångsenhet:"), 0, 0)
        dev.addWidget(self.device_combo, 0, 1)
        dev.addWidget(refresh, 0, 2)
        dev.addWidget(self.start_button, 1, 1)
        dev.addWidget(self.engine_label, 2, 0, 1, 3)
        grid.addWidget(_group("Ljudenhet", dev), 0, 0)

        # Fil och transport
        tr = QGridLayout()
        open_btn = QPushButton("Öppna ljudfil…")
        open_btn.clicked.connect(self._open_file)
        self.file_label = QLabel("Ingen fil vald")
        self.play_btn = QPushButton("▶ Spela")
        self.pause_btn = QPushButton("⏸ Paus")
        self.stop_btn = QPushButton("⏹ Stopp")
        self.play_btn.clicked.connect(self._play)
        self.pause_btn.clicked.connect(self.engine.pause)
        self.stop_btn.clicked.connect(self.engine.halt)
        self.pos_slider = QSlider(Qt.Orientation.Horizontal)
        self.pos_slider.setRange(0, 1000)
        self.pos_slider.sliderReleased.connect(self._seek)
        self.time_label = QLabel("0:00 / 0:00")
        self.loop_check = QCheckBox("Loop")
        self.loop_check.toggled.connect(self.engine.set_loop)
        tr.addWidget(open_btn, 0, 0)
        tr.addWidget(self.file_label, 0, 1, 1, 3)
        tr.addWidget(self.play_btn, 1, 0)
        tr.addWidget(self.pause_btn, 1, 1)
        tr.addWidget(self.stop_btn, 1, 2)
        tr.addWidget(self.loop_check, 1, 3)
        tr.addWidget(self.pos_slider, 2, 0, 1, 3)
        tr.addWidget(self.time_label, 2, 3)
        grid.addWidget(_group("Fil och uppspelning", tr), 1, 0)

        # Nivåer
        lv = QGridLayout()
        self.meter_in = LevelMeter(2)
        self.meter_out = LevelMeter(2)
        lv.addWidget(QLabel("Ingång (dBFS)"), 0, 0, Qt.AlignmentFlag.AlignHCenter)
        lv.addWidget(QLabel("Utgång (dBFS)"), 0, 1, Qt.AlignmentFlag.AlignHCenter)
        lv.addWidget(self.meter_in, 1, 0)
        lv.addWidget(self.meter_out, 1, 1)
        self.gr_label = QLabel("Limiter GR: 0.0 dB")
        self.latency_label = QLabel("")
        lv.addWidget(self.gr_label, 2, 0, 1, 2)
        lv.addWidget(self.latency_label, 3, 0, 1, 2)
        grid.addWidget(_group("Digitala nivåer", lv), 0, 1, 2, 1)

        # Reglage
        ctl = QGridLayout()
        self.master_slider = QSlider(Qt.Orientation.Horizontal)
        self.master_slider.setRange(-800, 60)
        self.master_slider.valueChanged.connect(self._on_master_slider)
        self.master_spin = _spin(-80, 6, -12, 0.5, 1, " dB")
        self.master_spin.valueChanged.connect(lambda v: self._set_field("master_gain_db", v, "master"))
        self.input_spin = _spin(-60, 12, 0, 0.5, 1, " dB")
        self.input_spin.valueChanged.connect(lambda v: self._set_field("input_gain_db", v, "input"))
        self.limiter_spin = _spin(-24, -0.1, -1, 0.5, 1, " dBFS")
        self.limiter_spin.valueChanged.connect(lambda v: self._set_field("limiter_threshold_db", v, "limthr"))
        self.release_spin = _spin(10, 1000, 100, 10, 0, " ms")
        self.release_spin.valueChanged.connect(lambda v: self._set_field("limiter_release_ms", v, "limrel"))
        self.mute_check = QCheckBox("Mute")
        self.mute_check.toggled.connect(lambda v: self._set_field("mute", v, None))
        self.bypass_check = QCheckBox("Förbikoppla EQ (jämför)")
        self.bypass_check.toggled.connect(lambda v: self._set_field("eq_bypass", v, None))
        rows = [
            ("Mastervolym", self.master_slider, self.master_spin),
            ("Ingångsförstärkning", None, self.input_spin),
            ("Limiter-tak", None, self.limiter_spin),
            ("Limiter-release", None, self.release_spin),
        ]
        for r, (name, slider, spin) in enumerate(rows):
            ctl.addWidget(QLabel(name), r, 0)
            if slider is not None:
                ctl.addWidget(slider, r, 1)
            ctl.addWidget(spin, r, 2)
        ctl.addWidget(self.mute_check, 4, 0)
        ctl.addWidget(self.bypass_check, 4, 1, 1, 2)
        self.undo_btn = QPushButton("Ångra")
        self.redo_btn = QPushButton("Gör om")
        self.ab_btn = QPushButton("A/B: A")
        self.undo_btn.clicked.connect(self._undo)
        self.redo_btn.clicked.connect(self._redo)
        self.ab_btn.clicked.connect(self._toggle_ab)
        hb = QHBoxLayout()
        for b in (self.undo_btn, self.redo_btn, self.ab_btn):
            hb.addWidget(b)
        ctl.addLayout(hb, 5, 0, 1, 3)
        grid.addWidget(_group("Reglage", ctl), 2, 0)

        # Säkerhet
        sf = QVBoxLayout()
        self.safety_list = QListWidget()
        sf.addWidget(self.safety_list)
        grid.addWidget(_group("Säkerhetsstatus (beräknad, ej uppmätt)", sf), 2, 1)
        grid.setRowStretch(2, 1)
        return page

    def _build_eq_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        self.eq_graph = EqGraph(self.engine.fs)
        self.eq_graph.bandMoved.connect(self._on_graph_move)
        lay.addWidget(self.eq_graph, 3)
        note = QLabel(
            "Kurvan är en beräknad filterrespons (matematisk modell) – inte en mätning. "
            "Dra punkterna med musen eller skriv exakta värden i tabellen."
        )
        note.setStyleSheet(f"color: {COLORS['muted']};")
        lay.addWidget(note)
        self.eq_table = QTableWidget(0, 5)
        self.eq_table.setHorizontalHeaderLabels(["Typ", "Frekvens", "Förstärkning", "Q", "På"])
        self.eq_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.eq_table.verticalHeader().setDefaultSectionSize(34)
        lay.addWidget(self.eq_table, 2)
        reset = QPushButton("Nollställ EQ (alla band 0 dB)")
        reset.clicked.connect(self._reset_eq)
        lay.addWidget(reset)
        return page

    def _build_analyzer_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        self.spectrum = SpectrumPlot()
        lay.addWidget(self.spectrum)
        info = QLabel(
            "FFT-spektrum av den digitala utsignalen efter DSP och limiter (dBFS). "
            "Mikrofonbaserad akustisk mätning ingår inte i Fas 1."
        )
        info.setStyleSheet(f"color: {COLORS['muted']};")
        lay.addWidget(info)
        return page

    def _build_presets_tab(self) -> QWidget:
        page = QWidget()
        lay = QGridLayout(page)
        self.preset_list = QListWidget()
        self.preset_name = QLineEdit()
        self.preset_name.setPlaceholderText("Presetnamn")
        buttons = [
            ("Spara", self._preset_save),
            ("Ladda", self._preset_load),
            ("Ta bort", self._preset_delete),
            ("Importera…", self._preset_import),
            ("Exportera…", self._preset_export),
            ("Fabriksinställningar", self._factory_reset),
        ]
        lay.addWidget(self.preset_list, 0, 0, len(buttons) + 1, 1)
        lay.addWidget(self.preset_name, 0, 1)
        for i, (label, fn) in enumerate(buttons, start=1):
            b = QPushButton(label)
            b.clicked.connect(fn)
            lay.addWidget(b, i, 1)
        lay.setColumnStretch(0, 2)
        lay.setColumnStretch(1, 1)
        self.preset_list.itemClicked.connect(lambda it: self.preset_name.setText(it.text()))
        self._refresh_presets()
        return page

    # ------------------------------------------------------------------
    # Inställningsflöde
    # ------------------------------------------------------------------
    def _commit(self, factory, key: str | None = None) -> None:
        """Bygger ny inställning, låter motorn validera den och sparar den i storen."""
        if self._building:
            return
        try:
            new = factory(self.store.current)
            self.engine.apply_settings(new)
        except SettingsRejected as exc:
            self.statusBar().showMessage(str(exc), 8000)
            self._sync_widgets()
            return
        except ValueError as exc:  # inkl. pydantic.ValidationError
            self.statusBar().showMessage(f"Ogiltigt värde: {exc}", 8000)
            self._sync_widgets()
            return
        self.store.set(new, coalesce_key=key)
        self._sync_widgets()

    def _set_field(self, name: str, value, key: str | None) -> None:
        self._commit(lambda s: s.replace(**{name: value}), key)

    def _apply_store(self) -> None:
        """Skickar storens aktuella värde till motorn (ångra/gör om, A/B, preset)."""
        try:
            self.engine.apply_settings(self.store.current)
        except (SettingsRejected, ValueError) as exc:
            self.statusBar().showMessage(str(exc), 8000)
        self._sync_widgets()

    def _on_master_slider(self, value: int) -> None:
        if not self._building:
            self._set_field("master_gain_db", value / 10.0, "master")

    def _on_graph_move(self, index: int, freq: float, gain: float, finished: bool) -> None:
        def build(s: ChainSettings) -> ChainSettings:
            old = s.eq_bands[index]
            return s.with_band(index, old.__class__(**{**old.model_dump(), "freq_hz": freq, "gain_db": gain}))

        self._commit(build, f"drag{index}")

    def _on_band_field(self, index: int, field: str, value) -> None:
        def build(s: ChainSettings) -> ChainSettings:
            old = s.eq_bands[index]
            return s.with_band(index, EQBand(**{**old.model_dump(), field: value}))

        self._commit(build, f"band{index}{field}")

    def _reset_eq(self) -> None:
        from ..dsp.params import default_bands

        self._commit(lambda s: s.replace(eq_bands=default_bands()), None)

    def _undo(self) -> None:
        if self.store.undo():
            self._apply_store()

    def _redo(self) -> None:
        if self.store.redo():
            self._apply_store()

    def _toggle_ab(self) -> None:
        self.store.toggle_ab()
        self._apply_store()

    # ------------------------------------------------------------------
    # Synkning store -> widgets
    # ------------------------------------------------------------------
    def _sync_widgets(self) -> None:
        s = self.store.current
        self._building = True
        try:
            def setv(widget, value):
                if isinstance(widget, QDoubleSpinBox):
                    if abs(widget.value() - value) > 1e-9:
                        widget.setValue(value)
                elif isinstance(widget, QCheckBox):
                    if widget.isChecked() != value:
                        widget.setChecked(value)

            setv(self.master_spin, s.master_gain_db)
            setv(self.input_spin, s.input_gain_db)
            setv(self.limiter_spin, s.limiter_threshold_db)
            setv(self.release_spin, s.limiter_release_ms)
            setv(self.mute_check, s.mute)
            setv(self.bypass_check, s.eq_bypass)
            tenth = int(round(s.master_gain_db * 10))
            if self.master_slider.value() != tenth:
                self.master_slider.setValue(tenth)
            self.undo_btn.setEnabled(self.store.can_undo)
            self.redo_btn.setEnabled(self.store.can_redo)
            self.ab_btn.setText(f"A/B: {self.store.active_slot}")
            self.eq_graph.set_fs(self.engine.fs)
            self.eq_graph.set_bands(s.eq_bands)
            self._sync_table(s)
        finally:
            self._building = False
        self._refresh_safety()

    def _sync_table(self, s: ChainSettings) -> None:
        if self.eq_table.rowCount() != len(s.eq_bands):
            self.eq_table.setRowCount(len(s.eq_bands))
            for i in range(len(s.eq_bands)):
                kind = QComboBox()
                for k in KINDS:
                    kind.addItem(KIND_LABELS[k], k)
                kind.currentIndexChanged.connect(
                    lambda _idx, i=i, c=kind: self._on_band_field(i, "kind", c.currentData())
                )
                freq = _spin(20, 20000, 1000, 10, 1, " Hz")
                freq.valueChanged.connect(lambda v, i=i: self._on_band_field(i, "freq_hz", v))
                gain = _spin(-24, 24, 0, 0.5, 1, " dB")
                gain.valueChanged.connect(lambda v, i=i: self._on_band_field(i, "gain_db", v))
                q = _spin(0.1, 20, 1, 0.1, 2)
                q.valueChanged.connect(lambda v, i=i: self._on_band_field(i, "q", v))
                on = QCheckBox()
                on.toggled.connect(lambda v, i=i: self._on_band_field(i, "enabled", v))
                for col, w in enumerate((kind, freq, gain, q, on)):
                    self.eq_table.setCellWidget(i, col, w)
        for i, b in enumerate(s.eq_bands):
            kind, freq, gain, q, on = (self.eq_table.cellWidget(i, c) for c in range(5))
            idx = KINDS.index(b.kind)
            if kind.currentIndex() != idx:
                kind.setCurrentIndex(idx)
            for w, v in ((freq, b.freq_hz), (gain, b.gain_db), (q, b.q)):
                if abs(w.value() - v) > 1e-9:
                    w.setValue(v)
            if on.isChecked() != b.enabled:
                on.setChecked(b.enabled)

    def _refresh_safety(self) -> None:
        report = self.engine.evaluate(self.store.current)
        self.safety_list.clear()
        header = QListWidgetItem(f"Beräknad max digital förstärkning: {report.predicted_peak_gain_db:+.1f} dB")
        header.setForeground(QColor(COLORS["text"]))
        self.safety_list.addItem(header)
        for issue in report.issues:
            item = QListWidgetItem(f"[{issue.severity.name}] {issue.message}")
            item.setForeground(QColor(SEVERITY_COLORS[issue.severity]))
            self.safety_list.addItem(item)
        disc = QListWidgetItem(report.disclaimer)
        disc.setForeground(QColor(COLORS["muted"]))
        self.safety_list.addItem(disc)

    # ------------------------------------------------------------------
    # Ljudenhet, fil och transport
    # ------------------------------------------------------------------
    def _refresh_devices(self) -> None:
        self.device_combo.clear()
        self.device_combo.addItem("Systemets standardenhet", None)
        try:
            for d in AudioEngine.list_output_devices():
                self.device_combo.addItem(f"{d.name}  [{d.hostapi}]", d.index)
        except AudioBackendUnavailable as exc:
            self.statusBar().showMessage(str(exc), 10000)
        except Exception as exc:  # noqa: BLE001
            log.exception("Kunde inte lista enheter")
            self.statusBar().showMessage(f"Kunde inte lista ljudenheter: {exc}", 10000)

    def _start_engine(self) -> None:
        try:
            self.engine.start(device=self.device_combo.currentData())
        except AudioBackendUnavailable as exc:
            QMessageBox.critical(self, "Ljudmotor", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("Kunde inte starta ljudmotorn")
            QMessageBox.critical(self, "Ljudmotor", f"Kunde inte starta ljudmotorn:\n{exc}")
            return
        self.engine_label.setText(f"Ljudmotor igång @ {self.engine.fs} Hz (utgången är fortfarande avstängd)")
        self.start_button.setText("Starta om ljudmotor")
        self._sync_widgets()

    def _open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Öppna ljudfil", "", "Ljud (*.wav *.flac *.ogg *.aiff *.aif);;Alla filer (*)"
        )
        if not path:
            return
        try:
            self.engine.load_file(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Ljudfil", f"Kunde inte läsa filen:\n{exc}")
            return
        self.file_label.setText(self.engine.file_name or "")

    def _play(self) -> None:
        if self.engine.core is None:
            self.statusBar().showMessage("Starta ljudmotorn först.", 5000)
            return
        if not self.engine.safety.gate_open:
            self.statusBar().showMessage("Utgången är avstängd. Klicka 'Aktivera utgång…' först.", 6000)
            return
        self.engine.play()

    def _seek(self) -> None:
        core = self.engine.core
        if core is not None and core.duration_s > 0:
            self.engine.seek_seconds(core.duration_s * self.pos_slider.value() / 1000.0)

    # ------------------------------------------------------------------
    # Säkerhet
    # ------------------------------------------------------------------
    def _arm_or_disarm(self) -> None:
        if self.engine.safety.armed:
            self.engine.safety.disarm("Utgången avstängd av användaren.")
            return
        if self.engine.core is None:
            self.statusBar().showMessage("Starta ljudmotorn innan utgången aktiveras.", 6000)
            return
        report = self.engine.evaluate()
        lines = [f"Beräknad max digital förstärkning: {report.predicted_peak_gain_db:+.1f} dB", ""]
        lines += [f"[{i.severity.name}] {i.message}" for i in report.issues]
        lines += ["", report.disclaimer]
        box = QMessageBox(self)
        box.setWindowTitle("Säkerhetsutlåtande")
        box.setIcon(QMessageBox.Icon.Warning if report.has_warning else QMessageBox.Icon.Information)
        box.setText("Granska innan utgången aktiveras. Sänk volymen på förstärkaren först.")
        box.setInformativeText("\n".join(lines))
        activate = None
        if not report.has_critical:
            activate = box.addButton("Jag har granskat – aktivera", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Avbryt", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if activate is not None and box.clickedButton() is activate:
            try:
                self.engine.arm()
            except SafetyError as exc:
                self.statusBar().showMessage(str(exc), 8000)

    def _emergency(self) -> None:
        self.engine.emergency_mute()
        self.statusBar().showMessage("NÖDSTOPP aktiverat – utgången är avstängd.", 8000)

    # ------------------------------------------------------------------
    # Presets
    # ------------------------------------------------------------------
    def _refresh_presets(self) -> None:
        self.preset_list.clear()
        self.preset_list.addItems(self.library.list_names())

    def _selected_preset(self) -> str | None:
        item = self.preset_list.currentItem()
        name = item.text() if item else self.preset_name.text().strip()
        return name or None

    def _preset_save(self) -> None:
        name = self.preset_name.text().strip()
        if not name:
            self.statusBar().showMessage("Ange ett presetnamn.", 4000)
            return
        try:
            self.library.save(name, self.store.current)
        except (PresetError, OSError) as exc:
            QMessageBox.warning(self, "Preset", str(exc))
            return
        self._refresh_presets()
        self.statusBar().showMessage(f"Preset '{name}' sparad.", 4000)

    def _load_settings(self, settings: ChainSettings) -> None:
        """Byte av preset: motorn tonar ned/upp vid stora nivåskillnader."""
        try:
            self.engine.apply_settings(settings)
        except (SettingsRejected, ValueError) as exc:
            QMessageBox.warning(self, "Preset", f"Presetten kan inte aktiveras:\n{exc}")
            return
        self.store.set(settings)
        self._sync_widgets()

    def _preset_load(self) -> None:
        name = self._selected_preset()
        if not name:
            return
        try:
            preset = self.library.load(name)
        except PresetError as exc:
            QMessageBox.warning(self, "Preset", str(exc))
            return
        self._load_settings(preset.settings)

    def _preset_delete(self) -> None:
        name = self._selected_preset()
        if name and QMessageBox.question(self, "Ta bort", f"Ta bort '{name}'?") == QMessageBox.StandardButton.Yes:
            try:
                self.library.delete(name)
            except (PresetError, OSError) as exc:
                QMessageBox.warning(self, "Preset", str(exc))
            self._refresh_presets()

    def _preset_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importera preset", "", "JSON (*.json)")
        if not path:
            return
        try:
            name = self.library.import_file(path)
        except PresetError as exc:
            QMessageBox.warning(self, "Import", str(exc))
            return
        self._refresh_presets()
        self.statusBar().showMessage(f"Importerade '{name}'.", 4000)

    def _preset_export(self) -> None:
        name = self._selected_preset()
        if not name:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exportera preset", f"{name}.json", "JSON (*.json)")
        if not path:
            return
        try:
            self.library.export_to(name, path)
        except (PresetError, OSError) as exc:
            QMessageBox.warning(self, "Export", str(exc))

    def _factory_reset(self) -> None:
        if QMessageBox.question(self, "Fabriksinställningar", "Återställ alla inställningar?") == QMessageBox.StandardButton.Yes:
            self._load_settings(ChainSettings())

    # ------------------------------------------------------------------
    # Periodisk uppdatering (GUI-tråd)
    # ------------------------------------------------------------------
    def _tick(self) -> None:
        eng = self.engine
        eng.check_health()
        core = eng.core
        armed = eng.safety.armed

        if core is not None:
            m = core.latest_meters()
            self.meter_in.set_levels(m.in_peak_db)
            self.meter_out.set_levels(m.out_peak_db)
            self.gr_label.setText(f"Limiter GR: {m.gain_reduction_db:.1f} dB")
            lat_ms = 1000.0 * core.chain.latency_samples / core.fs
            self.latency_label.setText(
                f"Limiter-lookahead: {lat_ms:.1f} ms · glitchar: {core.fault_count + core.status_events}"
            )
            for issue in eng.safety.observe_meters(m):
                self.statusBar().showMessage(issue.message, 1000)
            if core.duration_s > 0 and not self.pos_slider.isSliderDown():
                self.pos_slider.blockSignals(True)
                self.pos_slider.setValue(int(1000 * core.position_s / core.duration_s))
                self.pos_slider.blockSignals(False)
            self.time_label.setText(f"{_fmt(core.position_s)} / {_fmt(core.duration_s)}")
            if self.tabs.currentWidget() is self.analyzer_tab:
                freqs, db = compute_spectrum_db(core.spectrum_snapshot(4096), core.fs, 4096)
                self.spectrum.update_spectrum(freqs, db)

        if armed:
            self.output_status.setText("UTGÅNG AKTIV")
            self.output_status.setStyleSheet(f"font-weight: 600; color: {COLORS['green']};")
            self.arm_button.setText("Stäng av utgång")
        else:
            self.output_status.setText(eng.safety.last_event)
            self.output_status.setStyleSheet(f"font-weight: 600; color: {COLORS['orange']};")
            self.arm_button.setText("Aktivera utgång…")
        self.arm_button.setProperty("armed", "true" if armed else "false")
        self.arm_button.style().unpolish(self.arm_button)
        self.arm_button.style().polish(self.arm_button)

    def closeEvent(self, event) -> None:  # noqa: ANN001
        self._timer.stop()
        self.engine.emergency_mute()
        if self.autosave_path is not None:
            try:
                from ..presets import PresetFile, save_preset

                save_preset(self.autosave_path, PresetFile(name="autosave", settings=self.store.current))
            except Exception:  # noqa: BLE001
                log.exception("Kunde inte spara autosave")
        self.engine.stop()
        super().closeEvent(event)


def _fmt(seconds: float) -> str:
    s = int(seconds) if math.isfinite(seconds) else 0
    return f"{s // 60}:{s % 60:02d}"
