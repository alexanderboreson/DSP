import json

import pytest

from autodsp.dsp.meters import MeterSnapshot
from autodsp.dsp.params import ChainSettings, EQBand
from autodsp.presets import CURRENT_SCHEMA_VERSION, PresetError, PresetFile, PresetLibrary, load_preset, save_preset
from autodsp.safety import DISCLAIMER, EquipmentProfile, SafetyEngine, SafetyError, SafetyReport, Severity
from autodsp.store import SettingsStore

FS = 48000


# ---------------- Safety ----------------
def test_starts_disarmed_and_requires_acknowledgement():
    s = SafetyEngine()
    assert not s.armed and not s.gate_open
    rep = s.evaluate(ChainSettings(), FS)
    with pytest.raises(SafetyError):
        s.arm(rep, acknowledged=False)
    s.arm(rep, acknowledged=True)
    assert s.gate_open


def test_critical_issue_blocks_arming():
    s = SafetyEngine()
    risky = ChainSettings().replace(master_gain_db=6.0, input_gain_db=12.0).with_band(
        4, EQBand(kind="peak", freq_hz=1000, gain_db=24.0, q=1.0)
    )
    rep = s.evaluate(risky, FS)
    assert rep.has_critical
    with pytest.raises(SafetyError):
        s.arm(rep, acknowledged=True)


def test_headroom_warning_and_report_has_disclaimer():
    s = SafetyEngine()
    rep = s.evaluate(ChainSettings().replace(master_gain_db=3.0), FS)
    codes = {i.code for i in rep.issues}
    assert "HEADROOM" in codes and "MASTER_BOOST" in codes
    assert not rep.has_critical
    assert rep.disclaimer == DISCLAIMER and "garanterar aldrig" in rep.disclaimer


def test_default_settings_are_conservative():
    rep = SafetyEngine().evaluate(ChainSettings(), FS)
    assert not rep.has_warning
    assert rep.predicted_peak_gain_db <= -12.0 + 1e-6


def test_emergency_mute_and_device_loss_disarm_and_do_not_rearm():
    s = SafetyEngine()
    rep = SafetyReport((), 0.0)
    s.arm(rep, True)
    s.emergency_mute()
    assert not s.gate_open and "NÖDSTOPP" in s.last_event
    s.arm(rep, True)
    s.on_device_lost()
    assert not s.armed and not s.device_ok
    with pytest.raises(SafetyError):
        s.arm(rep, True)
    s.on_device_restored()
    assert not s.armed  # kräver nytt godkännande


def test_profile_boost_below_min_frequency_warns():
    prof = EquipmentProfile(name="Mellanbas", min_freq_hz=80.0, verified=True)
    s = ChainSettings().with_band(1, EQBand(kind="peak", freq_hz=50, gain_db=6.0, q=1.0))
    rep = SafetyEngine().evaluate(s, FS, prof)
    assert any(i.code == "BOOST_BELOW_SAFE_RANGE" for i in rep.issues)
    assert not any(i.code == "PROFILE_UNVERIFIED" for i in rep.issues)


def test_no_profile_is_reported_as_info_not_assumed_safe():
    rep = SafetyEngine().evaluate(ChainSettings(), FS)
    issue = next(i for i in rep.issues if i.code == "NO_PROFILE")
    assert issue.severity == Severity.INFO


def test_observe_meters_flags_clipping():
    m = MeterSnapshot((0.0, 0.0), (-6.0, -6.0), (-3.0, -3.0), (-9.0, -9.0), input_clipped=True)
    assert any(i.code == "INPUT_CLIPPING" for i in SafetyEngine().observe_meters(m))


# ---------------- Presets ----------------
def test_preset_roundtrip(tmp_path):
    s = ChainSettings().replace(master_gain_db=-20.0).with_band(
        2, EQBand(kind="peak", freq_hz=333, gain_db=4.5, q=2.2)
    )
    path = tmp_path / "p.json"
    save_preset(path, PresetFile(name="test", settings=s))
    assert load_preset(path).settings == s


