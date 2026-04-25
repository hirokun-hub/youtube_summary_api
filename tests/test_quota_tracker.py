"""quota_tracker（クォータ追跡 + SQLite 永続化 + ContextVar 隔離）テスト SQ-1〜SQ-9。

設計参照: design.md §3.2 / §5、tasks.md タスク 6.1。
"""

import asyncio
import sqlite3
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.core import quota_tracker
from app.core.constants import (
    SQLITE_BUSY_TIMEOUT_MS,
    YOUTUBE_DAILY_QUOTA_LIMIT,
    YOUTUBE_QUOTA_TIMEZONE,
)

PT = ZoneInfo(YOUTUBE_QUOTA_TIMEZONE)


def _today_pt_midnight_utc(now_utc: datetime) -> datetime:
    """同等ヘルパ（テスト計算用）。"""
    now_pt = now_utc.astimezone(PT)
    return datetime.combine(
        now_pt.date(), time.min, tzinfo=PT
    ).astimezone(timezone.utc)


def _next_pt_midnight_utc(now_utc: datetime) -> datetime:
    now_pt = now_utc.astimezone(PT)
    return datetime.combine(
        now_pt.date() + timedelta(days=1), time.min, tzinfo=PT
    ).astimezone(timezone.utc)


@pytest.fixture
def initialized_tracker(tmp_path):
    """各テスト用に空の DB を init し、終了後にプロセス内状態をリセットする。"""
    db_path = tmp_path / "usage.db"
    quota_tracker.init(db_path)
    yield db_path
    quota_tracker.reset()


@pytest.fixture(autouse=True)
def _ensure_clean_state():
    """テスト間でプロセス内グローバル状態が漏れないように teardown で reset。"""
    yield
    quota_tracker.reset()


# =============================================
# SQ-1: init で 2 テーブル + 4 種 PRAGMA が適用される
# =============================================

def test_sq1_init_creates_tables_and_applies_pragmas(initialized_tracker):
    """init 後、api_calls / quota_state テーブルが作成され、PRAGMA が反映されている。"""
    db_path = initialized_tracker
    # quota_tracker._connect 経由（PRAGMA も反映された接続）で確認
    conn = quota_tracker._connect()
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        names = {r[0] for r in rows}
        assert "api_calls" in names, f"api_calls テーブルが無い: {names}"
        assert "quota_state" in names, f"quota_state テーブルが無い: {names}"

        # PRAGMA 確認（接続単位の設定）
        journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        assert str(journal_mode).lower() == "wal", f"journal_mode={journal_mode}"

        synchronous = conn.execute("PRAGMA synchronous;").fetchone()[0]
        # NORMAL = 1
        assert int(synchronous) == 1, f"synchronous={synchronous}"

        busy_timeout = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
        assert int(busy_timeout) == SQLITE_BUSY_TIMEOUT_MS, (
            f"busy_timeout={busy_timeout}"
        )

        foreign_keys = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
        assert int(foreign_keys) == 1, f"foreign_keys={foreign_keys}"
    finally:
        conn.close()


# =============================================
# SQ-2: add_units(100) で in-memory + quota_state が同時更新、api_calls には書かない
# =============================================

def test_sq2_add_units_updates_memory_and_quota_state_only(initialized_tracker):
    """add_units(100) で consumed_units_today が +100、quota_state も同期。
    api_calls には INSERT しない（責務分離）。"""
    db_path = initialized_tracker

    snap_before = quota_tracker.get_snapshot()
    assert snap_before.consumed_units_today == 0

    quota_tracker.add_units(100)

    snap_after = quota_tracker.get_snapshot()
    assert snap_after.consumed_units_today == 100

    raw = sqlite3.connect(str(db_path))
    try:
        qs = raw.execute(
            "SELECT consumed_units_today FROM quota_state WHERE id = 1"
        ).fetchone()
        assert qs is not None and qs[0] == 100, f"quota_state row={qs}"

        api_count = raw.execute("SELECT COUNT(*) FROM api_calls").fetchone()[0]
        assert api_count == 0, "add_units は api_calls を触ってはいけない"
    finally:
        raw.close()


