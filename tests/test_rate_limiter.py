"""app/core/rate_limiter.py のユニットテスト。

時刻は monkeypatch で app.core.rate_limiter.time.monotonic を差し替えて制御する。
各テスト前に rate_limiter.reset() を呼ぶ autouse フィクスチャを使用。
"""

import pytest

from app.core import rate_limiter
from app.core.constants import (
    CLIENT_RATE_LIMIT_INTERVAL_SECONDS,
    ERROR_CLIENT_RATE_LIMITED,
)


@pytest.fixture(autouse=True)
def _reset_rate_limiter_state():
    """各テスト前にレートリミッタの内部状態をリセットする。"""
    rate_limiter.reset()
    yield
    rate_limiter.reset()


@pytest.fixture
def mock_time(monkeypatch):
    """time.monotonic() を制御可能にするフィクスチャ。

    返り値の関数 set_time(t) で現在時刻を設定できる。
    """
    state = {"now": 1000.0}

    def fake_monotonic():
        return state["now"]

    monkeypatch.setattr("app.core.rate_limiter.time.monotonic", fake_monotonic)

    def set_time(t: float):
        state["now"] = t

    return set_time


def test_rl01_first_request_allowed(mock_time):
    """初回呼び出しは常に許可される。"""
    mock_time(1000.0)
    allowed, retry_after = rate_limiter.check_and_update(60)
    assert allowed is True
    assert retry_after == 0


def test_rl02_within_interval_blocked(mock_time):
    """初回から30秒後の呼び出しは拒否され、残り秒数が返る。"""
    mock_time(1000.0)
    rate_limiter.check_and_update(60)

    mock_time(1030.0)
    allowed, retry_after = rate_limiter.check_and_update(60)
    assert allowed is False
    assert retry_after == 30


def test_rl03_exact_interval_allowed(mock_time):
    """ちょうど60秒経過時点で許可される。"""
    mock_time(1000.0)
    rate_limiter.check_and_update(60)

    mock_time(1060.0)
    allowed, retry_after = rate_limiter.check_and_update(60)
    assert allowed is True
    assert retry_after == 0


def test_rl04_after_interval_allowed(mock_time):
    """61秒経過時点で許可される。"""
    mock_time(1000.0)
    rate_limiter.check_and_update(60)

    mock_time(1061.0)
    allowed, retry_after = rate_limiter.check_and_update(60)
    assert allowed is True
    assert retry_after == 0


def test_rl05_blocked_does_not_extend_window(mock_time):
    """拒否されたリクエストは内部時刻を更新しない。

    30秒時点で拒否 → 40秒時点で残り20秒(60秒時点でロック解除予定)になることを確認。
    もし拒否時に時刻を更新していたら40秒時点では残り60秒になってしまう。
    """
    mock_time(1000.0)
    rate_limiter.check_and_update(60)

    mock_time(1030.0)
    allowed1, retry1 = rate_limiter.check_and_update(60)
    assert allowed1 is False
    assert retry1 == 30

    mock_time(1040.0)
    allowed2, retry2 = rate_limiter.check_and_update(60)
    assert allowed2 is False
    assert retry2 == 20


def test_rl06_reset_clears_state(mock_time):
    """reset() を呼ぶと内部状態がクリアされ、次回が初回として扱われる。"""
    mock_time(1000.0)
    rate_limiter.check_and_update(60)

    rate_limiter.reset()

    mock_time(1010.0)  # 通常なら拒否される時刻だが
    allowed, retry_after = rate_limiter.check_and_update(60)
    assert allowed is True
    assert retry_after == 0


def test_rl07_fractional_seconds_round_up(mock_time):
    """残り秒数の計算は切り上げ(0.x秒残っていても1秒として返す)。"""
    mock_time(1000.0)
    rate_limiter.check_and_update(60)

    mock_time(1059.5)  # 残り0.5秒
    allowed, retry_after = rate_limiter.check_and_update(60)
    assert allowed is False
    assert retry_after == 1


# --- 高レベルファサード check_request() のテスト ---


def test_rl08_check_request_first_allowed(mock_time):
    """check_request() の初回呼び出しは (True, None) を返す。"""
    mock_time(1000.0)
    allowed, blocked = rate_limiter.check_request()
    assert allowed is True
    assert blocked is None


def test_rl09_check_request_blocked_returns_response_fields(mock_time):
    """check_request() の拒否時は SummaryResponse 用のフィールド辞書を返す。"""
    mock_time(1000.0)
    rate_limiter.check_request()  # 1回目: 許可

    mock_time(1010.0)  # 10秒後: 拒否される
    allowed, blocked = rate_limiter.check_request()
    assert allowed is False
    assert blocked is not None
    assert blocked["error_code"] == ERROR_CLIENT_RATE_LIMITED
    assert blocked["retry_after"] == CLIENT_RATE_LIMIT_INTERVAL_SECONDS - 10
    # メッセージにretry_afterが埋め込まれていることを確認
    assert str(blocked["retry_after"]) in blocked["message"]
    # テンプレート文字列の {retry_after} が残っていないこと
    assert "{retry_after}" not in blocked["message"]


def test_rl10_check_request_uses_default_interval(mock_time):
    """check_request() は CLIENT_RATE_LIMIT_INTERVAL_SECONDS をデフォルトインターバルとして使う。"""
    mock_time(1000.0)
    rate_limiter.check_request()

    # デフォルトインターバル経過後は許可される
    mock_time(1000.0 + CLIENT_RATE_LIMIT_INTERVAL_SECONDS)
    allowed, blocked = rate_limiter.check_request()
    assert allowed is True
    assert blocked is None
