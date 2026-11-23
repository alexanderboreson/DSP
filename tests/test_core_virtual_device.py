"""Tester av realtidskärnan mot en virtuell enhet (simulerad miljö, ingen hårdvara)."""

import threading
import time

import numpy as np
import pytest

from autodsp.analysis import compute_spectrum_db
from autodsp.audio.source import FileSource, load_audio_file
from autodsp.dsp.params import ChainSettings, EQBand
from autodsp.dsp.response import predicted_peak_gain_db
from autodsp.dsp.units import db_to_lin
from helpers import flat_settings, make_core, run_blocks, sine

FS = 48000


def test_safe_startup_output_is_silent_and_transport_frozen():
    core = make_core(armed=False)
    out = run_blocks(core, 10)
    assert np.all(out == 0)
    assert core.source.position == 0


def test_armed_playback_produces_audio_with_soft_fade_in():
    core = make_core()
    out = run_blocks(core, 20)
    assert np.max(np.abs(out)) > 0.3
    assert np.max(np.abs(out[:50])) < 0.05  # fade-in, inget hårt hopp
    assert np.max(np.abs(np.diff(out[:, 0]))) < 0.1


def test_emergency_mute_silences_within_one_block():
    core = make_core()
    run_blocks(core, 10)
    core.safety.emergency_mute()
    b1 = core.process_block(512)
    b2 = core.process_block(512)
    assert b1[-1, 0] == 0.0 and np.max(np.abs(np.diff(b1[:, 0]))) < 0.1
    assert np.all(b2 == 0)
    frozen = core.source.position
    run_blocks(core, 5)
    assert core.source.position == frozen  # transporten står still


def test_device_loss_enters_safe_state_and_requires_rearm():
    core = make_core()
    run_blocks(core, 10)
    core.safety.on_device_lost()
    core.process_block(512)
    assert np.all(core.process_block(512) == 0)
    core.safety.on_device_restored()
    assert np.all(run_blocks(core, 3) == 0)  # inte automatiskt återaktiverad


def test_pause_fades_and_resume_continues_position():
    core = make_core()
    run_blocks(core, 10)
    core.pause()
    b = core.process_block(512)
    assert b[-1, 0] == 0.0
    pos = core.source.position
    run_blocks(core, 3)
    assert core.source.position == pos
    core.play()
    assert np.max(np.abs(run_blocks(core, 5))) > 0.3


def test_large_level_change_switches_through_silence():
    core = make_core(flat_settings(master_gain_db=-30.0), amp=0.5)
    run_blocks(core, 20)
    loud = flat_settings(master_gain_db=-6.0)
    assert abs(predicted_peak_gain_db(loud, FS) - predicted_peak_gain_db(flat_settings(master_gain_db=-30.0), FS)) > 6
    core.post_settings(loud, predicted_peak_gain_db(loud, FS))
    k = core.process_block(512)  # nedtoning
    assert k[-1, 0] == 0.0
    after = run_blocks(core, 20)
    assert np.max(np.abs(np.diff(np.concatenate([k, after])[:, 0]))) < 0.1
    expected = 0.5 * db_to_lin(-6.0)
    assert np.max(np.abs(after[-2048:])) == pytest.approx(expected, rel=0.02)


def test_small_level_change_applies_without_muting():
    core = make_core(flat_settings(master_gain_db=-12.0))
    run_blocks(core, 10)
    new = flat_settings(master_gain_db=-10.0)
    core.post_settings(new, predicted_peak_gain_db(new, FS))
    out = run_blocks(core, 10)
    assert np.max(np.abs(out[:512])) > 0.1  # aldrig tyst under bytet


def test_eq_change_during_playback_is_click_free_and_limited():
    core = make_core(flat_settings(), amp=0.8)
    run_blocks(core, 10)
    s = flat_settings().with_band(4, EQBand(kind="peak", freq_hz=1000, gain_db=12.0, q=1.0))
    core.post_settings(s, predicted_peak_gain_db(s, FS))
    out = run_blocks(core, 30)
    assert np.isfinite(out).all()
    assert np.max(np.abs(out)) <= db_to_lin(-1.0) + 1e-6
    assert np.max(np.abs(np.diff(out[:, 0]))) < 0.3


def test_exception_in_processing_yields_silence_not_crash():
    core = make_core()
    run_blocks(core, 5)

    def boom(_):
        raise RuntimeError("test")

    core.chain.process = boom
    out = core.process_block(512)
    assert out.shape == (512, 2) and np.all(out == 0)
    assert core.fault_count == 1


