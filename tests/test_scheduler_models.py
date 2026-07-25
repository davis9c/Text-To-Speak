"""Unit test untuk fungsi murni Scheduler (Phase 8): ``compute_next_run``, ``parse_time_of_day``, ``parse_run_date``."""

from __future__ import annotations

from datetime import date, datetime, time

from announcement_server.scheduler.models import ScheduleRecurrence, compute_next_run, parse_run_date, parse_time_of_day

# Senin 2026-07-20 pukul 10:00 dipakai sebagai titik acuan "sekarang" di seluruh test —
# date.weekday(): Senin=0, Selasa=1, ..., Minggu=6.
_MONDAY_10AM = datetime(2026, 7, 20, 10, 0, 0)


def test_compute_next_run_daily_returns_today_if_not_yet_passed() -> None:
    result = compute_next_run(
        recurrence=ScheduleRecurrence.DAILY, time_of_day=time(15, 0), days_of_week=None, run_date=None, after=_MONDAY_10AM
    )
    assert result == datetime(2026, 7, 20, 15, 0, 0)


def test_compute_next_run_daily_returns_tomorrow_if_already_passed() -> None:
    result = compute_next_run(
        recurrence=ScheduleRecurrence.DAILY, time_of_day=time(7, 0), days_of_week=None, run_date=None, after=_MONDAY_10AM
    )
    assert result == datetime(2026, 7, 21, 7, 0, 0)


def test_compute_next_run_daily_exact_boundary_is_not_due_yet() -> None:
    """`after` == waktu jadwal HARUS dianggap 'baru saja lewat' (strict >), bukan 'masih akan datang' —
    mencegah item yang sama terpicu dua kali pada poll cycle yang sama."""
    now = datetime(2026, 7, 20, 7, 0, 0)
    result = compute_next_run(
        recurrence=ScheduleRecurrence.DAILY, time_of_day=time(7, 0), days_of_week=None, run_date=None, after=now
    )
    assert result == datetime(2026, 7, 21, 7, 0, 0)


def test_compute_next_run_daily_never_returns_none() -> None:
    for hour in range(24):
        result = compute_next_run(
            recurrence=ScheduleRecurrence.DAILY, time_of_day=time(hour, 0), days_of_week=None, run_date=None, after=_MONDAY_10AM
        )
        assert result is not None


def test_compute_next_run_weekly_finds_next_matching_day_same_week() -> None:
    # Senin 10:00, jadwal Rabu(2)/Jumat(4) pukul 12:00 -> Rabu ini.
    result = compute_next_run(
        recurrence=ScheduleRecurrence.WEEKLY,
        time_of_day=time(12, 0),
        days_of_week=[2, 4],
        run_date=None,
        after=_MONDAY_10AM,
    )
    assert result == datetime(2026, 7, 22, 12, 0, 0)  # Rabu


def test_compute_next_run_weekly_same_day_but_time_already_passed_skips_to_next_week() -> None:
    # Senin 10:00, jadwal Senin(0) pukul 08:00 (sudah lewat hari ini) -> Senin depan.
    result = compute_next_run(
        recurrence=ScheduleRecurrence.WEEKLY,
        time_of_day=time(8, 0),
        days_of_week=[0],
        run_date=None,
        after=_MONDAY_10AM,
    )
    assert result == datetime(2026, 7, 27, 8, 0, 0)


def test_compute_next_run_weekly_same_day_time_not_passed_yet() -> None:
    # Senin 10:00, jadwal Senin(0) pukul 14:00 (belum lewat) -> hari ini.
    result = compute_next_run(
        recurrence=ScheduleRecurrence.WEEKLY,
        time_of_day=time(14, 0),
        days_of_week=[0],
        run_date=None,
        after=_MONDAY_10AM,
    )
    assert result == datetime(2026, 7, 20, 14, 0, 0)


def test_compute_next_run_weekly_empty_days_returns_none() -> None:
    result = compute_next_run(
        recurrence=ScheduleRecurrence.WEEKLY, time_of_day=time(12, 0), days_of_week=[], run_date=None, after=_MONDAY_10AM
    )
    assert result is None


def test_compute_next_run_weekly_none_days_returns_none() -> None:
    result = compute_next_run(
        recurrence=ScheduleRecurrence.WEEKLY, time_of_day=time(12, 0), days_of_week=None, run_date=None, after=_MONDAY_10AM
    )
    assert result is None


def test_compute_next_run_once_future_returns_datetime() -> None:
    result = compute_next_run(
        recurrence=ScheduleRecurrence.ONCE,
        time_of_day=time(9, 0),
        days_of_week=None,
        run_date=date(2026, 12, 25),
        after=_MONDAY_10AM,
    )
    assert result == datetime(2026, 12, 25, 9, 0, 0)


def test_compute_next_run_once_past_returns_none() -> None:
    result = compute_next_run(
        recurrence=ScheduleRecurrence.ONCE,
        time_of_day=time(9, 0),
        days_of_week=None,
        run_date=date(2020, 1, 1),
        after=_MONDAY_10AM,
    )
    assert result is None


def test_compute_next_run_once_missing_run_date_returns_none() -> None:
    result = compute_next_run(
        recurrence=ScheduleRecurrence.ONCE, time_of_day=time(9, 0), days_of_week=None, run_date=None, after=_MONDAY_10AM
    )
    assert result is None


def test_parse_time_of_day_without_seconds() -> None:
    assert parse_time_of_day("07:00") == time(7, 0)


def test_parse_time_of_day_with_seconds() -> None:
    assert parse_time_of_day("07:00:30") == time(7, 0, 30)


def test_parse_run_date() -> None:
    assert parse_run_date("2026-12-25") == date(2026, 12, 25)