# =============================================
# SQ-3: record_api_call で api_calls に 1 行 INSERT、quota_state は無変更
# =============================================

def test_sq3_record_api_call_inserts_row_and_does_not_touch_quota_state(
    initialized_tracker,
):
    """record_api_call は api_calls にだけ INSERT し、quota_state の数値は変えない。
    endpoint='search' / 'summary' の両方で同一関数が使える。"""
    db_path = initialized_tracker

    quota_tracker.record_api_call(
        endpoint="search",
        input_summary="ホリエモン AI 最新",
        units_cost=102,
        http_status=200,
        http_success=True,
        error_code=None,
        transcript_success=None,
        transcript_language=None,
        result_count=50,
    )
    quota_tracker.record_api_call(
        endpoint="summary",
        input_summary="dQw4w9WgXcQ",
        units_cost=2,
        http_status=200,
        http_success=True,
        error_code=None,
        transcript_success=True,
        transcript_language="ja",
        result_count=None,
    )

    raw = sqlite3.connect(str(db_path))
    try:
        rows = raw.execute(
            "SELECT endpoint, input_summary, units_cost, http_status, http_success, "
            "error_code, transcript_success, transcript_language, result_count "
            "FROM api_calls ORDER BY id"
        ).fetchall()
        assert len(rows) == 2
        # search 行
        assert rows[0][0] == "search"
        assert rows[0][1] == "ホリエモン AI 最新"
        assert rows[0][2] == 102
        assert rows[0][3] == 200
        assert int(rows[0][4]) == 1  # http_success True → 1
        assert rows[0][5] is None
        assert rows[0][6] is None  # transcript_success
        assert rows[0][7] is None  # transcript_language
        assert rows[0][8] == 50  # result_count
        # summary 行
        assert rows[1][0] == "summary"
        assert rows[1][1] == "dQw4w9WgXcQ"
        assert rows[1][2] == 2
        assert int(rows[1][6]) == 1  # transcript_success True → 1
        assert rows[1][7] == "ja"
        assert rows[1][8] is None  # /summary は result_count なし

        # quota_state は record_api_call の影響を受けない（add_units 経由でしか変化しない）
        qs = raw.execute(
            "SELECT consumed_units_today FROM quota_state WHERE id = 1"
        ).fetchone()
        assert qs[0] == 0
    finally:
        raw.close()


# =============================================
# SQ-4: get_snapshot の reset_at_utc / reset_at_jst / reset_in_seconds が正しい
# =============================================

def test_sq4_get_snapshot_pt_midnight_calculations_correct(initialized_tracker):
    """PT 0:00 基準で reset_at_utc / reset_at_jst / reset_in_seconds が正確に算出される。"""
    # 2026-04-25 12:00:00 UTC（PDT: UTC-7）→ PT は 2026-04-25 05:00 PDT
    now_utc = datetime(2026, 4, 25, 12, 0, 0, tzinfo=timezone.utc)
    expected_reset_utc = datetime(2026, 4, 26, 7, 0, 0, tzinfo=timezone.utc)

    snap = quota_tracker.get_snapshot(now_utc=now_utc)

    assert snap.reset_at_utc == expected_reset_utc
    assert snap.reset_at_jst.utcoffset() == timedelta(hours=9)
    # JST は UTC+9 → 2026-04-26 16:00:00+09:00
    assert snap.reset_at_jst.replace(tzinfo=None) == datetime(2026, 4, 26, 16, 0, 0)
    # 19 時間 = 68400 秒
    assert snap.reset_in_seconds == 19 * 3600

    assert snap.consumed_units_today == 0
    assert snap.daily_limit == YOUTUBE_DAILY_QUOTA_LIMIT
    assert snap.remaining_units_estimate == YOUTUBE_DAILY_QUOTA_LIMIT


