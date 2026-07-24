"""Unit test untuk PlaybackManager, memakai fake sounddevice module (tidak butuh hardware audio).

Test di sini secara khusus memverifikasi bagian paling riskan dari
implementasi: state playback yang diakses dari "callback thread" (di sini
disimulasikan dengan memanggil callback secara manual), dan bahwa
pause/resume TIDAK kehilangan/mereset posisi playback.
"""

from __future__ import annotations

import asyncio
import io
import struct
import wave
from pathlib import Path

import numpy as np
import pytest

from announcement_server.core.exceptions import (
    AudioFileNotFoundError,
    PlaybackStateError,
)
from announcement_server.playback.device_manager import AudioDeviceManager
from announcement_server.playback.manager import PlaybackManager
from announcement_server.playback.models import PlaybackState


class FakeStream:
    """Stream palsu: menyimpan callback tapi tidak auto-invoke (dipanggil manual di test)."""

    def __init__(self, callback, **kwargs) -> None:
        self.callback = callback
        self.kwargs = kwargs
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def close(self) -> None:
        self.closed = True


class FakeSoundDevice:
    class CallbackStop(Exception):
        pass

    class default:
        device = (0, 0)

    created_streams: list[FakeStream] = []

    @staticmethod
    def query_devices():
        return [{"name": "Fake Speaker", "max_output_channels": 2, "default_samplerate": 22050.0}]

    @classmethod
    def OutputStream(cls, callback, **kwargs):  # noqa: N802 - nama API sounddevice asli
        stream = FakeStream(callback, **kwargs)
        cls.created_streams.append(stream)
        return stream


def _make_wav_bytes(n_frames: int = 1000, channels: int = 1, rate: int = 22050) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(struct.pack(f"<{n_frames * channels}h", *range(n_frames * channels)))
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def reset_fake_streams():
    FakeSoundDevice.created_streams = []
    yield


@pytest.fixture()
def device_manager() -> AudioDeviceManager:
    return AudioDeviceManager(sd_module=FakeSoundDevice)


@pytest.fixture()
def playback_manager(device_manager: AudioDeviceManager) -> PlaybackManager:
    return PlaybackManager(device_manager, sd_module=FakeSoundDevice)


@pytest.fixture()
def wav_file(tmp_path: Path) -> Path:
    path = tmp_path / "test.wav"
    path.write_bytes(_make_wav_bytes(n_frames=1000))
    return path


async def test_play_missing_file_raises_error(playback_manager: PlaybackManager) -> None:
    with pytest.raises(AudioFileNotFoundError):
        await playback_manager.play("/path/tidak/ada.wav")


async def test_play_starts_stream_and_sets_state_playing(playback_manager: PlaybackManager, wav_file: Path) -> None:
    await playback_manager.play(str(wav_file))

    assert playback_manager.state == PlaybackState.PLAYING
    assert playback_manager.current_file == str(wav_file)
    stream = FakeSoundDevice.created_streams[-1]
    assert stream.started is True


async def test_callback_fills_outdata_with_real_samples(playback_manager: PlaybackManager, wav_file: Path) -> None:
    await playback_manager.play(str(wav_file))
    stream = FakeSoundDevice.created_streams[-1]

    outdata = np.zeros((100, 1), dtype=np.int16)
    stream.callback(outdata, 100, None, None)

    assert not (outdata == 0).all()


async def test_pause_sends_silence_without_advancing_position(playback_manager: PlaybackManager, wav_file: Path) -> None:
    await playback_manager.play(str(wav_file))
    stream = FakeSoundDevice.created_streams[-1]
    stream.callback(np.zeros((100, 1), dtype=np.int16), 100, None, None)  # majukan posisi ke frame 100

    playback_manager.pause()
    assert playback_manager.state == PlaybackState.PAUSED

    outdata = np.zeros((100, 1), dtype=np.int16)
    stream.callback(outdata, 100, None, None)
    assert (outdata == 0).all(), "saat PAUSED, callback harus mengirim silence, bukan lanjut membaca sample"


async def test_resume_continues_from_same_position_not_from_start(
    playback_manager: PlaybackManager, wav_file: Path
) -> None:
    await playback_manager.play(str(wav_file))
    stream = FakeSoundDevice.created_streams[-1]
    stream.callback(np.zeros((100, 1), dtype=np.int16), 100, None, None)  # posisi -> 100

    playback_manager.pause()
    stream.callback(np.zeros((100, 1), dtype=np.int16), 100, None, None)  # tidak boleh mengubah posisi
    playback_manager.resume()

    outdata = np.zeros((100, 1), dtype=np.int16)
    stream.callback(outdata, 100, None, None)

    with wave.open(str(wav_file), "rb") as reader:
        raw = reader.readframes(reader.getnframes())
    original = np.frombuffer(raw, dtype=np.int16).reshape(-1, 1)

    assert (outdata == original[100:200]).all(), "resume harus melanjutkan dari frame ke-100, bukan mengulang dari 0"


