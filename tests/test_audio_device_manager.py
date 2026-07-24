"""Unit test untuk AudioDeviceManager, memakai fake sounddevice module (tidak butuh hardware audio)."""

from __future__ import annotations

import pytest

from announcement_server.core.exceptions import AudioDeviceNotFoundError
from announcement_server.playback.device_manager import AudioDeviceManager


class FakeSoundDevice:
    """Fake module ``sounddevice`` — hanya mengimplementasikan yang dipakai AudioDeviceManager."""

    class default:
        device = (1, 2)  # (input_index, output_index)

    @staticmethod
    def query_devices():
        return [
            {"name": "Microphone (Realtek)", "max_output_channels": 0, "default_samplerate": 44100.0},
            {"name": "Headphone (Realtek)", "max_output_channels": 2, "default_samplerate": 48000.0},
            {"name": "Speaker TOA (USB Audio)", "max_output_channels": 2, "default_samplerate": 44100.0},
        ]


@pytest.fixture()
def device_manager() -> AudioDeviceManager:
    return AudioDeviceManager(sd_module=FakeSoundDevice)


def test_list_output_devices_excludes_input_only_devices(device_manager: AudioDeviceManager) -> None:
    devices = device_manager.list_output_devices()
    assert len(devices) == 2
    assert all(d.max_output_channels > 0 for d in devices)
    assert "Microphone (Realtek)" not in [d.name for d in devices]


def test_list_output_devices_ids_match_original_index(device_manager: AudioDeviceManager) -> None:
    devices = device_manager.list_output_devices()
    ids = [d.id for d in devices]
    assert ids == [1, 2]  # index asli pada query_devices(), bukan re-index dari 0


def test_default_output_device_detected_correctly(device_manager: AudioDeviceManager) -> None:
    devices = {d.id: d for d in device_manager.list_output_devices()}
    assert devices[2].is_default is True
    assert devices[1].is_default is False


def test_get_device_returns_correct_device(device_manager: AudioDeviceManager) -> None:
    device = device_manager.get_device(2)
    assert device.name == "Speaker TOA (USB Audio)"
    assert device.default_samplerate == 44100.0


def test_get_device_unknown_id_raises_not_found(device_manager: AudioDeviceManager) -> None:
    with pytest.raises(AudioDeviceNotFoundError) as exc_info:
        device_manager.get_device(999)
    assert exc_info.value.details["requested_device_id"] == 999


def test_validate_device_id_does_not_raise_for_valid_id(device_manager: AudioDeviceManager) -> None:
    device_manager.validate_device_id(1)  # tidak boleh melempar apa pun


def test_validate_device_id_raises_for_input_only_device(device_manager: AudioDeviceManager) -> None:
    """Device index 0 (microphone) valid secara index tapi bukan output -> harus ditolak."""
    with pytest.raises(AudioDeviceNotFoundError):
        device_manager.validate_device_id(0)
