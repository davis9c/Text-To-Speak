"""Application configuration.

Konfigurasi utama aplikasi dimuat dari file YAML (config/config.yaml) dan
dapat di-override melalui environment variable dengan prefix ``APP_``.

Desain ini dipilih (bukan hardcode / bukan murni .env) karena:
- Operator lapangan (teknisi TOA) lebih familiar mengedit YAML daripada .env.
- YAML mendukung struktur nested (zones, devices, dsb) yang akan tumbuh
  signifikan di fase-fase berikutnya (Multi Zone, Scheduler, dll).
- Environment variable override tetap didukung untuk kebutuhan deployment
  (mis. container / secret injection) tanpa mengubah file config.

Semua model konfigurasi memakai Pydantic v2 (BaseModel/BaseSettings) agar
validasi terjadi di startup (fail-fast), bukan saat runtime di tengah
operasional 24/7.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

# Lokasi default file konfigurasi. Bisa di-override lewat env var CONFIG_PATH
# (ditangani di YamlConfigSettingsSource di bawah).
DEFAULT_CONFIG_PATH = Path("config/config.yaml")


class ServerConfig(BaseModel):
    """Konfigurasi HTTP server (Uvicorn/FastAPI)."""

    host: str = Field(default="0.0.0.0", description="Host bind address")
    port: int = Field(default=8000, ge=1, le=65535, description="Port HTTP server")
    reload: bool = Field(default=False, description="Auto-reload (hanya untuk development)")
    workers: int = Field(default=1, ge=1, description="Jumlah worker Uvicorn")


class LoggingConfig(BaseModel):
    """Konfigurasi logging aplikasi."""

    level: str = Field(default="INFO", description="Level logging global")
    directory: str = Field(default="logs", description="Direktori file log")
    filename: str = Field(default="announcement_server.log", description="Nama file log utama")
    max_bytes: int = Field(default=10_485_760, description="Ukuran maksimum file log sebelum rotasi (bytes)")
    backup_count: int = Field(default=5, description="Jumlah backup file log yang disimpan")
    json_format: bool = Field(default=False, description="Gunakan format JSON untuk log (memudahkan log aggregation)")

    @field_validator("level")
    @classmethod
    def validate_level(cls, value: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        normalized = value.upper()
        if normalized not in allowed:
            raise ValueError(f"logging.level harus salah satu dari {allowed}, diterima: {value!r}")
        return normalized


class AppMetadata(BaseModel):
    """Metadata identitas aplikasi, dipakai antara lain oleh Swagger docs."""

    name: str = Field(default="Announcement Server")
    description: str = Field(
        default="Production Ready Text-to-Speech Announcement Server untuk sistem Public Address (TOA)."
    )
    environment: str = Field(default="development", description="development | staging | production")

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        allowed = {"development", "staging", "production"}
        normalized = value.lower()
        if normalized not in allowed:
            raise ValueError(f"app.environment harus salah satu dari {allowed}, diterima: {value!r}")
        return normalized


class TTSConfig(BaseModel):
    """Konfigurasi TTS Engine (Phase 3)."""

    engine: str = Field(
        default="piper",
        description="Nama engine TTS aktif. Harus terdaftar di EngineFactory (lihat tts/engine_factory.py).",
    )
    piper_binary_path: str = Field(
        default="engines/piper/piper.exe",
        description="Path ke executable Piper (Windows: piper.exe). Piper TIDAK disertakan dalam repo ini "
        "dan harus diunduh terpisah — lihat README.",
    )
    piper_models_dir: str = Field(
        default="engines/piper/models",
        description="Direktori berisi pasangan file model Piper (<voice>.onnx dan <voice>.onnx.json).",
    )
    default_voice: str = Field(
        default="en_US-lessac-medium",
        description="Nama voice default (tanpa ekstensi) yang dipakai jika request tidak menyebutkan voice.",
    )
    generation_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        description="Batas waktu maksimum proses sintesis TTS untuk satu item sebelum dianggap gagal.",
    )
    cache_dir: str = Field(
        default="cache/audio",
        description="Direktori penyimpanan cache audio hasil TTS (key = SHA256 dari parameter sintesis).",
    )


class PlaybackConfig(BaseModel):
    """Konfigurasi Audio Playback (Phase 4) & Announcement Pipeline (Phase 5)."""

    default_device_id: int | None = Field(
        default=None,
        description="ID output device default (lihat GET /devices untuk daftar id). "
        "null = pakai default output device sistem Windows.",
    )
    post_playback_delay_seconds: float = Field(
        default=0.5,
        ge=0.0,
        description="Jeda (detik) setelah satu pengumuman selesai diputar sebelum worker "
        "mulai memproses item antrean berikutnya (tahap 'Delay' pada pipeline Phase 5). "
        "0 = tanpa jeda.",
    )


class ZoneDefinition(BaseModel):
    """Konfigurasi statis satu Zone (Phase 6), dibaca dari ``config.yaml`` (bagian ``zones:``).

    Catatan desain — ``device_id`` (integer) dipakai alih-alih ``device``
    (nama string) seperti pada contoh YAML ilustratif di roadmap, supaya
    konsisten dengan konvensi identifikasi device yang SUDAH ditetapkan
    sejak Phase 4 (``GET /devices`` mengembalikan ``id`` integer, dan
    ``POST /device`` menerima ``device_id`` integer — lihat
    ``playback/device_manager.py``). Mencocokkan device lewat nama string
    akan menambah lapisan resolusi baru yang tidak konsisten dengan API
    Playback yang sudah ada, sehingga sengaja tidak dipakai.

    Zone tambahan (selain ``main``) yang didefinisikan di sini akan
    otomatis dibuat oleh ``ZoneManager`` saat aplikasi startup (lihat
    ``main.py``). Zone juga dapat dibuat/diubah/dihapus secara dinamis
    lewat REST API (``POST /zones``, ``PUT /zones/{name}``,
    ``DELETE /zones/{name}``) tanpa perlu mengedit file ini maupun
    me-restart server.
    """

    device_id: int | None = Field(
        default=None,
        description="ID output device untuk zone ini (lihat GET /devices). null = belum ada device dipilih.",
    )
    enabled: bool = Field(
        default=True,
        description="Jika false, zone dibuat tetapi worker-nya TIDAK berjalan (tidak memproses antrean).",
    )
    volume: float = Field(
        default=1.0,
        ge=0.0,
        le=2.0,
        description="Volume/gain khusus zone ini (analog volume knob per-channel amplifier), diterapkan saat "
        "playback tanpa memengaruhi cache audio TTS yang dipakai bersama seluruh zone.",
    )


class QueueConfig(BaseModel):
    """Konfigurasi Queue System (Phase 2)."""

    max_size: int = Field(
        default=100,
        ge=1,
        description="Jumlah maksimum item berstatus PENDING yang boleh ada di antrean secara bersamaan",
    )
    max_history: int = Field(
        default=1000,
        ge=0,
        description=(
            "Jumlah maksimum riwayat item final (completed/failed/cancelled) yang disimpan di memory "
            "sebelum dipangkas otomatis. Mencegah memory leak pada operasional 24/7."
        ),
    )


def _read_yaml_file(path: Path) -> dict[str, Any]:
    """Membaca file YAML dan mengembalikan dict. Aman terhadap file kosong."""
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


class YamlConfigSettingsSource(PydanticBaseSettingsSource):
    """Settings source kustom yang membaca nilai dari file YAML.

    Ditempatkan dengan prioritas lebih rendah daripada environment variable,
    sehingga env var selalu bisa meng-override nilai YAML (penting untuk
    deployment/production tanpa mengedit file config di server).
    """

    def get_field_value(self, field, field_name):  # type: ignore[override]
        # Tidak dipakai langsung karena kita override __call__ secara penuh.
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        config_path_str = self.config.get("yaml_config_path", str(DEFAULT_CONFIG_PATH))
        return _read_yaml_file(Path(config_path_str))


class AppSettings(BaseSettings):
    """Root settings object untuk seluruh aplikasi.

    Urutan prioritas sumber konfigurasi (tertinggi ke terendah):
    1. Environment variables (prefix APP_, nested delimiter '__')
    2. File YAML (config/config.yaml)
    3. Default value pada masing-masing field
    """

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
        yaml_config_path=str(DEFAULT_CONFIG_PATH),
    )

    app: AppMetadata = Field(default_factory=AppMetadata)
    server: ServerConfig = Field(default_factory=ServerConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    playback: PlaybackConfig = Field(default_factory=PlaybackConfig)
    queue: QueueConfig = Field(default_factory=QueueConfig)
    zones: dict[str, ZoneDefinition] = Field(
        default_factory=dict,
        description="Definisi Zone tambahan (Phase 6), key = nama zone. Zone 'main' SELALU dibuat otomatis "
        "dari config 'playback'/'queue' di atas; jika key 'main' turut didefinisikan di sini, nilainya "
        "meng-override default tsb (device_id/enabled/volume) tanpa mengubah max_size/max_history-nya.",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        yaml_source = YamlConfigSettingsSource(settings_cls)
        # init_settings & env_settings di depan (prioritas lebih tinggi) daripada yaml_source.
        return (init_settings, env_settings, dotenv_settings, yaml_source, file_secret_settings)


@functools.lru_cache(maxsize=1)
def get_settings(config_path: str | None = None) -> AppSettings:
    """Mengembalikan singleton AppSettings (di-cache agar tidak berulang kali parse YAML).

    Dipakai sebagai FastAPI dependency (lihat ``api/deps.py``) sehingga
    mudah di-override saat unit test (``app.dependency_overrides``).
    """
    if config_path:
        return AppSettings(yaml_config_path=config_path)  # type: ignore[call-arg]
    return AppSettings()
