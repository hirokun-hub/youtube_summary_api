"""プロセス内グローバルレートリミッタ。

最後に許可されたリクエストの時刻 (`time.monotonic()` 基準) を保持し、
指定インターバル未満の連続リクエストを拒否する。

- スコープ: グローバル単一バケット (個人API用、ユーザー区別なし)
- スレッド安全: threading.Lock で排他制御
- プロセス再起動でリセットされる (永続化なし)

公開API:
- `check_request()`: ルーター層向け高レベルファサード。拒否時のレスポンス断片も組み立てる。
- `check_and_update(interval)`: 低レベル純関数。テストで時刻と間隔を直接制御するために公開。
- `reset()`: 主にテスト用の状態リセット。
"""

import math
import time
import threading

from app.core.constants import (
    CLIENT_RATE_LIMIT_INTERVAL_SECONDS,
    ERROR_CLIENT_RATE_LIMITED,
    MSG_CLIENT_RATE_LIMITED,
)

# 最後に許可されたリクエストの時刻 (time.monotonic 基準)
# None は「まだ一度も許可されていない」状態を表す
_last_allowed_at: float | None = None
_lock = threading.Lock()


def check_and_update(interval_seconds: int) -> tuple[bool, int]:
    """レート制限をチェックし、許可される場合は内部時刻を更新する。

    Args:
        interval_seconds: リクエスト間の最低待機秒数

    Returns:
        (allowed, retry_after) のタプル。
        - 許可された場合: (True, 0)
        - 拒否された場合: (False, 残り秒数)  ※残り秒数は切り上げ、最低1
    """
    global _last_allowed_at
    with _lock:
        now = time.monotonic()
        if _last_allowed_at is None:
            _last_allowed_at = now
            return (True, 0)

        elapsed = now - _last_allowed_at
        if elapsed >= interval_seconds:
            _last_allowed_at = now
            return (True, 0)

        # 拒否: 内部時刻は更新しない (連続拒否で待機窓が伸びないように)
        # 残り秒数は切り上げ (例: 0.5秒残っていても1秒として返す)
        remaining = max(1, math.ceil(interval_seconds - elapsed))
        return (False, remaining)


def reset() -> None:
    """内部状態をリセットする (主にテスト用)。"""
    global _last_allowed_at
    with _lock:
        _last_allowed_at = None


def check_request() -> tuple[bool, dict | None]:
    """ルーター層向けの高レベルファサード。

    本番用の定数 (`CLIENT_RATE_LIMIT_INTERVAL_SECONDS` 等) を使ってチェックし、
    拒否時には SummaryResponse に流し込めるフィールド辞書を返す。

    Returns:
        (allowed, blocked_fields) のタプル。
        - 許可: (True, None)
        - 拒否: (False, {"error_code", "message", "retry_after"})

    使用例 (router):
        allowed, blocked = check_request()
        if not allowed:
            return SummaryResponse(success=False, **blocked)
    """
    allowed, retry_after = check_and_update(CLIENT_RATE_LIMIT_INTERVAL_SECONDS)
    if allowed:
        return (True, None)
    return (
        False,
        {
            "error_code": ERROR_CLIENT_RATE_LIMITED,
            "message": MSG_CLIENT_RATE_LIMITED.format(retry_after=retry_after),
            "retry_after": retry_after,
        },
    )
