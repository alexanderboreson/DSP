"""Presets i JSON med schemavalidering, versionering och migrering.

Filer tolkas enbart som data (json + pydantic). Ingen kod exekveras och okända
fält förkastas.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..dsp.params import ChainSettings

CURRENT_SCHEMA_VERSION = 1
MAX_PRESET_BYTES = 1_000_000


class PresetError(Exception):
    pass


class PresetFile(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    schema_version: int = CURRENT_SCHEMA_VERSION
    name: str = Field(min_length=1, max_length=80)
    notes: str = Field(default="", max_length=2000)
    settings: ChainSettings


# Migreringar: version N -> N+1. Fylls på när schemat ändras.
_MIGRATIONS: dict[int, "callable"] = {}


def migrate(raw: dict) -> dict:
    version = raw.get("schema_version")
    if not isinstance(version, int) or version < 1:
        raise PresetError("Ogiltigt eller saknat schema_version.")
    if version > CURRENT_SCHEMA_VERSION:
        raise PresetError(
            f"Presetfilen är från en nyare version ({version}) än vad programmet stöder "
            f"({CURRENT_SCHEMA_VERSION})."
        )
    while version < CURRENT_SCHEMA_VERSION:
        raw = _MIGRATIONS[version](raw)
        version += 1
        raw["schema_version"] = version
    return raw


def load_preset(path: str | Path) -> PresetFile:
    p = Path(path)
    try:
        size = p.stat().st_size
    except OSError as exc:
        raise PresetError(f"Kunde inte läsa filen: {exc}") from exc
    if size > MAX_PRESET_BYTES:
        raise PresetError("Presetfilen är för stor.")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PresetError(f"Ogiltig JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise PresetError("Presetfilen måste innehålla ett JSON-objekt.")
    raw = migrate(raw)
    try:
        return PresetFile.model_validate(raw)
    except ValidationError as exc:
        raise PresetError(f"Presetfilen klarar inte schemavalideringen: {exc}") from exc


def save_preset(path: str | Path, preset: PresetFile) -> None:
    """Atomisk skrivning. Befintlig fil säkerhetskopieras som '<fil>.bak'."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        shutil.copy2(p, p.with_name(p.name + ".bak"))
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(preset.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _slug(name: str) -> str:
    slug = re.sub(r"[^\w\- ]+", "_", name, flags=re.UNICODE).strip(" ._")
    if not slug:
        raise PresetError("Ogiltigt presetnamn.")
    return slug[:80]


class PresetLibrary:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        path = (self.directory / f"{_slug(name)}.json").resolve()
        if path.parent != self.directory.resolve():
            raise PresetError("Ogiltig sökväg.")
        return path

    def list_names(self) -> list[str]:
        return sorted(p.stem for p in self.directory.glob("*.json"))

    def save(self, name: str, settings: ChainSettings, notes: str = "") -> Path:
        path = self._path(name)
        save_preset(path, PresetFile(name=name, notes=notes, settings=settings))
        return path

    def load(self, name: str) -> PresetFile:
        return load_preset(self._path(name))

    def delete(self, name: str) -> None:
        path = self._path(name)
        if path.exists():
            path.unlink()

    def export_to(self, name: str, destination: str | Path) -> None:
        preset = self.load(name)
        save_preset(destination, preset)

    def import_file(self, source: str | Path) -> str:
        """Validerar filen och sparar den i biblioteket. Returnerar presetnamnet."""
        preset = load_preset(source)
        self.save(preset.name, preset.settings, preset.notes)
        return _slug(preset.name)
