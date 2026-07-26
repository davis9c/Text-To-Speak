"""Unit test untuk event emission (Phase 9) pada PlaybackManager.

Melengkapi ``test_playback_manager.py`` (Phase 4, tidak diubah) — memakai
ulang ``FakeSoundDevice``/``FakeStream``/``_make_wav_bytes`` dari sana
(bukan duplikat). Karena event dijadwalkan lewat
``asyncio.run_coroutine_threadsafe`` (lihat catatan desain pada
``playback/manager.py``), test di sini SELALU memberi kesempatan loop
untuk benar-benar menjalankan coroutine yang dijadwalkan (``asyncio.sleep(0)``
setelah aksi yang memicu event) sebelum memeriksa hasilnya.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest

from announcement_server.playback.device_manager import AudioDeviceManager
from announcement_server.playback.manager import PlaybackManager

from tests.test_playback_manager import FakeSoundDevice, _make_wav_bytes


class RecordingEventPublisher:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def __call__(self, event_type: str, data: dict) -> None:
        self.events.append((event_type, dict(data)))


@pytest.fixture(autouse=True)
def reset_fake_streams():
    FakeSoundDevice.created_streams = []
    yield


@pytest.fixture()
def device_manager() -> AudioDeviceManager:
    return AudioDeviceManager(sd_module=FakeSoundDevice)


@pytest.fixture()
def recorder() -> RecordingEventPublisher:
    return RecordingEventPublisher()


@pytest.fixture()
def playback_manager(device_manager: AudioDeviceManager, recorder: RecordingEventPublisher) -> PlaybackManager:
    return PlaybackManager(device_manager, sd_module=FakeSoundDevice, on_event=recorder)


@pytest.fixture()
def wav_file(tmp_path: Path) -> Path:
    path = tmp_path / "test.wav"
    path.write_bytes(_make_wav_bytes(n_frames=1000))
    return path


async def test_play_emits_speaking_event(
    playback_manager: PlaybackManager, wav_file: Path, recorder: RecordingEventPublisher
) -> None:
    await playback_manager.play(str(wav_file))

    assert len(recorder.events) == 1
    event_type, data = recorder.events[0]
    assert event_type == "speaking"
    assert data["file"] == str(wav_file)


async def test_pause_emits_pause_event(
    playback_manager: PlaybackManager, wav_file: Path, recorder: RecordingEventPublisher
) -> None:
    await playback_manager.play(str(wav_file))
    recorder.events.clear()

    playback_manager.pause()
    await asyncio.sleep(0)  # beri kesempatan loop menjalankan coroutine yang dijadwalkan run_coroutine_threadsafe

    assert len(recorder.events) == 1
    event_type, _data = recorder.events[0]
    assert event_type == "pause"


async def test_resume_emits_resume_event(
    playback_manager: PlaybackManager, wav_file: Path, recorder: RecordingEventPublisher
) -> None:
    await playback_manager.play(str(wav_file))
    playback_manager.pause()
    await asyncio.sleep(0)
    recorder.events.clear()

    playback_manager.resume()
    await asyncio.sleep(0)

    assert len(recorder.events) == 1
    event_type, _data = recorder.events[0]
    assert event_type == "resume"


async def test_stop_emits_idle_event_when_was_active(
    playback_manager: PlaybackManager, wav_file: Path, recorder: RecordingEventPublisher
) -> None:
    await playback_manager.play(str(wav_file))
    recorder.events.clear()

    await playback_manager.stop()

    assert len(recorder.events) == 1
    event_type, _data = recorder.events[0]
    assert event_type == "idle"


async def test_stop_when_already_idle_does_not_emit(
    playback_manager: PlaybackManager, recorder: RecordingEventPublisher
) -> None:
    await playback_manager.stop()  # belum pernah play() sama sekali
    assert recorder.events == []


async def test_natural_finish_emits_idle_event(
    playback_manager: PlaybackManager, wav_file: Path, recorder: RecordingEventPublisher
) -> None:
    """Simulasi frame audio habis SECARA ALAMI (di dalam callback native thread, dipanggil
    manual di sini via FakeStream) — HARUS memicu event 'idle', bukan hanya lewat stop()/pause()."""
    await playback_manager.play(str(wav_file))
    recorder.events.clear()
    stream = FakeSoundDevice.created_streams[-1]

    # Kirim frame dalam jumlah besar (melebihi total 1000 frame file). Panggilan PERTAMA
    # hanya mengonsumsi sisa frame yang ada (belum mendeteksi habis); panggilan KEDUA baru
    # mendeteksi `remaining <= 0`, menandai IDLE, dan menjadwalkan event.
    outdata = np.zeros((2000, 1), dtype=np.int16)
    stream.callback(outdata, 2000, None, None)
    with pytest.raises(FakeSoundDevice.CallbackStop):
        stream.callback(outdata, 2000, None, None)
    await asyncio.sleep(0)

    assert len(recorder.events) == 1
    event_type, _data = recorder.events[0]
    assert event_type == "idle"


async def test_default_on_event_is_noop_and_does_not_raise(device_manager: AudioDeviceManager, wav_file: Path) -> None:
    """Tanpa `on_event` (default), seluruh method tetap berjalan normal — perilaku Phase 1-8 tidak berubah."""
    manager = PlaybackManager(device_manager, sd_module=FakeSoundDevice)
    await manager.play(str(wav_file))
    manager.pause()
    manager.resume()
    await manager.stop()
    # Tidak melempar apa pun -> lulus.
