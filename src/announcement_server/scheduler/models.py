"""Model domain untuk Scheduler (Phase 8).

``ScheduleEntry`` murni data (pola yang sama seperti ``Zone`` di
``zones/models.py``) — orkestrasi (registry, background loop, enqueue)
ada di ``scheduler/manager.py``. ``compute_next_run`` SENGAJA berupa
fungsi murni (tidak mengakses jam sistem, waktu "sekarang" selalu
diberikan lewat parameter ``after``) supaya mudah diuji tanpa mocking
waktu, dan dipakai baik saat jadwal dibuat maupun setelah setiap kali
terpicu.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from announcement_server.queueing.models import AnnouncementType, QueuePriority


class ScheduleRecurrence(str, Enum):
    """Pola pengulangan satu jadwal (lihat ROADMAP.md Phase 8: Daily/Weekly/One Time)."""

    DAILY = "daily"
    WEEKLY = "weekly"
    ONCE = "once"


class AnnouncementSpec(BaseModel):
    """Isi pengumuman yang akan di-enqueue saat jadwal terpicu.

    Field-nya SENGAJA sama persis dengan ``SpeakRequest`` (Phase 2/7,
    ``schemas/queue.py``) — tapi didefinisikan ulang di sini (bukan impor
    langsung dari ``schemas/``) karena lapisan domain (``scheduler/``)
    TIDAK BOLEH bergantung pada lapisan API (Clean Architecture: arah
    dependensi selalu ke dalam). Validasi konsistensi ``type`` vs
    ``text``/``file`` tetap dilakukan — persis kontrak yang sama dengan
    ``SpeakRequest`` — lewat ``SchedulerManager`` saat jadwal dibuat.
    """

    model_config = ConfigDict(validate_assignment=True)

    type: AnnouncementType = AnnouncementType.TTS
    text: str | None = None
    file: str | None = None
    priority: QueuePriority = QueuePriority.NORMAL
    voice: str | None = None
    speed: float = 1.0
    pitch: float = 1.0
    volume: float = 1.0


class ScheduleEntry(BaseModel):
    """Representasi satu jadwal pemicu pengumuman otomatis."""

    model_config = ConfigDict(validate_assignment=True)

    id: uuid.UUID
    name: str = Field(description="Label jadwal, mis. 'Bell Masuk'")
    enabled: bool = Field(description="Jika false, jadwal tidak akan pernah terpicu")
    zone: str = Field(description="Nama zone tujuan pengumuman (lihat ZoneManager, Phase 6)")
    recurrence: ScheduleRecurrence
    time_of_day: time = Field(description="Jam pemicu (detik/mikrodetik diabaikan)")
    days_of_week: list[int] | None = Field(
        default=None, description="Hanya untuk recurrence=WEEKLY: 0=Senin..6=Minggu (date.weekday())"
    )
    run_date: date | None = Field(default=None, description="Hanya untuk recurrence=ONCE")
    announcement: AnnouncementSpec
    last_triggered_at: datetime | None = Field(default=None, description="Waktu terakhir jadwal ini benar-benar terpicu")
    next_run_at: datetime | None = Field(
        default=None, description="Waktu pemicu berikutnya. null jika jadwal ONCE sudah pernah terpicu (tidak akan terpicu lagi)."
    )
    created_at: datetime
    updated_at: datetime


def parse_time_of_day(value: str) -> time:
    """Parse string 'HH:MM' atau 'HH:MM:SS' (ISO 8601 partial) menjadi ``datetime.time``.

    Dipakai saat memuat jadwal statis dari ``config.yaml`` (bagian
    ``schedules:``) — lihat ``main.py``. Fungsi murni stdlib, tidak ada
    dependensi tambahan.
    """
    return time.fromisoformat(value)


def parse_run_date(value: str) -> date:
    """Parse string 'YYYY-MM-DD' (ISO 8601) menjadi ``datetime.date``.

    Dipakai saat memuat jadwal statis dari ``config.yaml`` (bagian
    ``schedules:``) — lihat ``main.py``.
    """
    return date.fromisoformat(value)


def compute_next_run(
    *,
    recurrence: ScheduleRecurrence,
    time_of_day: time,
    days_of_week: list[int] | None,
    run_date: date | None,
    after: datetime,
) -> datetime | None:
    """Menghitung waktu pemicu berikutnya SETELAH ``after`` (strict, tidak termasuk ``after`` itu sendiri).

    Fungsi MURNI — tidak mengakses jam sistem sama sekali, sehingga hasilnya
    sepenuhnya deterministik terhadap input. ``after`` HARUS berbagi
    tzinfo yang sama dengan hasil yang diharapkan (naive vs aware tidak
    boleh tercampur) — ``SchedulerManager`` selalu memanggil ini dengan
    ``after`` yang konsisten dengan ``scheduler.timezone``.

    Mengembalikan ``None`` jika:
    - ``recurrence=ONCE`` dan ``run_date``+``time_of_day`` sudah berlalu (<= ``after``).
    - ``recurrence=WEEKLY`` dan ``days_of_week`` kosong/``None`` (jadwal tidak valid).
    """
    if recurrence == ScheduleRecurrence.ONCE:
        if run_date is None:
            return None
        candidate = datetime.combine(run_date, time_of_day, tzinfo=after.tzinfo)
        return candidate if candidate > after else None

    if recurrence == ScheduleRecurrence.DAILY:
        candidate = datetime.combine(after.date(), time_of_day, tzinfo=after.tzinfo)
        if candidate <= after:
            candidate += timedelta(days=1)
        return candidate

    # WEEKLY
    if not days_of_week:
        return None
    valid_days = set(days_of_week)
    for offset in range(8):  # 8 hari cukup untuk memastikan satu putaran penuh + wraparound
        candidate_date = after.date() + timedelta(days=offset)
        if candidate_date.weekday() not in valid_days:
            continue
        candidate = datetime.combine(candidate_date, time_of_day, tzinfo=after.tzinfo)
        if candidate > after:
            return candidate
    return None