# =============================================
# SQ-5: PT 0:00 を跨ぐと内部カウンタが 0 にリセットされる
# =============================================

def test_sq5_pt_midnight_crossing_resets_counter(initialized_tracker):
    """PT 0:00 を跨ぐ get_snapshot 呼び出しで in-memory consumed_units_today が 0 になる。"""
    db_path = initialized_tracker
    # 2026-04-26 06:30 UTC = PT 4-25 23:30（PT 0:00 直前）
    before = datetime(2026, 4, 26, 6, 30, 0, tzinfo=timezone.utc)
    # 2026-04-26 07:30 UTC = PT 4-26 00:30（PT 0:00 通過後）
    after = datetime(2026, 4, 26, 7, 30, 0, tzinfo=timezone.utc)

    quota_tracker.add_units(500, now_utc=before)
    snap_before = quota_tracker.get_snapshot(now_utc=before)
    assert snap_before.consumed_units_today == 500

    snap_after = quota_tracker.get_snapshot(now_utc=after)
    assert snap_after.consumed_units_today == 0, (
        f"PT 0:00 跨ぎでリセットされていない: {snap_after.consumed_units_today}"
    )

    # SQLite の quota_state も同期更新されている
    raw = sqlite3.connect(str(db_path))
    try:
        qs = raw.execute(
            "SELECT consumed_units_today FROM quota_state WHERE id = 1"
        ).fetchone()
        assert qs[0] == 0
    finally:
        raw.close()


# =============================================
# SQ-6: 起動時 SUM 復元 — 事前に api_calls へ手動 INSERT した行から再計算
# =============================================

def test_sq6_init_restores_consumed_from_api_calls_sum(tmp_path):
    """再起動相当: api_calls に既存行があれば init 時に consumed_units_today を SUM 復元する。"""
    db_path = tmp_path / "usage.db"

    # 固定 now（2026-04-25 12:00 UTC、PT 4-25）
    now_utc = datetime(2026, 4, 25, 12, 0, 0, tzinfo=timezone.utc)
    today_pt_midnight = _today_pt_midnight_utc(now_utc)
    after_midnight = today_pt_midnight + timedelta(hours=1)
    yesterday = today_pt_midnight - timedelta(hours=2)

    # 1) 一度 init → スキーマ作成
    quota_tracker.init(db_path, now_utc=now_utc)
    quota_tracker.reset()  # in-memory のみクリア（DB は残る）

    # 2) 直接 SQL で api_calls にデータを投入（PT 今日 +1h, +1h 内 / 昨日分は除外確認）
    raw = sqlite3.connect(str(db_path))
    try:
        # 今日（PT）の行 = 100 + 50 = 150 が復元対象
        raw.execute(
            "INSERT INTO api_calls (called_at_utc, endpoint, input_summary, units_cost, "
            "cumulative_units_today, http_status, http_success, error_code, "
            "transcript_success, transcript_language, result_count) "
            "VALUES (?, 'search', 'q1', 100, 100, 200, 1, NULL, NULL, NULL, 50)",
            (after_midnight.isoformat(),),
        )
        raw.execute(
            "INSERT INTO api_calls (called_at_utc, endpoint, input_summary, units_cost, "
            "cumulative_units_today, http_status, http_success, error_code, "
            "transcript_success, transcript_language, result_count) "
            "VALUES (?, 'summary', 'vid', 50, 150, 200, 1, NULL, 1, 'ja', NULL)",
            (after_midnight.isoformat(),),
        )
        # 昨日の行は SUM に含めない
        raw.execute(
            "INSERT INTO api_calls (called_at_utc, endpoint, input_summary, units_cost, "
            "cumulative_units_today, http_status, http_success, error_code, "
            "transcript_success, transcript_language, result_count) "
            "VALUES (?, 'search', 'q0', 999, 999, 200, 1, NULL, NULL, NULL, 0)",
            (yesterday.isoformat(),),
        )
        raw.commit()
    finally:
        raw.close()

    # 3) 再 init → SUM 復元
    quota_tracker.init(db_path, now_utc=now_utc)
    snap = quota_tracker.get_snapshot(now_utc=now_utc)
    assert snap.consumed_units_today == 150, (
        f"今日 PT 内の SUM=150 を復元すべき: {snap.consumed_units_today}"
    )


