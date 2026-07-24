r"""Script bantu MANUAL untuk menguji Audio Playback Layer (Phase 4) secara langsung di Windows.

Ini BUKAN bagian dari server/API (roadmap Phase 4 tidak menyediakan endpoint
HTTP untuk memicu playback — hanya kontrol pause/resume/stop/pilih-device;
memicu playback dari sebuah item antrean otomatis adalah scope Phase 5).
Script ini murni alat bantu verifikasi lokal supaya kamu bisa BENAR-BENAR
MENDENGAR bahwa PlaybackManager berfungsi di komputer Windows kamu.

Cara pakai (PowerShell, dari root project):

    .\venv\Scripts\Activate.ps1
    $env:PYTHONPATH = "$PWD\src"
    python scripts\manual_test_playback.py "cache\audio\<nama_file>.wav"

Selama audio diputar, ketik salah satu perintah lalu Enter:
    p  -> pause
    r  -> resume
    s  -> stop
    q  -> keluar dari script
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from announcement_server.playback.device_manager import AudioDeviceManager  # noqa: E402
from announcement_server.playback.manager import PlaybackManager  # noqa: E402


async def main() -> None:
    if len(sys.argv) < 2:
        print("Pemakaian: python scripts\\manual_test_playback.py <path_ke_file.wav>")
        sys.exit(1)

    wav_path = Path(sys.argv[1])
    if not wav_path.is_file():
        print(f"File tidak ditemukan: {wav_path}")
        sys.exit(1)

    device_manager = AudioDeviceManager()
    playback_manager = PlaybackManager(device_manager)

    print("=== Daftar output device yang terdeteksi ===")
    for device in device_manager.list_output_devices():
        marker = " (default)" if device.is_default else ""
        print(f"  [{device.id}] {device.name}{marker}")
    print()

    print(f"Memutar: {wav_path}")
    await playback_manager.play(str(wav_path))

    print("\nPerintah: [p]ause, [r]esume, [s]top, [q]uit\n")
    loop = asyncio.get_event_loop()
    while True:
        command = (await loop.run_in_executor(None, input, "> ")).strip().lower()
        if command == "p":
            try:
                playback_manager.pause()
                print(f"State: {playback_manager.state.value}")
            except Exception as exc:  # noqa: BLE001
                print(f"Error: {exc}")
        elif command == "r":
            try:
                playback_manager.resume()
                print(f"State: {playback_manager.state.value}")
            except Exception as exc:  # noqa: BLE001
                print(f"Error: {exc}")
        elif command == "s":
            await playback_manager.stop()
            print(f"State: {playback_manager.state.value}")
        elif command == "q":
            await playback_manager.stop()
            print("Keluar.")
            break
        else:
            print("Perintah tidak dikenali. Pakai: p / r / s / q")


if __name__ == "__main__":
    asyncio.run(main())
