"""非同期スライディングウィンドウ・レート制限（/search 用）。

`/summary` 用 `app/core/rate_limiter.py`（threading.Lock）とは独立した実装。
async コンテキスト内で `threading.Lock` を保持しないために、本モジュールは
`asyncio.Lock` を使う（要件 TC-4 / 設計書 §3.3）。

公開 API:
- `check_request(now=None) -> tuple[bool, dict | None]`
  - 許可時: `(True, None)`
  - 拒否時: `(False, {"error_code", "message", "retry_after"})`
- `reset()`: 主にテスト用の状態リセット。
"""

import asyncio
import math
import time
from collections import deque

from app.core.constants import (
    ERROR_CLIENT_RATE_LIMITED,
    MSG_SEARCH_CLIENT_RATE_LIMITED_TEMPLATE,
    SEARCH_RATE_LIMIT_MAX_REQUESTS,
    SEARCH_RATE_LIMIT_WINDOW_SECONDS,
)

# モジュール状態。`asyncio.Lock` は最初の `await` 時に現在の event loop に
# 結びつくため、loop が切り替わった場合（例: `asyncio.run` を複数回呼ぶ
# テスト環境）でも安全に動作するよう lazy 初期化＋reset で再構築する。
_state: dict = {
    "deque": deque(),  # type: deque[float] : リクエスト到着時刻（time.monotonic 基準）
    "lock": None,      # type: asyncio.Lock | None : 初回 check_request で生成
}


def _get_lock() -> asyncio.Lock:
    """lazy に asyncio.Lock を生成して返す。reset() でクリア可能。"""
    if _state["lock"] is None:
        _state["lock"] = asyncio.Lock()
    return _state["lock"]


async def check_request(now: float | None = None) -> tuple[bool, dict | None]:
    """直近 60 秒で 10 回までのスライディングウィンドウ判定。

    Args:
        now: テスト用に外部から時刻を注入できる。None の場合は `time.monotonic()`。

    Returns:
        (allowed, blocked_payload) のタプル。
        - 許可: `(True, None)`
        - 拒否: `(False, {"error_code", "message", "retry_after"})`
    """
    if now is None:
        now = time.monotonic()

    lock = _get_lock()
    async with lock:
        dq: deque = _state["deque"]
        # ウィンドウ外（now - window 以前）の記録を popleft
        cutoff = now - SEARCH_RATE_LIMIT_WINDOW_SECONDS
        while dq and dq[0] <= cutoff:
            dq.popleft()

        if len(dq) >= SEARCH_RATE_LIMIT_MAX_REQUESTS:
            # ウィンドウ先頭が 60 秒経過するまでの秒数（端数切り上げ・最低 1）
            elapsed = now - dq[0]
            retry_after = max(
                1, math.ceil(SEARCH_RATE_LIMIT_WINDOW_SECONDS - elapsed)
            )
            message = MSG_SEARCH_CLIENT_RATE_LIMITED_TEMPLATE.format(
                window=SEARCH_RATE_LIMIT_WINDOW_SECONDS,
                max_req=SEARCH_RATE_LIMIT_MAX_REQUESTS,
                retry_after=retry_after,
            )
            return (
                False,
                {
                    "error_code": ERROR_CLIENT_RATE_LIMITED,
                    "message": message,
                    "retry_after": retry_after,
                },
            )

        dq.append(now)
        return (True, None)


def reset() -> None:
    """テスト用: deque と lock を初期化する。"""
    _state["deque"].clear()
    _state["lock"] = None
