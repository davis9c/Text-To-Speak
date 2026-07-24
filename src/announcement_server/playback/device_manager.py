"""Audio Device Manager.

Membungkus ``sounddevice.query_devices()`` untuk enumerasi output device
yang tersedia di sistem (speaker, headphone, sound card TOA via USB/3.5mm,
dsb) dan validasi id device sebelum dipakai untuk playback.

Desain penting — dependency injection untuk modul ``sounddevice``:
Parameter ``sd_module`` di constructor SENGAJA ada (default ``None`` ->
lazy-import ``sounddevice`` asli) supaya kelas ini bisa diuji tanpa
memerlukan hardware audio maupun PortAudio native library ter-install
(mis. di server CI/build tanpa sound card). Di lingkungan production
(Windows, dengan speaker/TOA terpasang), cukup panggil
``AudioDeviceManager()`` tanpa argumen — ``sounddevice`` asli otomatis
dipakai.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from announcement_server.core.exceptions import AudioDeviceNotFoundError
from announcement_server.playback.models import AudioDevice

logger = logging.getLogger(__name__)


class SoundDeviceModule(Protocol):
    """Kontrak minimal dari modul ``sounddevice`` yang dipakai di sini.

    Dipakai sebagai type hint untuk parameter injeksi ``sd_module`` —
    baik ``sounddevice`` asli maupun fake module di unit test sama-sama
    harus memenuhi kontrak ini.
    """

    default: Any

    def query_devices(self) -> list[dict[str, Any]]: ...


def _default_sounddevice_module() -> SoundDeviceModule:
    import sounddevice as sd  # import lokal: baru dibutuhkan saat benar-benar dipakai di Windows

    return sd


class AudioDeviceManager:
    """Enumerasi & validasi output audio device pada sistem."""

    def __init__(self, sd_module: SoundDeviceModule | None = None) -> None:
        self._sd = sd_module if sd_module is not None else _default_sounddevice_module()

    def list_output_devices(self) -> list[AudioDevice]:
        """Mengembalikan seluruh device yang punya minimal 1 output channel."""
        raw_devices = self._sd.query_devices()
        default_output_index = self._get_default_output_index()

        devices: list[AudioDevice] = []
        for index, device in enumerate(raw_devices):
            if device.get("max_output_channels", 0) <= 0:
                continue  # device input-only (mis. microphone), bukan output
            devices.append(
                AudioDevice(
                    id=index,
                    name=device.get("name", f"Device {index}"),
                    max_output_channels=device["max_output_channels"],
                    default_samplerate=float(device.get("default_samplerate", 0.0)),
                    is_default=(index == default_output_index),
                )
            )
        return devices

    def get_device(self, device_id: int) -> AudioDevice:
        """Mengembalikan detail satu device. Melempar AudioDeviceNotFoundError jika tidak ada."""
        for device in self.list_output_devices():
            if device.id == device_id:
                return device
        raise AudioDeviceNotFoundError(
            f"Output device dengan id {device_id} tidak ditemukan.",
            details={"requested_device_id": device_id},
        )

    def validate_device_id(self, device_id: int) -> None:
        """Memastikan device_id valid & merupakan output device. Melempar error jika tidak."""
        self.get_device(device_id)

    def _get_default_output_index(self) -> int | None:
        try:
            # sd.default.device biasanya berupa tuple (input_index, output_index)
            default_device = self._sd.default.device
            if isinstance(default_device, (tuple, list)) and len(default_device) >= 2:
                return int(default_device[1])
            return int(default_device)
        except Exception:  # noqa: BLE001 - kegagalan deteksi default tidak boleh menghentikan enumerasi device
            logger.debug("Gagal mendeteksi default output device index.", exc_info=True)
            return None
