"""Unit test untuk retry_with_backoff (Phase 14 — Production Hardening)."""

from __future__ import annotations

import pytest

from announcement_server.core.retry import retry_with_backoff


class _RetryableError(Exception):
    pass


class _OtherError(Exception):
    pass


async def test_succeeds_on_first_try_without_retry() -> None:
    calls = 0

    async def func() -> str:
        nonlocal calls
        calls += 1
        return "ok"

    result = await retry_with_backoff(func, max_retries=3, backoff_seconds=0, retry_on=(_RetryableError,))
    assert result == "ok"
    assert calls == 1


async def test_retries_until_success() -> None:
    calls = 0

    async def func() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise _RetryableError("gagal sementara")
        return "berhasil"

    result = await retry_with_backoff(func, max_retries=5, backoff_seconds=0, retry_on=(_RetryableError,))
    assert result == "berhasil"
    assert calls == 3


async def test_raises_after_exhausting_retries() -> None:
    calls = 0

    async def func() -> str:
        nonlocal calls
        calls += 1
        raise _RetryableError("selalu gagal")

    with pytest.raises(_RetryableError):
        await retry_with_backoff(func, max_retries=2, backoff_seconds=0, retry_on=(_RetryableError,))
    assert calls == 3  # 1 percobaan awal + 2 retry


async def test_does_not_retry_unlisted_exception() -> None:
    calls = 0

    async def func() -> str:
        nonlocal calls
        calls += 1
        raise _OtherError("kegagalan permanen")

    with pytest.raises(_OtherError):
        await retry_with_backoff(func, max_retries=5, backoff_seconds=0, retry_on=(_RetryableError,))
    assert calls == 1  # tidak di-retry sama sekali


async def test_max_retries_zero_means_no_retry() -> None:
    calls = 0

    async def func() -> str:
        nonlocal calls
        calls += 1
        raise _RetryableError("gagal")

    with pytest.raises(_RetryableError):
        await retry_with_backoff(func, max_retries=0, backoff_seconds=0, retry_on=(_RetryableError,))
    assert calls == 1
