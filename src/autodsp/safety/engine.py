"""Safety Engine – fristående från GUI.

Ansvar i Fas 1:
 * Safe Startup: utgången är avstängd tills användaren godkänt ett säkerhetsutlåtande.
 * Emergency Mute och hantering av bortkopplad ljudenhet (båda -> avstängd utgång).
 * Gain Safety / headroom-kontroll av inställningar (beräknad, inte uppmätt nivå).
 * Kontroll mot en användardefinierad utrustningsprofil.
 * Övervakning av digital clipping via nivåmätare.

VIKTIGT: En digital begränsare och dessa kontroller kan inte garantera skydd mot
överbelastning, felaktig förstärkargain, värmeskador, felaktig inkoppling eller
hårdvarufel. Programmet garanterar aldrig att utrustning inte kan skadas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from pydantic import BaseModel, ConfigDict, Field

from ..dsp.meters import MeterSnapshot
from ..dsp.params import ChainSettings, validate_for_sample_rate
from ..dsp.response import predicted_peak_gain_db

DISCLAIMER = (
    "En digital begränsare kan inte garantera skydd mot överbelastning, felaktig "
    "förstärkargain, värmeskador, felaktig inkoppling eller hårdvarufel. "
    "AutoDSP Studio garanterar aldrig att ansluten utrustning inte kan skadas."
)

# Beräknad maximal digital förstärkning (dB) över vilken inställningen räknas som kritisk.
CRITICAL_GAIN_DB = 12.0
# Skillnad i beräknad förstärkning (dB) som utlöser kontrollerad nedtoning vid byte.
SAFE_SWITCH_DB = 6.0


class Severity(IntEnum):
    INFO = 0
    WARNING = 1
    CRITICAL = 2


@dataclass(frozen=True)
class SafetyIssue:
    severity: Severity
    code: str
    message: str


@dataclass(frozen=True)
class SafetyReport:
    issues: tuple[SafetyIssue, ...]
    predicted_peak_gain_db: float
    disclaimer: str = DISCLAIMER

    @property
    def has_critical(self) -> bool:
        return any(i.severity == Severity.CRITICAL for i in self.issues)

    @property
    def has_warning(self) -> bool:
        return any(i.severity >= Severity.WARNING for i in self.issues)


class EquipmentProfile(BaseModel):
    """Användardefinierade gränser. Inga värden antas utifrån högtalartyp."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    name: str = Field(max_length=80)
    min_freq_hz: float | None = Field(default=None, ge=1.0, le=20000.0)
    verified: bool = False  # True först när användaren verifierat värdena mot tillverkaren


class SafetyError(Exception):
    pass


@dataclass
class SafetyEngine:
    armed: bool = False
    device_ok: bool = True
    last_event: str = "Säker start: utgången är avstängd."
    _clip_streak: int = field(default=0, repr=False)

    # ---- tillstånd -------------------------------------------------------
    @property
    def gate_open(self) -> bool:
        return self.armed and self.device_ok

    def arm(self, report: SafetyReport, acknowledged: bool) -> None:
        if not acknowledged:
            raise SafetyError("Säkerhetsutlåtandet måste godkännas innan utgången aktiveras.")
        if report.has_critical:
            raise SafetyError("Utgången kan inte aktiveras: kritiska säkerhetsproblem finns.")
        if not self.device_ok:
            raise SafetyError("Ljudenheten är inte tillgänglig.")
        self.armed = True
        self.last_event = "Utgång aktiverad."

    def disarm(self, reason: str = "Utgång avstängd.") -> None:
        self.armed = False
        self.last_event = reason

    def emergency_mute(self) -> None:
        self.disarm("NÖDSTOPP: utgången avstängd. Aktivera utgången manuellt igen.")

    def on_device_lost(self, reason: str = "Ljudenheten försvann eller slutade fungera.") -> None:
        self.device_ok = False
        self.disarm(f"{reason} Utgången är avstängd.")

    def on_device_restored(self) -> None:
        # Återställer inte aktiveringen: användaren måste godkänna igen.
        self.device_ok = True

    # ---- analys ----------------------------------------------------------
    def evaluate(
        self, settings: ChainSettings, fs: float, profile: EquipmentProfile | None = None
    ) -> SafetyReport:
        issues: list[SafetyIssue] = []
        try:
            validate_for_sample_rate(settings, fs)
        except ValueError as exc:
            issues.append(SafetyIssue(Severity.CRITICAL, "INVALID_FOR_SAMPLE_RATE", str(exc)))

        pred = predicted_peak_gain_db(settings, fs)
        if pred > CRITICAL_GAIN_DB:
            issues.append(
                SafetyIssue(
                    Severity.CRITICAL,
                    "EXCESSIVE_GAIN",
                    f"Beräknad maximal digital förstärkning är {pred:+.1f} dB "
                    f"(gräns {CRITICAL_GAIN_DB:+.0f} dB). Sänk master, ingång eller EQ-boost.",
                )
            )
        elif pred > 0.0:
            issues.append(
                SafetyIssue(
                    Severity.WARNING,
                    "HEADROOM",
                    f"Beräknad maximal digital förstärkning är {pred:+.1f} dB: "
                    "risk för clipping/limiter-ingrepp vid fullt utstyrda ingångssignaler.",
                )
            )
        if settings.master_gain_db > 0.0:
            issues.append(
                SafetyIssue(
                    Severity.WARNING,
                    "MASTER_BOOST",
                    f"Mastervolymen är {settings.master_gain_db:+.1f} dB (över 0 dB).",
                )
            )

        if profile is None:
            issues.append(
                SafetyIssue(
                    Severity.INFO,
                    "NO_PROFILE",
                    "Ingen utrustningsprofil vald: inga högtalarspecifika kontroller utförs.",
                )
            )
        else:
            if not profile.verified:
                issues.append(
                    SafetyIssue(
                        Severity.INFO,
                        "PROFILE_UNVERIFIED",
                        f"Profilen '{profile.name}' har inte markerats som verifierad.",
                    )
                )
            if profile.min_freq_hz is not None and not settings.eq_bypass:
                for i, band in enumerate(settings.eq_bands):
                    if band.enabled and band.gain_db > 0 and band.freq_hz < profile.min_freq_hz:
                        issues.append(
                            SafetyIssue(
                                Severity.WARNING,
                                "BOOST_BELOW_SAFE_RANGE",
                                f"EQ-band {i + 1} förstärker {band.gain_db:+.1f} dB vid "
                                f"{band.freq_hz:.0f} Hz, under profilens nedre gräns "
                                f"{profile.min_freq_hz:.0f} Hz.",
                            )
                        )
        return SafetyReport(tuple(issues), pred)

    def observe_meters(self, m: MeterSnapshot) -> list[SafetyIssue]:
        """Körs från GUI/övervakningstråd (inte från ljudcallbacken)."""
        issues: list[SafetyIssue] = []
        if m.input_clipped:
            issues.append(
                SafetyIssue(Severity.WARNING, "INPUT_CLIPPING", "Ingångssignalen clippar digitalt.")
            )
        if max(m.out_peak_db, default=-120.0) >= -0.1:
            issues.append(
                SafetyIssue(
                    Severity.WARNING,
                    "OUTPUT_FULL_SCALE",
                    "Utgångsnivån ligger vid digital fullskala.",
                )
            )
        return issues