def test_settings_posted_from_another_thread_while_processing():
    core = make_core(amp=0.9)
    stop = threading.Event()

    def poster():
        i = 0
        while not stop.is_set():
            s = flat_settings(master_gain_db=-30.0 + (i % 25), input_gain_db=float(i % 4))
            core.post_settings(s, predicted_peak_gain_db(s, FS))
            i += 1
            time.sleep(0.002)  # ett GUI postar vid användarinteraktion, inte i en snäv loop

    t = threading.Thread(target=poster)
    t.start()
    try:
        out = run_blocks(core, 300, block=256)
    finally:
        stop.set()
        t.join()
    assert np.isfinite(out).all()
    assert np.max(np.abs(out)) <= db_to_lin(-1.0) + 1e-6
    assert core.fault_count == 0


def test_file_end_stops_and_loop_wraps():
    fs = FS
    core = make_core(seconds=0.2, loop=False)
    out = run_blocks(core, 40)
    assert not core.playing
    assert np.all(out[-1024:] == 0)

    core2 = make_core(seconds=0.2, loop=True)
    out2 = run_blocks(core2, 40)
    assert core2.playing and np.max(np.abs(out2[-4000:])) > 0.3


def test_stop_resets_position_and_replay_works():
    core = make_core(seconds=1.0)
    run_blocks(core, 10)
    core.stop()
    run_blocks(core, 3)
    assert core.source.position == 0
    core.play()
    assert np.max(np.abs(run_blocks(core, 10))) > 0.3


def test_seek_ducks_then_jumps():
    core = make_core(seconds=2.0)
    run_blocks(core, 5)
    core.seek_seconds(1.5)
    first = core.process_block(512)
    assert first[-1, 0] == 0.0
    run_blocks(core, 2)
    assert core.position_s > 1.5


def test_mono_and_multichannel_sources_become_stereo_and_resample():
    mono = sine(1000, 44100, 1.0, 0.5, channels=1)
    src = FileSource(mono, 44100, 48000)
    assert src.length == pytest.approx(48000, abs=2)
    block = src.read(100)
    assert block.shape == (100, 2) and np.allclose(block[:, 0], block[:, 1])
    six = sine(1000, 48000, 0.1, 0.5, channels=6)
    assert FileSource(six, 48000, 48000).read(10).shape == (10, 2)
    with pytest.raises(ValueError):
        FileSource(np.zeros(10), 48000, 48000)


def test_source_with_nan_samples_is_handled(tmp_path):
    from scipy.io import wavfile

    x = (sine(1000, FS, 0.2, 0.5, channels=2)).astype(np.float32)
    x[100, 0] = np.nan
    path = tmp_path / "nan.wav"
    wavfile.write(path, FS, x)
    data, sr = load_audio_file(path)
    assert np.isfinite(data).all() and sr == FS
    core = make_core()
    core.set_source(FileSource(data, sr, FS, loop=True))
    core.play()
    assert np.isfinite(run_blocks(core, 10)).all()


def test_wav_int16_loading(tmp_path):
    from scipy.io import wavfile

    x = (sine(1000, FS, 0.1, 0.5) * 32767).astype(np.int16)
    path = tmp_path / "i16.wav"
    wavfile.write(path, FS, x)
    data, sr = load_audio_file(path)
    assert sr == FS and data.dtype == np.float32
    assert np.max(np.abs(data)) == pytest.approx(0.5, abs=0.01)


def test_spectrum_of_known_sine_reads_correct_level_and_frequency():
    n = 4096
    f = 96 * FS / n  # exakt binmitt
    x = 0.5 * np.sin(2 * np.pi * f * np.arange(n) / FS)
    freqs, db = compute_spectrum_db(x, FS, n)
    k = int(np.argmax(db))
    assert freqs[k] == pytest.approx(f, abs=1e-6)
    assert db[k] == pytest.approx(-6.02, abs=0.1)
    assert np.isfinite(compute_spectrum_db(np.zeros(10), FS, n)[1]).all()


def test_spectrum_tap_returns_recent_output():
    core = make_core()
    run_blocks(core, 30)
    snap = core.spectrum_snapshot(4096)
    assert snap.shape == (4096,) and np.max(np.abs(snap)) > 0.3