def test_overwrite_creates_backup(tmp_path):
    path = tmp_path / "p.json"
    save_preset(path, PresetFile(name="a", settings=ChainSettings()))
    save_preset(path, PresetFile(name="b", settings=ChainSettings()))
    assert (tmp_path / "p.json.bak").exists()
    assert json.loads((tmp_path / "p.json.bak").read_text())["name"] == "a"


def _write(tmp_path, obj):
    p = tmp_path / "x.json"
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")
    return p


def _valid_dict():
    return json.loads(PresetFile(name="n", settings=ChainSettings()).model_dump_json())


def test_invalid_presets_are_rejected(tmp_path):
    with pytest.raises(PresetError):
        load_preset(_write(tmp_path, "{not json"))
    with pytest.raises(PresetError):
        load_preset(_write(tmp_path, "[1,2,3]"))

    d = _valid_dict()
    d["unexpected"] = "__import__('os').system('x')"
    with pytest.raises(PresetError):
        load_preset(_write(tmp_path, d))

    d = _valid_dict()
    d["settings"]["eq_bands"][0]["freq_hz"] = 99999
    with pytest.raises(PresetError):
        load_preset(_write(tmp_path, d))

    d = _valid_dict()
    d["settings"]["master_gain_db"] = 40
    with pytest.raises(PresetError):
        load_preset(_write(tmp_path, d))

    text = json.dumps(_valid_dict()).replace('"master_gain_db": -12.0', '"master_gain_db": NaN')
    with pytest.raises(PresetError):
        load_preset(_write(tmp_path, text))

    d = _valid_dict()
    d["schema_version"] = CURRENT_SCHEMA_VERSION + 1
    with pytest.raises(PresetError):
        load_preset(_write(tmp_path, d))

    del d["schema_version"]
    with pytest.raises(PresetError):
        load_preset(_write(tmp_path, d))


def test_oversized_preset_rejected(tmp_path):
    p = tmp_path / "big.json"
    p.write_text(" " * 1_100_000)
    with pytest.raises(PresetError):
        load_preset(p)


def test_library_sanitizes_names_and_stays_inside_directory(tmp_path):
    lib = PresetLibrary(tmp_path / "lib")
    path = lib.save("../../evil", ChainSettings())
    assert path.parent == (tmp_path / "lib").resolve()
    assert lib.list_names()
    with pytest.raises(PresetError):
        lib.save("   ...  ", ChainSettings())


def test_library_import_export(tmp_path):
    lib = PresetLibrary(tmp_path / "lib")
    lib.save("Min", ChainSettings().replace(master_gain_db=-30.0))
    dest = tmp_path / "export.json"
    lib.export_to("Min", dest)
    lib2 = PresetLibrary(tmp_path / "lib2")
    name = lib2.import_file(dest)
    assert lib2.load(name).settings.master_gain_db == -30.0
    dest.write_text('{"schema_version": 1}')
    with pytest.raises(PresetError):
        lib2.import_file(dest)


# ---------------- Store ----------------
def test_store_undo_redo_and_notifications():
    store = SettingsStore()
    seen = []
    store.subscribe(seen.append)
    a = store.current.replace(master_gain_db=-20.0)
    b = a.replace(master_gain_db=-10.0)
    store.set(a)
    store.set(b)
    assert store.undo() and store.current == a
    assert store.undo() and store.current == ChainSettings()
    assert not store.undo()
    assert store.redo() and store.current == a
    store.set(b.replace(mute=True))
    assert not store.can_redo
    assert len(seen) >= 5


def test_store_coalesces_drags_within_window():
    t = [0.0]
    store = SettingsStore(clock=lambda: t[0], coalesce_window_s=0.5)
    base = store.current
    for i in range(10):
        t[0] += 0.05
        store.set(base.replace(master_gain_db=-12.0 + i + 1), coalesce_key="master")
    assert store.undo() and store.current == base
    assert not store.can_undo


def test_store_ab_toggle():
    store = SettingsStore()
    store.set(store.current.replace(master_gain_db=-30.0))
    assert store.toggle_ab() == "B"
    assert store.current.master_gain_db == -12.0
    store.set(store.current.replace(master_gain_db=-6.0))
    assert store.toggle_ab() == "A"
    assert store.current.master_gain_db == -30.0
