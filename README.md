# AutoDSP Studio – Fas 1 (MVP)

Lokal DSP-applikation i Python/PyQt6 med säkerhet och användarvänlighet i fokus. Fungerar helt
utan molntjänster. Arkitektur, risker och signalflöde: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Vad Fas 1 innehåller (och vad som är verifierat)

| Funktion | Status |
|---|---|
| Parametrisk EQ, 10 band (Peak/Low Shelf/High Shelf), frekvens/gain/Q, per-band på/av, bypass | Implementerad, **testad** |
| Gain (input, master, mute) med rampning, peak-limiter med lookahead och release | Implementerad, **testad** |
| Digital nivåmätning (peak/RMS/clipping), FFT-spektrum | Implementerad, **testad** (matematik) |
| Safety Engine: safe startup, nödstopp, enhetsförlust, headroom-kontroll, profilkontroll | Implementerad, **testad** |
| Presets i JSON med schema, versionering, import/export, backup, ångra/gör om, A/B | Implementerad, **testad** |
| Säkert presetbyte (nedtoning vid stora nivåskillnader) | Implementerad, **testad** |
| NaN/Inf-hantering, fel i callback → tystnad, ändring under uppspelning, 44,1–192 kHz, 1–6 kanaler | **Testad** |
| PyQt6-gränssnitt (Dashboard, Equalizer, Analyzer, Presets) | Skriven, **ej körd** (se nedan) |
| PortAudio-uppspelning via `sounddevice` | Skriven, **ej körd mot riktig hårdvara** |
| Crossover, delay, kanalrouting, bilvy, kalibrering, mikrofonmätning, hårdvaruadaptrar | **Ej implementerade** (Fas 2–4) |

Alla automatiska tester körs i simulerad miljö (virtuell enhet som driver `RealtimeCore`
direkt). **Inga tester har körts med fysiska förstärkare eller högtalare.**

## Installation (Windows 11, PowerShell)

```powershell
cd "C:\Users\alexander.boreson\Desktop\DSP"
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
```

## Starta

```powershell
python -m autodsp
```

1. Välj utgångsenhet och klicka **Starta ljudmotor**. Utgången är fortfarande avstängd.
2. **Öppna ljudfil…** (WAV/FLAC/OGG).
3. Sänk volymen på förstärkaren/hörlurarna, klicka **Aktivera utgång…**, läs säkerhetsutlåtandet
   och godkänn. Först då släpps ljudet igenom.
4. **NÖDSTOPP** (knappen eller Ctrl+M) stänger utgången omedelbart (5 ms ramp). Ctrl+Z/Ctrl+Y
   ångrar/gör om.

Standardvärden är konservativa: master −12 dB, limiter-tak −1 dBFS.

## Tester

```powershell
python -m pytest -q
```

## Kända begränsningar

* **GUI-koden har bara syntaxkontrollerats**, inte körts: miljön där den skrevs saknade PyQt6,
  pyqtgraph, sounddevice och soundfile. Räkna med att små fel i GUI/ljudenhetskoden dyker upp
  vid första körning – skicka felmeddelandet så rättar jag dem.
* Stereo endast (mono dupliceras, >2 kanaler → de två första). Filer laddas helt i minnet.
* Limiterns lookahead är 1,5 ms; callbacken är Python (se risk 1 i ARCHITECTURE.md).
* EQ-kurvan i grafen är en beräknad modell, inte en mätning.
* Digital begränsning och kontroller **garanterar inte** skydd av utrustning.

## Nästa steg: Fas 2

Kanalvis EQ/crossover/delay, routing, utrustningsprofiler, bilvy och avancerade säkerhetskontroller.
Se "Hur Fas 2 bygger vidare" i docs/ARCHITECTURE.md.