async def test_pause_when_not_playing_raises_state_error(playback_manager: PlaybackManager, wav_file: Path) -> None:
    with pytest.raises(PlaybackStateError):
        playback_manager.pause()  # belum ada playback sama sekali (state IDLE)


async def test_pause_twice_raises_state_error(playback_manager: PlaybackManager, wav_file: Path) -> None:
    await playback_manager.play(str(wav_file))
    playback_manager.pause()
    with pytest.raises(PlaybackStateError):
        playback_manager.pause()


async def test_resume_when_playing_raises_state_error(playback_manager: PlaybackManager, wav_file: Path) -> None:
    await playback_manager.play(str(wav_file))
    with pytest.raises(PlaybackStateError):
        playback_manager.resume()  # sudah PLAYING, bukan PAUSED


async def test_stop_resets_state_to_idle_and_closes_stream(playback_manager: PlaybackManager, wav_file: Path) -> None:
    await playback_manager.play(str(wav_file))
    stream = FakeSoundDevice.created_streams[-1]

    await playback_manager.stop()

    assert playback_manager.state == PlaybackState.IDLE
    assert playback_manager.current_file is None
    assert stream.closed is True


async def test_stop_is_idempotent(playback_manager: PlaybackManager) -> None:
    await playback_manager.stop()  # belum pernah play() sama sekali
    await playback_manager.stop()  # dipanggil dua kali, tidak boleh error
    assert playback_manager.state == PlaybackState.IDLE


async def test_playback_auto_stops_when_frames_exhausted(playback_manager: PlaybackManager, wav_file: Path) -> None:
    await playback_manager.play(str(wav_file))
    stream = FakeSoundDevice.created_streams[-1]

    stream.callback(np.zeros((1000, 1), dtype=np.int16), 1000, None, None)  # habiskan semua 1000 frame

    with pytest.raises(FakeSoundDevice.CallbackStop):
        stream.callback(np.zeros((100, 1), dtype=np.int16), 100, None, None)

    assert playback_manager.state == PlaybackState.IDLE


async def test_play_stops_previous_playback_first(playback_manager: PlaybackManager, wav_file: Path) -> None:
    await playback_manager.play(str(wav_file))
    first_stream = FakeSoundDevice.created_streams[-1]

    await playback_manager.play(str(wav_file))  # play lagi tanpa stop() manual dulu

    assert first_stream.closed is True, "playback sebelumnya harus otomatis dihentikan"
    assert playback_manager.state == PlaybackState.PLAYING


async def test_select_device_delegates_validation_to_device_manager(playback_manager: PlaybackManager) -> None:
    playback_manager.select_device(0)
    assert playback_manager.selected_device_id == 0


async def test_select_invalid_device_raises_error(playback_manager: PlaybackManager) -> None:
    from announcement_server.core.exceptions import AudioDeviceNotFoundError

    with pytest.raises(AudioDeviceNotFoundError):
        playback_manager.select_device(999)


# --- wait_until_finished (Phase 5) ------------------------------------------


async def test_wait_until_finished_returns_immediately_when_idle(playback_manager: PlaybackManager) -> None:
    """Tanpa playback aktif sama sekali, wait_until_finished() tidak boleh menunggu selamanya."""
    await asyncio.wait_for(playback_manager.wait_until_finished(), timeout=1.0)


async def test_wait_until_finished_blocks_while_playing(
    playback_manager: PlaybackManager, wav_file: Path
) -> None:
    await playback_manager.play(str(wav_file))

    waiter = asyncio.ensure_future(playback_manager.wait_until_finished())
    await asyncio.sleep(0.05)
    assert not waiter.done(), "selagi PLAYING, wait_until_finished() belum boleh selesai"

    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    # Cancelling `waiter` melepas TASK asyncio-nya, tapi thread executor yang
    # menjalankan `_finished_event.wait()` (blocking) di baliknya masih hidup
    # sampai event benar-benar di-set. stop() di sini memastikan thread tsb
    # dilepas dengan bersih, bukan menggantung sampai proses test berakhir.
    await playback_manager.stop()


async def test_wait_until_finished_completes_when_frames_exhausted(
    playback_manager: PlaybackManager, wav_file: Path
) -> None:
    await playback_manager.play(str(wav_file))
    stream = FakeSoundDevice.created_streams[-1]

    waiter = asyncio.ensure_future(playback_manager.wait_until_finished())
    await asyncio.sleep(0.02)
    assert not waiter.done()

    with pytest.raises(FakeSoundDevice.CallbackStop):
        stream.callback(np.zeros((1000, 1), dtype=np.int16), 1000, None, None)  # habiskan semua frame

    await asyncio.wait_for(waiter, timeout=1.0)
    assert playback_manager.state == PlaybackState.IDLE


async def test_wait_until_finished_completes_when_stopped_externally(
    playback_manager: PlaybackManager, wav_file: Path
) -> None:
    await playback_manager.play(str(wav_file))

    waiter = asyncio.ensure_future(playback_manager.wait_until_finished())
    await asyncio.sleep(0.02)
    assert not waiter.done()

    await playback_manager.stop()

    await asyncio.wait_for(waiter, timeout=1.0)
