"""PortAudio-koppling (sounddevice) runt `RealtimeCore`.

Den här filen kräver riktig ljudhårdvara och paketet `sounddevice`. Den är därför
inte täckt av de automatiska testerna; all logik som går att testa ligger i `core`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ..dsp.params import ChainSettings, validate_for_sample_rate
from ..safety.engine import EquipmentProfile, SafetyEngine, SafetyReport
from .core import RealtimeCore
from .source import FileSource, load_audio_file

log = logging.getLogger(__name__)


class SettingsRejected(Exception):
    """Inställningen avvisades av Safety Engine medan utgången är aktiv."""


class AudioBackendUnavailable(Exception):
    pass


@dataclass(frozen=True)
class DeviceInfo:
    index: int
    name: str
    hostapi: str
    max_output_channels: int
    default_samplerate: float


def _import_sd():
    try:
        import sounddevice as sd  # type: ignore
    except Exception as exc:  # ImportError eller OSError (saknad PortAudio)
        raise AudioBackendUnavailable(
            f"Ljudbiblioteket 'sounddevice' kunde inte laddas: {exc}"
        ) from exc
    return sd


class AudioEngine:
    DEFAULT_FS = 48_000

    def __init__(
        self,
        safety: SafetyEngine | None = None,
        settings: ChainSettings | None = None,
        profile: EquipmentProfile | None = None,
    ) -> None:
        self.safety = safety or SafetyEngine()
        self.settings = settings or ChainSettings()
        self.profile = profile
        self.fs = self.DEFAULT_FS
        self.core: RealtimeCore | None = None
        self.file_name: str | None = None
        self._raw: tuple | None = None
        self._loop = False
        self._stream = None
        self._stopping = False

    # ---- enheter ---------------------------------------------------------
    @staticmethod
    def list_output_devices() -> list[DeviceInfo]:
        sd = _import_sd()
        hostapis = sd.query_hostapis()
        out: list[DeviceInfo] = []
        for idx, dev in enumerate(sd.query_devices()):
            if dev["max_output_channels"] >= 2:
                out.append(
                    DeviceInfo(
                        index=idx,
                        name=dev["name"],
                        hostapi=hostapis[dev["hostapi"]]["name"],
                        max_output_channels=dev["max_output_channels"],
                        default_samplerate=float(dev["default_samplerate"]),
                    )
                )
        return out

    # ---- livscykel -------------------------------------------------------
    def start(self, device: int | None = None, blocksize: int = 512, samplerate: int | None = None) -> None:
        sd = _import_sd()
        self.stop()
        info = sd.query_devices(device, "output")
        fs = int(samplerate or info["default_samplerate"])
        sd.check_output_settings(device=device, channels=2, dtype="float32", samplerate=fs)
        validate_for_sample_rate(self.settings, fs)

        self.fs = fs
        self.core = RealtimeCore(fs, 2, self.settings, self.safety)
        self._attach_source()
        self.safety.on_device_restored()
        self._stopping = False
        self._stream = sd.OutputStream(
            samplerate=fs,
            blocksize=blocksize,
            device=device,
            channels=2,
            dtype="float32",
            latency="low",
            callback=self._callback,
            finished_callback=self._on_finished,
        )
        self._stream.start()
        log.info("Ljudström startad: enhet=%s fs=%d block=%d", info["name"], fs, blocksize)

    def stop(self) -> None:
        self._stopping = True
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:  # noqa: BLE001
                log.exception("Fel vid stängning av ljudström")
        self.safety.disarm("Ljudmotorn stoppad. Utgången är avstängd.")
        self.core = None

    @property
    def running(self) -> bool:
        return self._stream is not None and bool(self._stream.active)

    def check_health(self) -> None:
        """Anropas regelbundet från GUI. Försätter systemet i säkert läge vid avbrott."""
        if self._stream is not None and not self._stopping and not self._stream.active:
            self.safety.on_device_lost("Ljudströmmen avbröts.")

    # ---- callbacks (ljudtråd) -------------------------------------------
    def _callback(self, outdata, frames, time_info, status) -> None:  # noqa: ANN001
        core = self.core
        if core is None:
            outdata.fill(0)
            return
        if status:
            core.note_status(status)
        outdata[:] = core.process_block(frames)

    def _on_finished(self) -> None:
        if not self._stopping:
            self.safety.on_device_lost("Ljudströmmen avslutades oväntat.")

    # ---- inställningar och säkerhet -------------------------------------
    def evaluate(self, settings: ChainSettings | None = None) -> SafetyReport:
        return self.safety.evaluate(settings or self.settings, self.fs, self.profile)

    def apply_settings(self, settings: ChainSettings) -> SafetyReport:
        validate_for_sample_rate(settings, self.fs)
        report = self.evaluate(settings)
        if self.safety.armed and report.has_critical:
            msgs = "; ".join(i.message for i in report.issues if i.severity >= 2)
            raise SettingsRejected(f"Inställningen avvisades medan utgången är aktiv: {msgs}")
        self.settings = settings
        if self.core is not None:
            self.core.post_settings(settings, report.predicted_peak_gain_db)
        return report

    def arm(self) -> SafetyReport:
        """Aktiverar utgången. Anropas först efter att användaren godkänt utlåtandet."""
        if self.core is None:
            from ..safety.engine import SafetyError

            raise SafetyError("Starta ljudmotorn innan utgången aktiveras.")
        report = self.evaluate()
        self.safety.arm(report, acknowledged=True)
        return report

    def emergency_mute(self) -> None:
        self.safety.emergency_mute()

    # ---- fil och transport ----------------------------------------------
    def load_file(self, path: str | Path) -> None:
        data, sr = load_audio_file(path)
        self._raw = (data, sr)
        self.file_name = Path(path).name
        self._attach_source()

    def _attach_source(self) -> None:
        if self.core is not None and self._raw is not None:
            data, sr = self._raw
            self.core.set_source(FileSource(data, sr, self.fs, loop=self._loop))

    def set_loop(self, loop: bool) -> None:
        self._loop = bool(loop)
        if self.core is not None and self.core.source is not None:
            self.core.source.loop = self._loop

    def play(self) -> None:
        if self.core is not None:
            self.core.play()

    def pause(self) -> None:
        if self.core is not None:
            self.core.pause()

    def halt(self) -> None:
        if self.core is not None:
            self.core.stop()

    def seek_seconds(self, seconds: float) -> None:
        if self.core is not None:
            self.core.seek_seconds(seconds)
