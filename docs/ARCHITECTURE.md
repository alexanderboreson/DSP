# AutoDSP Studio – arkitektur, tekniska risker och signalflöde

## Katalogstruktur

```
AutoDSP-Studio/
├─ pyproject.toml · requirements.txt · README.md
├─ docs/ARCHITECTURE.md
├─ src/autodsp/
│  ├─ app.py · __main__.py · paths.py     Start, loggning, datakatalog
│  ├─ store.py                            Inställningslager: ångra/gör om, A/B (Qt-fritt)
│  ├─ dsp/                                Ren signalbehandling (NumPy/SciPy)
│  │  ├─ params.py                        Pydantic-modeller + validering
│  │  ├─ biquad.py · response.py          RBJ-filter, beräknad frekvensrespons
│  │  ├─ eq.py · gain.py · limiter.py     EQ, rampad gain, lookahead-limiter
│  │  ├─ meters.py · chain.py             Nivåmätare, hela signalkedjan
│  ├─ safety/engine.py                    Safety Engine (fristående från GUI)
│  ├─ presets/manager.py                  JSON-presets, schema, migrering, bibliotek
│  ├─ audio/
│  │  ├─ core.py                          Realtidskärna (testbar, ingen hårdvara)
│  │  ├─ source.py                        Filinläsning, resampling, stereokälla
│  │  └─ engine.py                        PortAudio/sounddevice-koppling
│  ├─ analysis/spectrum.py                FFT-spektrum (dBFS)
│  └─ ui/                                 PyQt6: tema, widgets, huvudfönster
└─ tests/                                 pytest (simulerad miljö)
```

## Signalflöde (Fas 1, stereo)

```
Fil → Input Meter → Input Gain → Parametrisk EQ (10 band) → Master Gain (+Mute)
    → Peak Limiter (lookahead) → Säkerhetsgrind (5 ms ramp) → Output Meter → Ljudutgång
```

* Säkerhetsgrinden är sista steget och stängs av: avaktiverad utgång (safe startup),
  nödstopp, bortkopplad enhet, kontrollerade preset-byten och sökning.
* Gain, mute, bypass och EQ-koefficienter rampas/crossfadas, så att inga klick uppstår.

## Trådmodell

| Tråd | Gör | Får inte göra |
|---|---|---|
| GUI | Bygger/validerar inställningar, `post_settings`, transport, läser mätare | Röra filtertillstånd |
| Ljud (PortAudio-callback) | `RealtimeCore.process_block` | Disk, loggning, GUI-anrop, kasta undantag |

* Inställningar skickas som en oföränderlig tupel `(version, settings, predicted_gain)` i en
  enda tilldelning och appliceras vid blockgräns. Ingen lås i callbacken.
* Mätare publiceras som en oföränderlig `MeterSnapshot`. Spektrumbufferten är en ring som GUI
  läser utan lås (kan i sällsynta fall visa ett "trasigt" block; endast visualisering).

## Safety Engine (Fas 1)

Implementerat: safe startup, godkännande av säkerhetsutlåtande, nödstopp, bortkopplad enhet,
headroom-/gain-kontroll (beräknad), kontroll mot användardefinierad profil, clipping-varning,
avvisning av kritiska inställningar medan utgången är aktiv, kontrollerad nedtoning vid stora
nivåskillnader (> 6 dB beräknad förstärkning).

**Garanti:** ingen. Digitala begränsare skyddar inte mot för hög förstärkargain, värmeskador,
felkoppling eller hårdvarufel. Programmet antar aldrig högtalarspecifikationer.

## Tekniska risker

| # | Risk | Hantering / nästa steg |
|---|---|---|
| 1 | **Python i realtidscallback**: NumPy/SciPy allokerar minne, GC och GIL kan ge jitter/avbrott. | Blockstorlek 512 som utgångspunkt; callbacken är undantagssäker och räknar glitchar (visas i GUI). Mät på mål-datorn. Om det inte räcker: flytta `dsp/` till C++/Rust-motor bakom samma gränssnitt (`RealtimeCore`). |
| 2 | **ASIO/WASAPI**: vilka värdgränssnitt som finns beror på PortAudio-bygget i `sounddevice`-hjulet. | Enhetslistan visar värd-API per enhet. Verifiera på din dator om ASIO syns; annars WASAPI/MME. |
| 3 | **Latens**: limitern lägger 1,5 ms lookahead, plus enhetens buffert. | Visas i GUI. Ingen tidskritisk användning i Fas 1. |
| 4 | **Samplingsfrekvens**: strömmen öppnas med enhetens standardfrekvens, filer resamplas vid inläsning (`resample_poly`). | Hela filen laddas i minnet (max 60 min). Streaming från disk är en senare förbättring. |
| 5 | **Externa DSP:er**: kräver dokumenterade protokoll. | Ingen gissning av USB-kommandon. Plugin-system är Fas 4. |
| 6 | **Beräknat ≠ uppmätt**: EQ-kurvan är en modell. | Märkt tydligt i GUI. Mikrofonmätning kommer i Fas 3. |
| 7 | **GUI ej körd i utvecklingsmiljön** | Se README → "Kända begränsningar". |

## Hur Fas 2 bygger vidare

* `ProcessingChain` får kanalvisa EQ/crossover/delay (`channels` är redan en parameter;
  filtertillståndet är redan `(sektioner, 2, kanaler)`).
* `ChainSettings` utökas med `channels: tuple[ChannelSettings, ...]`; `schema_version` höjs och
  en migrering läggs i `presets/manager.py::_MIGRATIONS`.
* `EquipmentProfile` utökas per högtalare (frekvensområde, effektgräns) och `SafetyEngine.evaluate`
  får kanalvisa regler (t.ex. kräv högpassfilter).
* Bilvy och Channel Manager läggs som nya flikar i `ui/`.
