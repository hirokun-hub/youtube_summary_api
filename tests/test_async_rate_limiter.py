"""非同期スライディングウィンドウ・レート制限テスト (AR-1〜AR-5)。

`/search` 用のクライアントレート制限（直近 60 秒で 10 回まで）が
`asyncio.Lock` + `collections.deque` で正しく実装されていることを検証する。

設計参照: design.md §3.3 / §9.4、tasks.md タスク 4.1。
"""

import asyncio

import pytest

from app.core import async_rate_limiter
from app.core.constants import (
    ERROR_CLIENT_RATE_LIMITED,
    SEARCH_RATE_LIMIT_MAX_REQUESTS,
    SEARCH_RATE_LIMIT_WINDOW_SECONDS,
)


@pytest.fixture(autouse=True)
def _reset_async_rate_limiter():
    """各テストの前後でモジュール状態（deque / lock）をリセットする。"""
    async_rate_limiter.reset()
    yield
    async_rate_limiter.reset()


def _run(coro):
    """asyncio.run のラッパ。pytest-asyncio に依存せず async ロジックを駆動する。"""
    return asyncio.run(coro)


def test_ar1_ten_calls_within_window_allowed():
    """AR-1: 直近 60 秒で 10 回までは check_request() が (True, None) を返す。"""

    async def scenario():
        results = []
        # t=0.0, 0.1, ..., 0.9 で 10 回連続呼び出し（全て窓内）
        for i in range(SEARCH_RATE_LIMIT_MAX_REQUESTS):
            allowed, blocked = await async_rate_limiter.check_request(now=i * 0.1)
            results.append((allowed, blocked))
        return results

    results = _run(scenario())
    assert len(results) == SEARCH_RATE_LIMIT_MAX_REQUESTS
    assert all(r == (True, None) for r in results), (
        f"10 回目までは全て (True, None) のはず: {results}"
    )


def test_ar2_eleventh_call_blocked_with_retry_after_matches_window_head():
    """AR-2: 11 回目で (False, blocked_payload) を返し、retry_after は
    ウィンドウ先頭リクエストが 60 秒経過するまでの秒数と一致する。"""

    async def scenario():
        for _ in range(SEARCH_RATE_LIMIT_MAX_REQUESTS):
            await async_rate_limiter.check_request(now=0.0)
        # ウィンドウ先頭(t=0) から 10 秒経過 → 残り 50 秒
        return await async_rate_limiter.check_request(now=10.0)

    allowed, blocked = _run(scenario())
    assert allowed is False
    assert isinstance(blocked, dict)
    assert blocked["error_code"] == ERROR_CLIENT_RATE_LIMITED
    assert blocked["retry_after"] == SEARCH_RATE_LIMIT_WINDOW_SECONDS - 10  # = 50
    # メッセージ本文にルール（最大回数）と retry_after 秒数が含まれる（AI 学習容易性）
    assert str(SEARCH_RATE_LIMIT_MAX_REQUESTS) in blocked["message"]
    assert str(blocked["retry_after"]) in blocked["message"]


def test_ar3_window_slides_after_60_seconds():
    """AR-3: 60 秒経過後、ウィンドウから古い記録が排除され再度許可される。"""

    async def scenario():
        # t=0.0..0.9 で 10 回満杯
        for i in range(SEARCH_RATE_LIMIT_MAX_REQUESTS):
            await async_rate_limiter.check_request(now=i * 0.1)
        # t=60.5 では先頭の t=0..0.5 が窓外で popleft され、空きが出る
        return await async_rate_limiter.check_request(now=60.5)

    allowed, blocked = _run(scenario())
    assert allowed is True
    assert blocked is None


def test_ar4_concurrent_safety_no_race_condition():
    """AR-4: asyncio.gather で 20 並列でも asyncio.Lock により race が起きない。
    許可 10 件・拒否 10 件で確定する。"""

    async def scenario():
        # 全タスクで同一の now=0.0 を使い、ウィンドウ先頭時刻も 0.0 に揃える
        tasks = [async_rate_limiter.check_request(now=0.0) for _ in range(20)]
        return await asyncio.gather(*tasks)

    results = _run(scenario())
    allowed_count = sum(1 for allowed, _ in results if allowed is True)
    blocked_count = sum(1 for allowed, _ in results if allowed is False)
    assert allowed_count == SEARCH_RATE_LIMIT_MAX_REQUESTS, (
        f"許可された数は {SEARCH_RATE_LIMIT_MAX_REQUESTS} 件のはず: {allowed_count}"
    )
    assert blocked_count == 20 - SEARCH_RATE_LIMIT_MAX_REQUESTS


def test_ar5_retry_after_min_one_second():
    """AR-5: retry_after は端数切り上げで最低 1 秒。"""

    async def scenario():
        # ウィンドウ先頭 t=0 を 10 件で満杯にし、11 回目を t=59.9 で叩く
        for _ in range(SEARCH_RATE_LIMIT_MAX_REQUESTS):
            await async_rate_limiter.check_request(now=0.0)
        return await async_rate_limiter.check_request(now=59.9)

    allowed, blocked = _run(scenario())
    assert allowed is False
    # 残り 60 - 59.9 = 0.1 秒 → 切り上げ最低 1 秒
    assert blocked["retry_after"] == 1
