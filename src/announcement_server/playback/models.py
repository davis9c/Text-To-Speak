"""Model data untuk domain Audio Playback."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PlaybackState(str, Enum):
    """Status siklus hidup playback saat ini."""

    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"


@dataclass(frozen=True, slots=True)
class AudioDevice:
    """Representasi satu output audio device pada sistem."""

    id: int
    name: str
    max_output_channels: int
    default_samplerate: float
    is_default: bool
