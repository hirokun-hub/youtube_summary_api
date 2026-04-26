"""YouTube Data API v3 のクォータ消費を追跡する（プロセス内 + SQLite 永続化）。

責務:
  - in-memory の `consumed_units_today` を `threading.RLock` 保護で更新
  - SQLite `quota_state` (単一行) と `api_calls` テーブルへの永続化
  - 太平洋時間 (PT) 0:00 跨ぎでのカウンタ自動リセット
  - 並行リクエストで `last_call_cost` が混ざらないよう ContextVar で各リクエストの
    cost 累計をリクエストローカルに保持
  - YouTube 403 quotaExceeded 受信時の強制 exhausted 化（次の PT 0:00 まで）

公開 API:
  - `init(db_path, now_utc=None)` — テーブル作成 + PRAGMA + SUM 復元（startup で 1 回）
  - `add_units(cost, now_utc=None)` — units を計上（in-memory + quota_state + ContextVar）
  - `record_api_call(...)` — api_calls に 1 行 INSERT（リクエスト終端で 1 回）
  - `get_snapshot(now_utc=None) -> Quota` — 応答用クォータ状態を組み立てる
  - `is_exhausted(now_utc=None)` / `mark_exhausted(reason, now_utc=None)`
  - `reset_request_cost()` / `get_request_cost()` — ContextVar アクセサ
  - `reset()` — テスト用にプロセス内状態をクリア
"""

from __future__ import annotations

import sqlite3
import threading
from contextvars import ContextVar
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from app.core.constants import (
    SQLITE_BUSY_TIMEOUT_MS,
    YOUTUBE_DAILY_QUOTA_LIMIT,
    YOUTUBE_QUOTA_TIMEZONE,
)
from app.models.schemas import Quota

PT = ZoneInfo(YOUTUBE_QUOTA_TIMEZONE)
JST = timezone(timedelta(hours=9))

# プロセス内状態（threading.RLock 保護）。db_path は init で設定する。
_state: dict = {
    "consumed_units_today": 0,
    "quota_date_pt": None,        # type: Optional[str]  # "YYYY-MM-DD" (PT)
    "exhausted_until": None,      # type: Optional[datetime]  # 403 強制 exhausted の終端
    "db_path": None,              # type: Optional[Path]
}
_lock = threading.RLock()

# リクエストローカルな当該リクエスト分の cost 累計。
# FastAPI は各リクエストを独立した async タスクで処理し、ContextVar は Task ごとに
# Copy-on-Write で隔離されるため、並行リクエストの値が混ざらない。
_request_cost: ContextVar[int] = ContextVar("request_cost", default=0)


# ---------- 時刻ユーティリティ ----------

def _today_pt_str(now_utc: datetime) -> str:
    """now_utc を PT 換算した日付の ISO 文字列 (YYYY-MM-DD)。"""
    return now_utc.astimezone(PT).date().isoformat()


def _next_pt_midnight_utc(now_utc: datetime) -> datetime:
    """次の PT 0:00 を UTC で返す。zoneinfo が DST を自動処理する。"""
    now_pt = now_utc.astimezone(PT)
    next_day_pt = datetime.combine(
        now_pt.date() + timedelta(days=1), time.min, tzinfo=PT
    )
    return next_day_pt.astimezone(timezone.utc)


def _today_pt_midnight_utc(now_utc: datetime) -> datetime:
    """今日 (PT) の 0:00 を UTC で返す。SUM 復元クエリの境界に使う。"""
    now_pt = now_utc.astimezone(PT)
    today_midnight_pt = datetime.combine(now_pt.date(), time.min, tzinfo=PT)
    return today_midnight_pt.astimezone(timezone.utc)


# ---------- SQLite ヘルパ ----------

def _connect() -> sqlite3.Connection:
    """PRAGMA を適用した sqlite3.Connection を返す。"""
    if _state["db_path"] is None:
        raise RuntimeError("quota_tracker.init(db_path) を先に呼んでください")
    conn = sqlite3.connect(
        str(_state["db_path"]), timeout=5.0, isolation_level=None
    )
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS};")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _exec_atomic(conn: sqlite3.Connection, statements: list[tuple[str, tuple]]) -> None:
    """BEGIN IMMEDIATE で書き込みロックを先取りしつつ複数文を一括実行する。"""
    conn.execute("BEGIN IMMEDIATE;")
    try:
        for sql, params in statements:
            conn.execute(sql, params)
        conn.execute("COMMIT;")
    except Exception:
        conn.execute("ROLLBACK;")
        raise


