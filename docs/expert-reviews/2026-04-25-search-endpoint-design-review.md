# 検索エンドポイント設計レビュー — 専門家合意事項

> 調査日: 2026-04-25
> 対象: `.kiro/specs/search-endpoint/requirements.md` (コミット 9d5bd82)
> 回答者: 専門家O（アーキテクト）、専門家A（Web検索確認済）、専門家G（AI調査）
> 信頼度: 以下は3名のコンセンサスが取れ、かつ公式ドキュメントとの照合で信頼性97%以上と判断したもの

本ドキュメントは、`POST /api/v1/search` 追加にあたっての技術的意思決定の根拠を記録する。  
**後続の実装・リファクタリング時は必ずこの文書を参照すること。**

---

## 目次

1. [HTTP クライアント (`requests` の採用と設定)](#1-http-クライアント)
2. [クォータ追跡の二層構造](#2-クォータ追跡の二層構造)
3. [SQLite 並行耐性設定](#3-sqlite-並行耐性設定)
4. [非同期コンテキストでのロック](#4-非同期コンテキストでのロック)
5. [タイムゾーン処理](#5-タイムゾーン処理)
6. [search.list のパラメタ既定値](#6-searchlist-のパラメタ既定値)
7. [バッチ呼び出しの設計](#7-バッチ呼び出しの設計)
8. [transcript 除外と `has_caption` の追加](#8-transcript-除外と-has_caption-の追加)
9. [HTTP ステータスコードの方針](#9-http-ステータスコードの方針)
10. [Pydantic v2 スキーマ設計](#10-pydantic-v2-スキーマ設計)
11. [観測性の最小限ライン](#11-観測性の最小限ライン)
12. [テスト戦略](#12-テスト戦略)
13. [保留事項（コンセンサス未形成）](#13-保留事項)
14. [参考リンク](#14-参考リンク)

---

## 1. HTTP クライアント

**結論: `requests.Session` + `urllib3.util.retry.Retry` で十分（3名全員一致）**

### 採用設定

- リトライ対象: `429, 500, 502, 503, 504`
- `backoff_factor=1.0` の指数バックオフ
- `backoff_jitter=0.3` でサンダーリングハード回避
- `Retry-After` ヘッダを尊重（`respect_retry_after_header=True`）
- `allowed_methods=["GET"]` のみ

### 重要: 403 `quotaExceeded` はリトライしない

- YouTube Data API の `403` エラーは `errors[0].reason` に理由が入る
- `quotaExceeded` / `rateLimitExceeded` / `keyInvalid` を判別して分岐
- `quotaExceeded` は即座に `QUOTA_EXCEEDED` 扱い（リトライすると日次カウンタを無駄に溶かす上、ログが汚れる）

### `google-api-python-client` を採用しない理由

- 使うエンドポイントは `search.list` / `videos.list` / `channels.list` の3本のみ
- Discovery API 呼び出し・OAuth 機構が不要
- 公式クライアントも YouTube Data API 向けの自動指数バックオフは **未実装**（`google-api-core.retry` は gRPC 向け）
- 依存サイズ 50MB+ を追加する利点がない

---

## 2. クォータ追跡の二層構造

**結論: プロセス内カウンタ + SQLite 永続化、YouTube 403 が最終判定（3名全員一致）**

### 権威 / 推定 の分離

| レイヤ | 役割 | 実装 |
|---|---|---|
| 権威（ground truth） | YouTube が 403 `quotaExceeded` を返した瞬間に「今日はもう無理」確定 | `quota_state.exhausted_until = 次のPT 0:00` |
| 推定（estimate） | 呼び出し毎に積算したローカル値 | メモリカウンタ + SQLite `quota_state` |

- レスポンスで返すフィールドは `remaining_units_estimate`（"estimate" を名前で明示）
- 実測値を返す手段は存在しない（Cloud Quotas API は設定値しか返さない / Console UI は日次集計で即時性なし）

### 起動時の再計算

- プロセス再起動時は SQLite から `SELECT SUM(units_cost) FROM api_calls WHERE called_at_utc >= (今日のPT 0:00のUTC値)` で `quota_state.consumed_units_today` を復元
- 手動でDBを触った場合の不整合検出にも有効

### JSONL / 単一 JSON を採用しない理由

- JSON 上書き: クラッシュ時の部分書き込みリスク
- JSONL: 追記は速いが集計で全走査が必要
- SQLite: INSERT + `SELECT SUM()` で両立、1行 <1ms で書ける（1日100回未満なら完全に余裕）

---

## 3. SQLite 並行耐性設定

**結論: WAL モード + busy_timeout 5秒 + BEGIN IMMEDIATE（3名全員一致）**

### 接続初期化 PRAGMA

以下を接続直後に必ず実行する:

```python
conn = sqlite3.connect("data/usage/usage.db", timeout=5.0, isolation_level=None)
conn.execute("PRAGMA journal_mode=WAL;")      # 読み書き並行性の向上
conn.execute("PRAGMA synchronous=NORMAL;")     # fsync頻度をFULLから緩和（WALなら十分安全）
conn.execute("PRAGMA busy_timeout=5000;")      # ロック待ち最大5秒
conn.execute("PRAGMA foreign_keys=ON;")        # 外部キー制約を有効化
```

### 書き込みパターン

- 書き込みは必ず `BEGIN IMMEDIATE` で書き込みロックを先取り
- 暗黙の `BEGIN` は後から `SQLITE_BUSY` を食う可能性がある

```python
conn.execute("BEGIN IMMEDIATE;")
try:
    conn.execute("UPDATE quota_state SET ...")
    conn.execute("INSERT INTO api_calls ...")
    conn.execute("COMMIT;")
except Exception:
    conn.execute("ROLLBACK;")
    raise
```

### PostgreSQL 移行の定量閾値

以下のいずれかを満たしたら検討:

- 持続書き込み **10 QPS 超**
- 同時 writer **3 プロセス超**
- 同時接続 **20超**
- `SQLITE_BUSY` が **週1回以上** 発生
- ファイル共有がネットワーク越し（NFS 等）

**本件の現状規模（個人利用、worker 1、1日最大約98検索）では移行不要。**

---

## 4. 非同期コンテキストでのロック

**結論: `asyncio.Lock` を使用（3名全員一致）**

### `threading.Lock` を async def で使わない理由

- `threading.Lock.acquire()` はイベントループを **完全停止** させる
- 他のリクエストやバックグラウンドタスクが全て待たされる
- 短時間なら実害は小さいが、ベストプラクティス違反

### 実装パターン

```python
import asyncio
from collections import deque

class AsyncSlidingWindow:
    def __init__(self, max_calls: int, window_sec: float):
        self._max = max_calls
        self._window = window_sec
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def try_acquire(self) -> tuple[bool, float]:
        async with self._lock:
            now = asyncio.get_event_loop().time()
            while self._calls and now - self._calls[0] > self._window:
                self._calls.popleft()
            if len(self._calls) >= self._max:
                retry_after = self._window - (now - self._calls[0])
                return False, retry_after
            self._calls.append(now)
            return True, 0.0
```

### 既存 `app/core/rate_limiter.py` の扱い

- 現行は `threading.Lock` ベースで `/summary` が使用中
- `/summary` は 60秒に1回のため実害は僅少だが、**新規に書く `/search` は `asyncio.Lock` を採用**
- 既存コードの書き換えは必須ではない（別件で対応可）

### ライブラリ採用判断

- 単一エンドポイントで1ルールなら自前実装で十分
- 将来5種類以上のルールが並ぶなら `slowapi` 移行を検討
- `fastapi-limiter` は Redis 前提なので本件では過剰

---

## 5. タイムゾーン処理

**結論: `zoneinfo.ZoneInfo("America/Los_Angeles")` + datetime.combine パターン（3名全員一致、細部は多少差分あり）**

### ゾーン名

- IANA 正式名は `America/Los_Angeles`
- `US/Pacific` は歴史的エイリアス（動作はするが非推奨）
- **新規コードでは `America/Los_Angeles` を使用**

### リセット時刻算出

常に UTC で保持・計算、PT への変換は表示時のみ:

```python
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")

def next_pt_midnight_utc(now_utc: datetime) -> datetime:
    """次のPT 0:00をUTCで返す。DST自動処理。"""
    now_pt = now_utc.astimezone(PT)
    next_day_pt = datetime.combine(
        now_pt.date() + timedelta(days=1),
        time.min,
        tzinfo=PT,
    )
    return next_day_pt.astimezone(timezone.utc)
```

### DST 境界で抑えるべきテストシナリオ

- **2026-03-08 開始**: PST 01:59 → PDT 03:00 ジャンプ（02:00〜02:59 が存在しない）
- **2026-11-01 終了**: PDT 01:59 → PST 01:00 巻き戻し（01:00〜01:59 が2回発生、`fold` 属性で区別）
- PT 0:00 自体は DST の影響を受けない（0:00 は常に1日1回）
- 通常日の境界前後 ±1分

### ローカル時刻で `timedelta` 演算しない

- `pytz` 時代からの古典的罠。`zoneinfo` でも同じ
- 加減算は必ず UTC で行い、最後に PT へ変換

---

## 6. search.list のパラメタ既定値

**結論: `type=video` 固定は3者一致、その他の既定値は保留（[§13](#13-保留事項)参照）**

### サーバー側で固定

- **`type=video`**: 3名全員一致で必須。指定しないと channel/playlist が混在し、`videos.list(id=...)` でエラーになる
- **`videoEmbeddable=true` は既定にしない**: 埋め込み可能動画だけに偏る（3名一致）
- **`maxResults=50`**: サーバー固定（既存設計通り）

### リクエストで受け付ける（デフォルトは YouTube API 側に任せる）

- `order` (relevance/date/rating/viewCount/title)
- `publishedAfter` / `publishedBefore`
- `videoDuration` (any/short/medium/long)
- `regionCode`, `relevanceLanguage`, `channelId`

### ノイジークエリ対策

- サーバー側で勝手に絞らない（AIの探索意図を潰さない）
- クライアント（AI）側で「結果が薄い → `order=viewCount` で再検索」のリトライ戦略を取らせる
- 再検索は +100 units なので、AI プロンプトで回数制限ガイダンスを与える

---

## 7. バッチ呼び出しの設計

**結論: 50 IDs 固定、`itertools.batched` で分割、part 複数指定は1 unit のまま（3名全員一致）**

### 正しいパターン

```python
from itertools import batched  # Python 3.12+

# video_ids, channel_ids は重複排除済みの list
for chunk in batched(video_ids, 50):
    # videos.list?id=a,b,c&part=snippet,contentDetails,statistics → 1 unit
    ...
for chunk in batched(channel_ids, 50):
    # channels.list?id=a,b,c&part=snippet,statistics → 1 unit
    ...
```

### コスト特性（公式クォータ表ベース）

- `part=snippet,contentDetails,statistics` と複数指定してもコールあたり **1 unit**
- part ごとに分割すると割高（part数 × 1 unit）
- 50 IDs/コール は YouTube Data API の仕様上限

### 将来 maxResults > 50 対応時

- `videos.list` を chunk 数分呼ぶ（2 chunks なら 2 units）
- `channels.list` は 50動画で 20-30 unique なので通常 1 chunk

---

## 8. transcript 除外と `has_caption` の追加

**結論: 検索レスポンスに transcript は含めない。代わりに `has_caption` を返す（3名全員一致）**

### 除外理由（2026年4月現在も継続）

- `youtube-transcript-api` は非公式スクレイピング依存
- 同一 IP から短時間に多数のリクエストで **IP BAN（CAPTCHA 要求状態）**
- 50本一括取得は現状の60秒セルフ制限を **事実上バイパス**
- BAN されると `/summary` 側も停止する二次被害

### `has_caption` の取得方法

- `videos.list(part=contentDetails)` の `contentDetails.caption` は `"true"` / `"false"` 文字列
- **追加 API コスト 0 unit**（既存の videos.list 呼び出しで一緒に取得）
- AI は「字幕ある動画だけ `/summary` に回そう」と自律判断可能

### 「先頭30秒だけ字幕」案を採用しない理由

- 結局 `youtube-transcript-api` を50回叩くことに変わりない
- バイト数ではなくリクエスト数で BAN されるため、本質が解決しない

### 推奨ワークフロー

```
AI: /search で候補50件を一気に取得 (has_caption 付き)
 ↓
AI: has_caption=true のうち関心の高いもの上位2-3件を選定
 ↓
AI: 選んだ video_id に対して /summary を逐次呼ぶ
    (60秒セルフ制限により自動的に安全)
```

---

## 9. HTTP ステータスコードの方針

**結論: `/search` は標準 HTTP ステータスを返す。`/summary` は 200 固定を維持（3名全員一致）**

これは `requirements.md` の「HTTP ステータスは常に 200」の方針に対する **明確な変更推奨**。

### 根拠

- LLM Tool SDK（Anthropic `tool_use` / OpenAI tools / MCP 等）は HTTP ステータスで自動リトライを分岐
- 200 でエラーを返すと LLM が「成功」と誤認 → エラー文字列を検索結果として解釈するハルシネーション
- MCP 公式仕様は内部で `isError: true` を使うパターンを推奨するが、**ビジネスエラー vs インフラエラーを分けるのが 2026 年の事実上の標準**

### 推奨マッピング（`/search`）

| 状況 | HTTP | error_code |
|---|---|---|
| 成功 | 200 | `null` |
| 認証エラー（X-API-KEY不正） | 401 | `UNAUTHORIZED` |
| リクエスト構造違反 | 422 | （FastAPI/Pydantic 標準） |
| 自サーバ短期レート制限 | 429 | `CLIENT_RATE_LIMITED` |
| YouTube 日次クォータ枯渇 | 429 または 403 | `QUOTA_EXCEEDED` |
| YouTube 一時制限 | 503 または 429 | `RATE_LIMITED` |
| 内部エラー | 500 | `INTERNAL_ERROR` |

### 共通の追加

- 429 / 503 / 403 レスポンスには **`Retry-After` ヘッダ** を付与
- レスポンスボディは既存形式（`success`, `error_code`, `message`, `quota`）を維持
  - → HTTP を見る SDK と、ボディを見るクライアントの両対応

### `/summary` の扱い

- iPhone ショートカット互換のため 200 固定を継続
- 既存テスト・クライアントの破壊を回避

---

## 10. Pydantic v2 スキーマ設計

**結論: `X | None` に統一、`computed_field`、`frozen=True`、標準 `BaseModel`（3名全員一致）**

### 型ヒント

- **`Optional[X]` は使わない、`X | None` に統一**
- Python 3.10+ ネイティブ、Pydantic v2 は両方サポートするが可読性で一貫性優先
- 既存の `Optional[str]` を使っているコードは別件で置換（機能的には同等）

### `computed_field` で動的計算

```python
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field, computed_field

class Quota(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    consumed_units_today: int
    daily_limit: int = 10_000
    last_call_cost: int
    reset_at_utc: datetime

    @computed_field
    @property
    def remaining_units_estimate(self) -> int:
        return max(0, self.daily_limit - self.consumed_units_today)

    @computed_field
    @property
    def reset_in_seconds(self) -> int:
        delta = (self.reset_at_utc - datetime.now(timezone.utc)).total_seconds()
        return max(0, int(delta))
```

### `model_config`

- `ConfigDict(frozen=True, extra="forbid")` を全レスポンスモデルに適用
- `frozen=True`: 不変オブジェクト化、微小なパフォーマンス向上
- `extra="forbid"`: 想定外のフィールドを拒否（コード変更時の検出）

### `RootModel` は使わない

- `results` はトップレベルのリストではなくフィールドのため不要

### `model_validator(mode="after")` で相関制約

- `success=False` のとき `error_code is not None` を検証
- 逆 (`success=True` で `error_code is not None`) も検証

---

## 11. 観測性の最小限ライン

**結論: 現状 (`logging` + SQLite `api_calls`) で十分、構造化ログ追加は推奨（3名全員一致）**

### 区分

| 項目 | 判定 | 理由 |
|---|---|---|
| Python 標準 `logging` | **必須** | エラー・429・クォータ枯渇の追跡 |
| SQLite `api_calls` テーブル | **必須** | 日次消費と AI 暴走検知 |
| JSON 構造化ログ（`structlog` or json.JSONFormatter） | **推奨** | grep とクエリ容易性 |
| `X-Request-ID` ヘッダ + ログ伝播 | あったら便利 | 分散追跡の第一歩 |
| Sentry | 過剰（10人超 or プロダクショントラフィック時検討） | |
| Prometheus / Grafana | 過剰（20+ メトリクス / 時系列可視化必要時） | |
| OpenTelemetry tracing | 過剰（マルチサービス / QPS 10+ 時） | |

### 構造化ログ最小実装

```python
import logging, json
class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "ts": record.created,
            "level": record.levelname,
            "msg": record.getMessage(),
            "logger": record.name,
            **(getattr(record, "extra", {}) or {}),
        }, ensure_ascii=False)
```

---

## 12. テスト戦略

**結論: 3層構成 — モック/スナップショット/任意の実API（3名全員一致）**

### 第1層: 通常 CI、全モック

- 既存方針（97 件）を継続
- `requests.get` を `unittest.mock` でパッチ
- 新規テストも同じ方針

### 第2層: スキーマスナップショット

- 実 API レスポンスを 1 回保存（手動 or 初回取得時）:
  - `tests/snapshots/search_list_sample.json`
  - `tests/snapshots/videos_list_sample.json`
  - `tests/snapshots/channels_list_sample.json`
- Pydantic モデルで `model_validate(json.load(f))` が通ることを検証
- API スキーマが変わった時だけ人間が更新

```python
def test_search_list_schema_snapshot():
    data = json.loads(Path("tests/snapshots/search_list_sample.json").read_text())
    resp = YouTubeSearchListResponse.model_validate(data)
    assert len(resp.items) > 0
```

### 第3層: 実 API (任意、手動 or 月次 CI)

- 環境変数 `RUN_LIVE_YOUTUBE_TESTS=1` で有効化
- 週1 または月1 の頻度
- 1回 = 約102 units（日次の1%）→ コスト許容範囲
- 通常の CI からは除外（フレイキー要因を避ける）

### Pact 等の採用は見送り

- Pact は双方向の契約テストが前提
- YouTube API は一方的な外部依存なので原理的に合わない
- API 利用者が複数プロジェクトに増えたら検討

---

## 13. 保留事項

以下は3名の間でコンセンサスが取れなかった、または `requirements.md` の範囲を超えるため本レビューでは採用決定しない:

### safeSearch の既定値

- O: `moderate`（YouTube API デフォルトに合わせる）
- A: 既定指定不要（YouTube 側で `moderate` になる）
- G: `none`（AI の検索意図を潰さない）
- **判断**: 既定指定せず、YouTube 側デフォルト（`moderate`）に任せる方針でスタート。実運用で不満が出たら変更

### regionCode の既定値

- O: `JP` 推奨（リクエストで override 可能）
- A: `regionCode=JP` は「視聴可能動画フィルタ」の副作用があり、意味合いが期待と異なる
- G: `JP` 強く推奨（グローバル動画の混入回避）
- **判断**: リクエストパラメタで受けるが、サーバー側デフォルトは **指定しない**。AI が必要に応じて渡す

### HTTP async 対応（requests vs httpx）

- O, A: `requests` で問題なし
- G: FastAPI の async def 内での sync `requests` は技術的にブロッキング。`httpx` + `tenacity` を強く推奨
- **判断**: 個人利用・同時接続1-2の規模では実害が低いため現状維持。ただし将来の選択肢として記録

### slowapi 採用

- O: 不要、自前実装で十分
- A: 単一ルールなら不要、5種類以上で検討
- G: 推奨（2026年のFastAPI標準）
- **判断**: 自前実装でスタート、ルール増加時に再検討

---

## 14. 参考リンク

### YouTube Data API v3（公式）

- [Quota Calculator](https://developers.google.com/youtube/v3/determine_quota_cost) — クォータコスト表（search=100, videos/channels=各1）
- [Getting Started](https://developers.google.com/youtube/v3/getting-started) — 認証・エンドポイント概要
- [search.list](https://developers.google.com/youtube/v3/docs/search/list) — 検索仕様
- [videos.list](https://developers.google.com/youtube/v3/docs/videos/list) — 動画詳細仕様
- [channels.list](https://developers.google.com/youtube/v3/docs/channels/list) — チャンネル情報仕様

### Pydantic v2

- [Concepts: Models](https://docs.pydantic.dev/latest/concepts/models/)
- [ConfigDict](https://docs.pydantic.dev/latest/api/config/)
- [v1 → v2 Migration](https://docs.pydantic.dev/latest/migration/)

### FastAPI

- [Concurrency and async/await](https://fastapi.tiangolo.com/async/) — sync 処理の async 内での扱い

### SQLite

- [Write-Ahead Logging](https://sqlite.org/wal.html) — WAL モード公式解説
- [Python sqlite3](https://docs.python.org/3/library/sqlite3.html)

### Python zoneinfo

- [PEP 615: Support for the IANA Time Zone Database](https://peps.python.org/pep-0615/)

### youtube-transcript-api（IP BAN 参考）

- [Repository README](https://github.com/jdepoix/youtube-transcript-api)
- [Issue #511: IP block in cloud](https://github.com/jdepoix/youtube-transcript-api/issues/511)

### LLM Tool / API 設計

- [Anthropic API Errors](https://docs.anthropic.com/en/api/errors)
- [MCP Tools Specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
