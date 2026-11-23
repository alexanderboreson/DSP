"""Realtidskärna: allt som körs per ljudblock, utan beroende av GUI eller maskinvara.

Trådmodell
 * GUI-tråden anropar `post_settings`, transportmetoderna och läser mätare.
 * Ljudtråden (PortAudio-callbacken) anropar endast `process_block`.
 * Inställningar skickas som en oföränderlig tupel `(version, settings, predicted_gain)`
   i en enda attribut-tilldelning (atomär i CPython) och appliceras vid blockgräns.
 * Mätare publiceras som en oföränderlig snapshot.

Ljudutgången passerar alltid en säkerhetsgrind (SmoothedGain, 5 ms ramp) som stängs
av nödstopp, avaktiverad utgång, bortkopplad enhet, kontrollerade preset-byten och
sökningar.

Kända begränsningar i Python: NumPy/SciPy allokerar minne i callbacken. Prestanda
och jitter måste verifieras på mål-datorn (se docs/ARCHITECTURE.md).
"""

from __future__ import annotations

import numpy as np

from ..dsp.chain import ProcessingChain
from ..dsp.gain import SmoothedGain
from ..dsp.meters import MeterSnapshot, measure
from ..dsp.params import ChainSettings
from ..dsp.response import predicted_peak_gain_db
from ..safety.engine import SAFE_SWITCH_DB, SafetyEngine
from .source import FileSource

GATE_RAMP_MS = 5.0
TAP_SIZE = 8192


class RealtimeCore:
    def __init__(
        self,
        fs: int,
        channels: int = 2,
        settings: ChainSettings | None = None,
        safety: SafetyEngine | None = None,
    ) -> None:
        settings = settings or ChainSettings()
        self.fs = int(fs)
        self.channels = int(channels)
        self.safety = safety or SafetyEngine()
        self.chain = ProcessingChain(self.fs, self.channels, settings)
        self._gate = SmoothedGain(self.fs, initial=0.0, ramp_ms=GATE_RAMP_MS)

        self._version = 0
        self._applied_version = 0
        self._applied_pred = predicted_peak_gain_db(settings, self.fs)
        self._mailbox: tuple[int, ChainSettings, float] = (0, settings, self._applied_pred)
        self._switching = False

        self._source: FileSource | None = None
        self._want_play = False
        self._seek_to: int | None = None

        self._meters = MeterSnapshot.silent(self.channels)
        self._tap = np.zeros(TAP_SIZE, dtype=np.float32)
        self._tap_pos = 0

        self.fault_count = 0
        self.status_events = 0

    # ------------------------------------------------------------------
    # GUI-trådens API
    # ------------------------------------------------------------------
    def post_settings(self, settings: ChainSettings, predicted_gain_db: float) -> None:
        self._version += 1
        self._mailbox = (self._version, settings, float(predicted_gain_db))

    def set_source(self, source: FileSource | None) -> None:
        self._want_play = False
        self._seek_to = None
        self._source = source

    @property
    def source(self) -> FileSource | None:
        return self._source

    @property
    def playing(self) -> bool:
        return self._want_play and self._source is not None

    @property
    def position_s(self) -> float:
        return self._source.position / self.fs if self._source else 0.0

    @property
    def duration_s(self) -> float:
        return self._source.length / self.fs if self._source else 0.0

    def play(self) -> None:
        src = self._source
        if src is None:
            return
        if src.position >= src.length:
            self._seek_to = 0
        self._want_play = True

    def pause(self) -> None:
        self._want_play = False

    def stop(self) -> None:
        self._want_play = False
        self._seek_to = 0

    def seek_seconds(self, seconds: float) -> None:
        if self._source is not None:
            self._seek_to = int(max(0.0, seconds) * self.fs)

    def latest_meters(self) -> MeterSnapshot:
        return self._meters

    def spectrum_snapshot(self, n: int = 4096) -> np.ndarray:
        """Senaste utsignalen (mono). Kan i sällsynta fall vara något "trasig" vid
        läsning mitt i en skrivning; avsett för visualisering."""
        pos = self._tap_pos
        ordered = np.concatenate((self._tap[pos:], self._tap[:pos]))
        return ordered[-n:].copy()

    def note_status(self, status: object) -> None:
        self.status_events += 1

    # ------------------------------------------------------------------
    # Ljudtråden
    # ------------------------------------------------------------------
    def process_block(self, frames: int) -> np.ndarray:
        try:
            return self._process(frames)
        except Exception:  # noqa: BLE001 - en callback får aldrig kasta
            self.fault_count += 1
            try:
                self.chain.reset()
            except Exception:  # noqa: BLE001
                pass
            return np.zeros((frames, self.channels), dtype=np.float32)

    def _apply(self, version: int, settings: ChainSettings, predicted: float) -> None:
        try:
            self.chain.apply(settings)
        except ValueError:
            self.fault_count += 1
            return
        self._applied_version = version
        self._applied_pred = predicted

    def _service_pending(self) -> None:
        closed = self._gate.is_closed

        if self._seek_to is not None and closed:
            if self._source is not None:
                self._source.seek(self._seek_to)
            self._seek_to = None

        version, settings, predicted = self._mailbox
        if self._switching:
            if closed:
                self._apply(version, settings, predicted)
                self._switching = False
        elif version != self._applied_version:
            jump = abs(predicted - self._applied_pred) > SAFE_SWITCH_DB
            audible = self._gate.current > 0.0
            if jump and audible and self._want_play:
                self._switching = True  # tona ned, byt, tona upp
            else:
                self._apply(version, settings, predicted)

    def _process(self, frames: int) -> np.ndarray:
        self._service_pending()

        src = self._source
        hold = self._switching or self._seek_to is not None
        want_open = (
            self.safety.gate_open and self._want_play and not hold and src is not None
        )
        self._gate.set_target(1.0 if want_open else 0.0, ramp_ms=GATE_RAMP_MS)

        if src is None or (self._gate.is_closed and not want_open):
            self._gate.advance(frames)
            self._meters = MeterSnapshot.silent(self.channels)
            return np.zeros((frames, self.channels), dtype=np.float32)

        x = src.read(frames)
        if src.finished:
            self._want_play = False
        y = self._gate.process(self.chain.process(x))

        out_peak, out_rms, out_clipped = measure(y)
        self._meters = MeterSnapshot(
            in_peak_db=self.chain.last_input_peak_db,
            in_rms_db=self.chain.last_input_rms_db,
            out_peak_db=out_peak,
            out_rms_db=out_rms,
            gain_reduction_db=self.chain.gain_reduction_db,
            input_clipped=self.chain.last_input_clipped,
            output_clipped=out_clipped,
        )
        self._write_tap(y)
        return y

    def _write_tap(self, y: np.ndarray) -> None:
        mono = y.mean(axis=1)
        n = mono.shape[0]
        if n >= TAP_SIZE:
            self._tap[:] = mono[-TAP_SIZE:]
            self._tap_pos = 0
            return
        pos = self._tap_pos
        end = pos + n
        if end <= TAP_SIZE:
            self._tap[pos:end] = mono
        else:
            first = TAP_SIZE - pos
            self._tap[pos:] = mono[:first]
            self._tap[: n - first] = mono[first:]
        self._tap_pos = end % TAP_SIZE