def _create_tables(conn: sqlite3.Connection) -> None:
    """api_calls / quota_state テーブルとインデックスを作成する。"""
    _exec_atomic(
        conn,
        [
            (
                """
                CREATE TABLE IF NOT EXISTS api_calls (
                    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
                    called_at_utc            TEXT NOT NULL,
                    endpoint                 TEXT NOT NULL,
                    input_summary            TEXT,
                    units_cost               INTEGER NOT NULL DEFAULT 0,
                    cumulative_units_today   INTEGER NOT NULL DEFAULT 0,
                    http_status              INTEGER NOT NULL,
                    http_success             INTEGER NOT NULL,
                    error_code               TEXT,
                    transcript_success       INTEGER,
                    transcript_language      TEXT,
                    result_count             INTEGER
                )
                """,
                (),
            ),
            (
                "CREATE INDEX IF NOT EXISTS idx_api_calls_called_at "
                "ON api_calls(called_at_utc)",
                (),
            ),
            (
                """
                CREATE TABLE IF NOT EXISTS quota_state (
                    id                      INTEGER PRIMARY KEY CHECK (id = 1),
                    quota_date_pt           TEXT NOT NULL,
                    consumed_units_today    INTEGER NOT NULL DEFAULT 0,
                    daily_limit             INTEGER NOT NULL DEFAULT 10000,
                    updated_at_utc          TEXT NOT NULL
                )
                """,
                (),
            ),
        ],
    )


def _ensure_quota_state_row(conn: sqlite3.Connection, now_utc: datetime) -> None:
    """quota_state の id=1 行が無ければ INSERT する。"""
    row = conn.execute("SELECT id FROM quota_state WHERE id = 1").fetchone()
    if row is None:
        _exec_atomic(
            conn,
            [
                (
                    "INSERT INTO quota_state "
                    "(id, quota_date_pt, consumed_units_today, daily_limit, updated_at_utc) "
                    "VALUES (1, ?, 0, ?, ?)",
                    (
                        _today_pt_str(now_utc),
                        YOUTUBE_DAILY_QUOTA_LIMIT,
                        now_utc.isoformat(),
                    ),
                ),
            ],
        )


# ---------- 公開 API ----------

def init(db_path: Path | str, now_utc: datetime | None = None) -> None:
    """SQLite を開き、PRAGMA を適用し、テーブル作成 + 起動時 SUM 復元を行う。

    アプリ起動時に 1 度だけ呼び出す（再 init 可能、テストで複数回呼ばれても安全）。
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    with _lock:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        _state["db_path"] = path

        conn = _connect()
        try:
            _create_tables(conn)
            _ensure_quota_state_row(conn, now_utc)

            # 起動時 SUM 復元（今日 PT 0:00 以降の units_cost 合計）
            today_pt_midnight = _today_pt_midnight_utc(now_utc)
            row = conn.execute(
                "SELECT COALESCE(SUM(units_cost), 0) FROM api_calls "
                "WHERE called_at_utc >= ?",
                (today_pt_midnight.isoformat(),),
            ).fetchone()
            consumed = int(row[0] or 0)

            _state["consumed_units_today"] = consumed
            _state["quota_date_pt"] = _today_pt_str(now_utc)
            _state["exhausted_until"] = None

            # quota_state も同期
            _exec_atomic(
                conn,
                [
                    (
                        "UPDATE quota_state SET consumed_units_today = ?, "
                        "quota_date_pt = ?, updated_at_utc = ? WHERE id = 1",
                        (consumed, _today_pt_str(now_utc), now_utc.isoformat()),
                    ),
                ],
            )
        finally:
            conn.close()


def _maybe_rollover(now_utc: datetime) -> None:
    """PT 0:00 を跨いだ場合に in-memory + quota_state をリセットする。

    呼び出し側は `_lock` を保持していること。
    """
    today_pt = _today_pt_str(now_utc)
    if _state["quota_date_pt"] is None:
        _state["quota_date_pt"] = today_pt
        return
    if _state["quota_date_pt"] != today_pt:
        _state["consumed_units_today"] = 0
        _state["quota_date_pt"] = today_pt
        _state["exhausted_until"] = None
        if _state["db_path"] is not None:
            conn = _connect()
            try:
                _exec_atomic(
                    conn,
                    [
                        (
                            "UPDATE quota_state SET consumed_units_today = 0, "
                            "quota_date_pt = ?, updated_at_utc = ? WHERE id = 1",
                            (today_pt, now_utc.isoformat()),
                        ),
                    ],
                )
            finally:
                conn.close()


def add_units(cost: int, now_utc: datetime | None = None) -> None:
    """YouTube サブ呼び出し成功時に units を計上する。

    更新先 (3 箇所、同時更新):
      1. in-memory `consumed_units_today`（threading.RLock 保護）
      2. SQLite `quota_state` テーブル
      3. ContextVar `_request_cost`（リクエストローカル累計）

    `api_calls` テーブルへは触らない（責務分離: そちらは `record_api_call` の責務）。
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    with _lock:
        _maybe_rollover(now_utc)
        _state["consumed_units_today"] += cost
        if _state["db_path"] is not None:
            conn = _connect()
            try:
                _exec_atomic(
                    conn,
                    [
                        (
                            "UPDATE quota_state SET consumed_units_today = ?, "
                            "updated_at_utc = ? WHERE id = 1",
                            (_state["consumed_units_today"], now_utc.isoformat()),
                        ),
                    ],
                )
            finally:
                conn.close()
        # ContextVar は同一リクエスト（async タスク）内のみで累積する
        _request_cost.set(_request_cost.get() + cost)


