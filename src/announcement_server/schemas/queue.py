"""Schema untuk endpoint Queue System (/speak, /queue, /clear)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from announcement_server.queueing.models import AnnouncementType, QueueItem, QueueItemStatus, QueuePriority


class SpeakRequest(BaseModel):
    """Request body untuk POST /speak.

    Sejak Phase 7, satu endpoint yang sama mendukung dua sumber audio
    (dipilih lewat ``type``), persis seperti contoh API pada ROADMAP.md:

    - ``type="tts"`` (default, perilaku Phase 1-6 tanpa perubahan): wajib
      mengisi ``text``.
    - ``type="audio"``: memutar file audio statis (bell/alarm/jingle/MP3/WAV
      apa pun) yang sudah ada di ``announcement.sounds_dir`` — wajib
      mengisi ``file``, ``text`` diabaikan.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "type": "tts",
                    "text": "Nomor antrean A001, silakan menuju loket 3.",
                    "priority": "normal",
                    "voice": None,
                    "speed": 1.0,
                    "pitch": 1.0,
                    "volume": 1.0,
                },
                {
                    "type": "audio",
                    "file": "sounds/bell.mp3",
                    "priority": "high",
                },
            ]
        }
    )

    type: AnnouncementType = Field(
        default=AnnouncementType.TTS,
        description="Sumber audio pengumuman ini: 'tts' (sintesis dari `text`) atau 'audio' (file statis dari `file`).",
    )
    engine: str | None = Field(
        default=None,
        max_length=200,
        description="Nama TTS engine yang dipakai (mis. 'piper'). Kosongkan (null) untuk memakai engine default "
        "server (perilaku V1, tidak berubah). Mengembalikan error jika nama engine tidak dikenali/tidak tersedia "
        "(tidak fallback diam-diam ke engine default). Diabaikan jika type='audio'.",
    )
    text: str | None = Field(
        default=None,
        max_length=1000,
        description="Teks pengumuman yang akan diucapkan. WAJIB diisi (tidak boleh kosong) jika type='tts'.",
    )
    file: str | None = Field(
        default=None,
        max_length=500,
        description="Path file audio (relatif terhadap announcement.sounds_dir pada config.yaml), "
        "mis. 'sounds/bell.mp3'. WAJIB diisi jika type='audio'.",
    )
    priority: QueuePriority = Field(
        default=QueuePriority.NORMAL,
        description="Prioritas pengumuman: urgent > high > normal > low",
    )
    voice: str | None = Field(
        default=None,
        max_length=200,
        description="Nama voice/model TTS. Kosongkan (null) untuk memakai default server (tts.default_voice). "
        "Diabaikan jika type='audio'.",
    )
    speed: float = Field(
        default=1.0,
        ge=0.5,
        le=2.0,
        description="Kecepatan bicara. 1.0 = normal, <1.0 = lebih lambat, >1.0 = lebih cepat. Diabaikan jika type='audio'.",
    )
    pitch: float = Field(
        default=1.0,
        ge=0.5,
        le=2.0,
        description=(
            "Pitch suara. 1.0 = normal. Catatan: mengubah pitch turut memengaruhi tempo audio "
            "(lihat AudioProcessor.apply_pitch untuk detail keterbatasan teknik yang dipakai). "
            "Diabaikan jika type='audio'."
        ),
    )
    volume: float = Field(
        default=1.0,
        ge=0.0,
        le=2.0,
        description="Volume relatif. 1.0 = normal, 0.0 = bisu, 2.0 = 2x lebih keras.",
    )

    @model_validator(mode="after")
    def _validate_source_by_type(self) -> "SpeakRequest":
        """Memastikan field yang relevan dengan `type` benar-benar terisi.

        Divalidasi di sini (bukan lewat `Field(min_length=1)` langsung pada
        `text`/`file`) karena keduanya kini opsional pada level schema —
        wajib-tidaknya baru bisa ditentukan setelah `type` diketahui.
        """
        if self.type == AnnouncementType.TTS:
            if not self.text or not self.text.strip():
                raise ValueError("`text` wajib diisi (tidak boleh kosong) untuk type='tts'.")
        else:
            if not self.file or not self.file.strip():
                raise ValueError("`file` wajib diisi (tidak boleh kosong) untuk type='audio'.")
        return self

    @property
    def resolved_text(self) -> str:
        """Teks yang disimpan pada `QueueItem.text` untuk item ini.

        Untuk `type='tts'`, ini SELALU `self.text` (dijamin non-kosong oleh
        validator di atas). Untuk `type='audio'`, `text` opsional dan boleh
        dikosongkan pada request — jika begitu, dibuat teks tampilan
        otomatis dari nama file supaya `GET /queue` tetap informatif alih-alih
        menampilkan string kosong.
        """
        if self.type == AnnouncementType.TTS:
            return self.text  # type: ignore[return-value] - dijamin non-None oleh validator
        return self.text.strip() if self.text and self.text.strip() else f"[audio] {self.file}"


class QueueItemResponse(BaseModel):
    """Response body yang merepresentasikan satu item antrean."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: AnnouncementType = Field(description="Sumber audio item ini: 'tts' atau 'audio' (Phase 7)")
    text: str
    file: str | None = Field(default=None, description="Path file audio statis untuk type='audio'. null untuk type='tts'.")
    priority: QueuePriority
    status: QueueItemStatus
    created_at: datetime
    updated_at: datetime
    error_message: str | None = None
    engine: str | None = Field(
        default=None,
        description="Nama TTS engine yang dipakai untuk item ini. null berarti memakai engine default server "
        "(diabaikan jika type='audio').",
    )
    voice: str = Field(description="Voice/model TTS yang dipakai untuk item ini (diabaikan jika type='audio')")
    speed: float = Field(description="Kecepatan bicara yang dipakai untuk item ini (diabaikan jika type='audio')")
    pitch: float = Field(description="Pitch yang dipakai untuk item ini (diabaikan jika type='audio')")
    volume: float = Field(description="Volume yang dipakai untuk item ini")
    audio_file_path: str | None = Field(
        default=None, description="Path file audio siap-putar (terisi setelah selesai diproses, dari TTS maupun file statis)"
    )
    cache_hit: bool | None = Field(
        default=None,
        description="True jika audio diambil dari cache (TTS) atau file WAV dipakai langsung/hasil konversi sudah ada (audio)",
    )
    position: int | None = Field(
        default=None,
        description="Posisi 1-based di antara item PENDING (1 = akan diproses berikutnya). null jika bukan PENDING.",
    )

    @classmethod
    def from_item(cls, item: QueueItem, *, position: int | None = None) -> "QueueItemResponse":
        """Factory untuk membangun response dari QueueItem domain + posisi opsional.

        Field response `type`/`file` (nama yang dipakai pada request Phase
        7) di-mapping dari field domain `announcement_type`/`source_file`
        (lihat `queueing/models.py`) — nama domain sengaja lebih deskriptif
        karena `type`/`file` generik bisa ambigu di luar konteks HTTP.
        """
        data = item.model_dump()
        data["type"] = data.pop("announcement_type")
        data["file"] = data.pop("source_file")
        return cls(**data, position=position)


class QueueListResponse(BaseModel):
    """Response body untuk GET /queue."""

    items: list[QueueItemResponse]
    count: int = Field(description="Jumlah item pada response ini")


class ClearResponse(BaseModel):
    """Response body untuk POST /clear."""

    cleared_count: int = Field(description="Jumlah item PENDING yang berhasil dibatalkan")