# =============================================
# SQ-7: 内部カウンタが daily_limit (10000) 到達 → is_exhausted() True
# =============================================

def test_sq7_is_exhausted_at_daily_limit(initialized_tracker):
    """consumed_units_today >= 10000 で is_exhausted=True。"""
    assert quota_tracker.is_exhausted() is False
    quota_tracker.add_units(YOUTUBE_DAILY_QUOTA_LIMIT)
    assert quota_tracker.is_exhausted() is True


def test_sq7_mark_exhausted_forces_true_until_pt_midnight(initialized_tracker):
    """mark_exhausted(reason) 後は consumed が limit 未満でも is_exhausted=True。
    次の PT 0:00 後は False に戻る。"""
    now = datetime(2026, 4, 25, 12, 0, 0, tzinfo=timezone.utc)
    after_midnight = _next_pt_midnight_utc(now) + timedelta(minutes=1)

    quota_tracker.mark_exhausted(reason="youtube_403", now_utc=now)
    assert quota_tracker.is_exhausted(now_utc=now) is True

    # 翌 PT 0:00 後（rollover される）
    assert quota_tracker.is_exhausted(now_utc=after_midnight) is False


# =============================================
# SQ-8: 書き込みで BEGIN IMMEDIATE が使われている（暗黙の BEGIN ではない）
# =============================================

def test_sq8_begin_immediate_used_on_write(initialized_tracker, monkeypatch):
    """add_units の SQL トレースに BEGIN IMMEDIATE が含まれること。
    暗黙の BEGIN（後発で SQLITE_BUSY を食う）を使わない契約の固定。"""
    statements: list[str] = []

    original_connect = sqlite3.connect

    def tracking_connect(*args, **kwargs):
        conn = original_connect(*args, **kwargs)
        conn.set_trace_callback(lambda sql: statements.append(sql))
        return conn

    monkeypatch.setattr("sqlite3.connect", tracking_connect)

    quota_tracker.add_units(50)

    assert any("BEGIN IMMEDIATE" in s.upper() for s in statements), (
        f"BEGIN IMMEDIATE が発行されていない: {statements!r}"
    )


# =============================================
# SQ-9: ContextVar 隔離 — 並行リクエストで get_request_cost が混入しない
# =============================================

def test_sq9_request_cost_contextvar_isolation(initialized_tracker):
    """asyncio.gather で 2 並行タスクが add_units(100) と add_units(50) を呼んでも、
    各タスクの get_request_cost は自分の値（100 / 50）のみを返す。"""

    async def worker(value: int) -> int:
        quota_tracker.reset_request_cost()
        # 別タスクへ割り込ませ ContextVar 混入有無を試す
        await asyncio.sleep(0)
        quota_tracker.add_units(value)
        await asyncio.sleep(0)
        return quota_tracker.get_request_cost()

    async def scenario():
        return await asyncio.gather(worker(100), worker(50))

    results = asyncio.run(scenario())
    # 各タスクは自タスクの value だけを見る（混入なし）
    assert sorted(results) == [50, 100], (
        f"ContextVar が並行タスク間で混入している: {results}"
    )

    # in-memory の総消費は両タスク分の合計（150）になる
    snap = quota_tracker.get_snapshot()
    assert snap.consumed_units_today == 150
