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

from announcement_server.core.exceptions import ConfigurationError

# Lokasi default file konfigurasi. Bisa di-override lewat env var CONFIG_PATH
# (ditangani di YamlConfigSettingsSource di bawah).
DEFAULT_CONFIG_PATH = Path("config/config.yaml")


class ServerConfig(BaseModel):
    """Konfigurasi HTTP server (Uvicorn/FastAPI)."""

    host: str = Field(default="0.0.0.0", description="Host bind address")
    port: int = Field(default=8000, ge=1, le=65535, description="Port HTTP server")
    reload: bool = Field(default=False, description="Auto-reload (hanya untuk development)")
    workers: int = Field(default=1, ge=1, description="Jumlah worker Uvicorn")
    cors_allow_origins: list[str] = Field(
        default_factory=lambda: ["*"],
        description="Daftar origin yang diizinkan mengakses API lewat browser (CORS), mis. untuk dashboard/tester "
        "HTML terpisah (index.html) yang dibuka dari file:// atau origin/port lain. '*' = izinkan semua origin "
        "(cocok untuk development/tooling internal; batasi ke domain spesifik untuk production).",
    )


class LoggingConfig(BaseModel):
    """Konfigurasi logging aplikasi."""

    level: str = Field(default="INFO", description="Level logging global")
    directory: str = Field(default="logs", description="Direktori file log")
    filename: str = Field(default="announcement_server.log", description="Nama file log utama")
    max_bytes: int = Field(default=10_485_760, description="Ukuran maksimum file log sebelum rotasi (bytes)")
    backup_count: int = Field(default=5, description="Jumlah backup file log yang disimpan")
    json_format: bool = Field(default=False, description="Gunakan format JSON untuk log (memudahkan log aggregation)")

    # --- Phase 11 (Monitoring) — log terpisah selain file utama di atas ---
    error_filename: str = Field(default="error.log", description="File khusus log level ERROR/CRITICAL dari seluruh aplikasi")
    playback_filename: str = Field(default="playback.log", description="File khusus log domain Playback (Phase 4/9)")
    worker_filename: str = Field(default="worker.log", description="File khusus log domain Queue Worker/Pipeline (Phase 2/5)")

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
    max_retries: int = Field(
        default=2, ge=0, description="Jumlah percobaan ulang (Phase 14) jika sintesis Piper gagal transien."
    )
    retry_backoff_seconds: float = Field(
        default=1.0, ge=0, description="Delay dasar (detik) antar percobaan ulang, naik eksponensial (Phase 14)."
    )
    cache_max_age_days: float | None = Field(
        default=None,
        ge=0,
        description="Phase 14: file cache lebih tua dari ini (hari) dihapus saat cache cleanup. null = tidak ada batas usia.",
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


class AnnouncementConfig(BaseModel):
    """Konfigurasi Announcement Engine (Phase 7) — file audio statis (bell/alarm/jingle/dsb) di luar TTS.

    Selain TTS (Phase 3), server dapat memutar file audio yang SUDAH ADA
    di disk (WAV/MP3/dst — lihat ``announcement/asset_resolver.py``).
    ``ffmpeg`` bersifat OPSIONAL, persis seperti Piper pada Phase 3
    (graceful degradation): file yang SUDAH berformat WAV tetap bisa
    diputar tanpa ``ffmpeg`` sama sekali; ``ffmpeg`` hanya dibutuhkan
    untuk mengonversi format lain (mis. MP3) ke WAV.
    """

    sounds_dir: str = Field(
        default="sounds",
        description="Direktori berisi file audio statis (bell/alarm/jingle/dst). Path pada request "
        "POST /speak (`file`) SELALU relatif terhadap direktori ini — request tidak dapat "
        "mengakses file di luar direktori ini (dicegah lewat validasi path).",
    )
    ffmpeg_binary_path: str = Field(
        default="ffmpeg",
        description="Path ke executable ffmpeg, atau cukup 'ffmpeg' jika sudah ada di PATH sistem. "
        "Hanya dipakai saat file sumber BUKAN .wav (lihat docstring kelas ini).",
    )
    converted_cache_dir: str = Field(
        default="cache/announcement_audio",
        description="Direktori cache hasil konversi ffmpeg ke WAV (key = SHA256 dari path+mtime+size "
        "file sumber), supaya file yang sama tidak dikonversi ulang setiap kali diputar.",
    )
    conversion_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        description="Batas waktu maksimum proses konversi ffmpeg untuk satu file sebelum dianggap gagal.",
    )
    max_retries: int = Field(
        default=2, ge=0, description="Jumlah percobaan ulang (Phase 14) jika konversi ffmpeg gagal transien."
    )
    retry_backoff_seconds: float = Field(
        default=1.0, ge=0, description="Delay dasar (detik) antar percobaan ulang, naik eksponensial (Phase 14)."
    )
    cache_max_age_days: float | None = Field(
        default=None,
        ge=0,
        description="Phase 14: file cache lebih tua dari ini (hari) dihapus saat cache cleanup. null = tidak ada batas usia.",
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


class SchedulerConfig(BaseModel):
    """Konfigurasi Scheduler (Phase 8) — pemicu pengumuman otomatis berbasis waktu."""

    poll_interval_seconds: float = Field(
        default=5.0,
        gt=0,
        description="Seberapa sering SchedulerManager memeriksa jadwal yang sudah jatuh tempo. "
        "Nilai lebih kecil = lebih presisi tapi lebih sering polling; 5 detik cukup presisi "
        "untuk jadwal berbasis menit (mis. '07:00').",
    )
    timezone: str = Field(
        default="local",
        description="Zona waktu untuk evaluasi jadwal. 'local' (default) memakai waktu sistem "
        "(tanpa tzinfo eksplisit, mengikuti jam OS) — paling sesuai untuk perangkat PA fisik "
        "yang jam sistemnya sudah diset ke waktu setempat. Bisa diisi nama zona IANA eksplisit "
        "(mis. 'Asia/Jakarta') jika server & perangkat PA berada di zona waktu berbeda.",
    )


class ScheduleAnnouncementDefinition(BaseModel):
    """Konfigurasi statis isi pengumuman satu jadwal (bagian dari ``ScheduleDefinition``).

    Field di sini SENGAJA memakai tipe ``str`` polos (bukan mengimpor enum
    ``AnnouncementType``/``QueuePriority`` dari ``queueing.models``) — mengikuti
    prinsip yang sama dengan ``ZoneDefinition`` di atas: ``core/config.py``
    tetap independen dari domain (Clean Architecture, config sebagai lapisan
    paling dasar). Validasi & konversi ke enum domain dilakukan saat
    jadwal ini benar-benar didaftarkan ke ``SchedulerManager`` (lihat
    ``main.py``), persis seperti ``zones:`` diproses saat ini.
    """

    type: str = Field(default="tts", description="'tts' atau 'audio' — lihat AnnouncementType (queueing.models)")
    text: str | None = Field(default=None, description="Wajib diisi jika type='tts'")
    file: str | None = Field(default=None, description="Wajib diisi jika type='audio' (path relatif announcement.sounds_dir)")
    priority: str = Field(default="normal", description="'urgent' | 'high' | 'normal' | 'low'")
    voice: str | None = Field(default=None, description="Diabaikan jika type='audio'")
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    pitch: float = Field(default=1.0, ge=0.5, le=2.0)
    volume: float = Field(default=1.0, ge=0.0, le=2.0)


class ScheduleDefinition(BaseModel):
    """Konfigurasi statis satu Schedule (Phase 8), dibaca dari ``config.yaml`` (bagian ``schedules:``).

    Contoh sesuai ROADMAP.md (07.00 -> Bell, 12.00 -> Istirahat, 15.00 -> Pulang)
    — lihat ``config/config.yaml``. Jadwal tambahan juga bisa dibuat/diubah/dihapus
    secara dinamis lewat REST API (``POST /scheduler``, dst) tanpa restart server,
    persis seperti Zone (Phase 6).
    """

    enabled: bool = Field(default=True, description="Jika false, jadwal terdaftar tapi tidak akan pernah terpicu")
    zone: str = Field(default="main", description="Nama zone tujuan pengumuman (lihat ZoneManager, Phase 6)")
    recurrence: str = Field(description="'daily' | 'weekly' | 'once'")
    time_of_day: str = Field(description="Jam pemicu, format 24-jam 'HH:MM' (mis. '07:00')")
    days_of_week: list[int] | None = Field(
        default=None,
        description="Hanya untuk recurrence='weekly': daftar hari (0=Senin .. 6=Minggu, mengikuti "
        "date.weekday() Python). Wajib diisi (minimal 1 hari) untuk 'weekly'.",
    )
    run_date: str | None = Field(
        default=None, description="Hanya untuk recurrence='once': tanggal pemicu, format 'YYYY-MM-DD'."
    )
    announcement: ScheduleAnnouncementDefinition


class MaintenanceConfig(BaseModel):
    """Konfigurasi Production Hardening (Phase 14)."""

    cache_cleanup_on_startup: bool = Field(
        default=False, description="Jika true, cache TTS & Announcement dibersihkan otomatis saat server startup."
    )
    shutdown_timeout_seconds: float = Field(
        default=15.0, gt=0, description="Batas waktu maksimum graceful shutdown sebelum dipaksa berhenti."
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
    announcement: AnnouncementConfig = Field(default_factory=AnnouncementConfig)
    zones: dict[str, ZoneDefinition] = Field(
        default_factory=dict,
        description="Definisi Zone tambahan (Phase 6), key = nama zone. Zone 'main' SELALU dibuat otomatis "
        "dari config 'playback'/'queue' di atas; jika key 'main' turut didefinisikan di sini, nilainya "
        "meng-override default tsb (device_id/enabled/volume) tanpa mengubah max_size/max_history-nya.",
    )
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    maintenance: MaintenanceConfig = Field(default_factory=MaintenanceConfig)
    schedules: dict[str, ScheduleDefinition] = Field(
        default_factory=dict,
        description="Definisi Schedule statis (Phase 8), key = nama jadwal (unik). Dibuat otomatis saat "
        "startup — bisa juga dibuat/diubah/dihapus secara dinamis lewat REST API (/scheduler) tanpa "
        "restart server, persis seperti 'zones' (Phase 6).",
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


def validate_runtime_config(settings: AppSettings) -> None:
    """Validasi tambahan di luar tipe/range Pydantic (Phase 14 — Production Hardening).

    Dipanggil sekali saat app startup (``main.py``) — memastikan direktori
    yang dibutuhkan (cache, sounds, log) BENAR-BENAR bisa dibuat/ditulis
    SEBELUM server mulai menerima traffic (fail-fast), bukan gagal
    belakangan di tengah pemrosesan request pertama yang membutuhkannya.
    Melempar ``ConfigurationError`` (bukan exception generik) jika gagal.
    """
    directories = {
        "tts.cache_dir": settings.tts.cache_dir,
        "announcement.sounds_dir": settings.announcement.sounds_dir,
        "announcement.converted_cache_dir": settings.announcement.converted_cache_dir,
        "logging.directory": settings.logging.directory,
    }
    for key, directory in directories.items():
        path = Path(directory)
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe_file = path / ".write_test"
            probe_file.write_text("ok")
            probe_file.unlink()
        except OSError as exc:
            raise ConfigurationError(
                f"Direktori untuk '{key}' ('{directory}') tidak bisa dibuat/ditulis: {exc}",
                details={"config_key": key, "directory": directory},
            ) from exc