def record_api_call(
    endpoint: str,
    input_summary: str | None,
    units_cost: int,
    http_status: int,
    http_success: bool,
    error_code: str | None,
    transcript_success: bool | None = None,
    transcript_language: str | None = None,
    result_count: int | None = None,
    now_utc: datetime | None = None,
) -> None:
    """`api_calls` テーブルに 1 行 INSERT する。`quota_state` には触らない。

    粒度: 1 リクエスト = 1 行（YouTube サブ呼び出しごとには INSERT しない）。
    `endpoint` は 'search' / 'summary' のどちらでも使える。
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    if _state["db_path"] is None:
        raise RuntimeError("quota_tracker.init(db_path) を先に呼んでください")

    with _lock:
        cumulative = _state["consumed_units_today"]

    conn = _connect()
    try:
        _exec_atomic(
            conn,
            [
                (
                    "INSERT INTO api_calls "
                    "(called_at_utc, endpoint, input_summary, units_cost, "
                    " cumulative_units_today, http_status, http_success, error_code, "
                    " transcript_success, transcript_language, result_count) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        now_utc.isoformat(),
                        endpoint,
                        input_summary,
                        int(units_cost),
                        int(cumulative),
                        int(http_status),
                        int(bool(http_success)),
                        error_code,
                        None if transcript_success is None else int(bool(transcript_success)),
                        transcript_language,
                        result_count,
                    ),
                ),
            ],
        )
    finally:
        conn.close()


def is_exhausted(now_utc: datetime | None = None) -> bool:
    """日次クォータが枯渇しているか（推定到達 or 403 強制）。PT 0:00 跨ぎは自動リセット。"""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    with _lock:
        _maybe_rollover(now_utc)
        if _state["consumed_units_today"] >= YOUTUBE_DAILY_QUOTA_LIMIT:
            return True
        if (
            _state["exhausted_until"] is not None
            and now_utc < _state["exhausted_until"]
        ):
            return True
        return False


def mark_exhausted(
    reason: str = "youtube_403", now_utc: datetime | None = None
) -> None:
    """YouTube 403 quotaExceeded 受信時に呼ぶ。次の PT 0:00 まで枯渇扱い。"""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    with _lock:
        _state["exhausted_until"] = _next_pt_midnight_utc(now_utc)


def get_snapshot(now_utc: datetime | None = None) -> Quota:
    """現在のクォータ状態を `Quota` モデルとして返す。

    `last_call_cost` は ContextVar 由来（当該リクエスト内の累積）。
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    with _lock:
        _maybe_rollover(now_utc)
        consumed = _state["consumed_units_today"]
        reset_at_utc = _next_pt_midnight_utc(now_utc)
        reset_at_jst = reset_at_utc.astimezone(JST)
        reset_in_seconds = max(0, int((reset_at_utc - now_utc).total_seconds()))

    return Quota(
        consumed_units_today=consumed,
        daily_limit=YOUTUBE_DAILY_QUOTA_LIMIT,
        last_call_cost=_request_cost.get(),
        reset_at_utc=reset_at_utc,
        reset_at_jst=reset_at_jst,
        reset_in_seconds=reset_in_seconds,
    )


def reset_request_cost() -> None:
    """router 先頭で呼び出し、当該リクエストの cost 累計を 0 にする。"""
    _request_cost.set(0)


def get_request_cost() -> int:
    """当該リクエスト内で `add_units` 経由に積まれた累積 cost を返す。"""
    return _request_cost.get()


def reset() -> None:
    """テスト用: プロセス内状態（_state）をクリアする。SQLite ファイルは残る。"""
    with _lock:
        _state["consumed_units_today"] = 0
        _state["quota_date_pt"] = None
        _state["exhausted_until"] = None
        _state["db_path"] = None
