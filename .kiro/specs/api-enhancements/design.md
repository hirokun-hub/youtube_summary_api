# 設計書: APIレスポンス拡充 — テスト駆動開発

## 1. テスト基盤の設計

### 1.1 テストフレームワーク

| 項目 | 選定 | 理由 |
|------|------|------|
| テストフレームワーク | **pytest** | FastAPIの公式ドキュメントが推奨。fixture・parametrize等の機能がTDDに適する |
| HTTPクライアント | **httpx + FastAPI TestClient** | FastAPIのエンドポイントをサーバー起動なしでテスト可能 |
| モック | **unittest.mock（標準ライブラリ）** | 外部API（yt-dlp, oEmbed, youtube-transcript-api）をモックする |

### 1.2 ディレクトリ構成

```
youtube_summary_api/
├── app/
│   ├── core/
│   ├── models/
│   │   └── schemas.py          ← レスポンスモデル拡張
│   ├── routers/
│   │   └── summary.py
│   └── services/
│       └── youtube.py          ← yt-dlp取得関数追加・エラーハンドリング改善
├── tests/                       ← 新規作成
│   ├── __init__.py
│   ├── conftest.py              ← 共通fixture（TestClient, モック, テスト用データ）
│   ├── test_schemas.py          ← レスポンスモデルの型・フィールド検証
│   ├── test_youtube_service.py  ← サービス層の単体テスト（モック使用）
│   └── test_api_endpoint.py     ← APIエンドポイントの統合テスト
├── requirements.txt              ← 本番依存
├── requirements-dev.txt          ← テスト・開発依存（-r requirements.txt を含む）
└── pytest.ini                    ← pytest設定
```

### 1.3 テストの分類と方針

| テスト種別 | ファイル | テスト対象 | 外部通信 |
|-----------|---------|-----------|---------|
| モデルテスト | `test_schemas.py` | `SummaryResponse` のフィールド定義・型・デフォルト値 | なし |
| サービス単体テスト | `test_youtube_service.py` | `get_summary_data()` のビジネスロジック | すべてモック |
| API統合テスト | `test_api_endpoint.py` | `POST /api/v1/summary` のリクエスト〜レスポンス | すべてモック |

**原則: テストでは外部通信を一切行わない。** yt-dlp, oEmbed API, youtube-transcript-api はすべてモックする。

### 1.4 依存パッケージの分離

```
# requirements.txt（本番）
fastapi==0.115.14
uvicorn
yt-dlp[default]
youtube-transcript-api>=1.2.0
python-dotenv
requests

# requirements-dev.txt（テスト・開発）
-r requirements.txt
pytest
httpx
```

Dockerfile ではビルド引数で切り替え:
- 本番: `pip install -r requirements.txt`
- テスト: `pip install -r requirements-dev.txt`

## 2. モック戦略

### 2.1 モック対象と方法

youtube-transcript-api v1.2.x ではインスタンスメソッドに変更されているため、クラス自体をモックする。
yt-dlp もコンテキストマネージャ経由のインスタンスメソッドのため同様。

| 外部依存 | モック対象 | patchターゲット | モック方法 |
|---------|-----------|---------------|-----------|
| yt-dlp | `YoutubeDL` クラス | `app.services.youtube.yt_dlp.YoutubeDL` | クラスをモックし、`__enter__` が返すインスタンスの `extract_info` の戻り値を設定 |
| oEmbed API | `requests.get` | `app.services.youtube.requests.get` | `unittest.mock.patch` で固定JSONを返す |
| youtube-transcript-api | `YouTubeTranscriptApi` クラス | `app.services.youtube.YouTubeTranscriptApi` | クラスをモックし、インスタンスの `fetch()` の戻り値を設定 |

### 2.2 モックのコード例

#### yt-dlp のモック

```python
@patch('app.services.youtube.yt_dlp.YoutubeDL')
def test_metadata(mock_ydl_class):
    mock_instance = mock_ydl_class.return_value.__enter__.return_value
    mock_instance.extract_info.return_value = {
        "title": "テスト動画",
        "channel": "テストチャンネル",
        "upload_date": "20260208",
        "duration": 360,
        # ... 他のフィールド
    }
```

#### youtube-transcript-api のモック（v1.2.x — `fetch()` ショートカット使用）

`fetch()` ショートカットにより、`list()` → `find_transcript()` → `fetch()` の3ステップは不要。
`FetchedTranscript` が `language_code` と `is_generated` を直接持つため、モックが大幅に簡略化される。

```python
@patch('app.services.youtube.YouTubeTranscriptApi')
def test_transcript(mock_ytt_class):
    mock_instance = mock_ytt_class.return_value

    mock_fetched = MagicMock()
    mock_fetched.language_code = 'ja'
    mock_fetched.is_generated = False
    mock_fetched.to_raw_data.return_value = [
        {'text': 'こんにちは', 'start': 0.0, 'duration': 1.5}
    ]
    mock_instance.fetch.return_value = mock_fetched
```

### 2.3 テスト用固定データ（conftest.py に定義）

モックが返す固定データは実際のYouTubeレスポンスを模した現実的な値を使う:

- **yt-dlp成功レスポンス**: title, channel, upload_date, duration, view_count, thumbnail, description, tags, categories 等の全項目（`sanitize_info` 済みの形式を想定）
- **oEmbed成功レスポンス**: title, author_name, thumbnail_url 等（フォールバック用）
- **youtube-transcript-api成功レスポンス**: `FetchedTranscript` 互換のモック（`.to_raw_data()` で `list[dict]` を返す、`.language_code` と `.is_generated` を持つ）
- **各種失敗レスポンス**: `yt_dlp.utils.DownloadError`, `NoTranscriptFound`, `TranscriptsDisabled`, `RequestBlocked` 等の例外

### 2.4 環境変数のモック

`main.py` がモジュールレベルで `load_dotenv()` を実行し、`.env.local` を `override=True` で読み込むため、
テスト環境に `.env.local` が存在すると `os.environ` が上書きされるリスクがある。

以下の2段階で対応する:

```python
# tests/conftest.py の先頭
import os
os.environ["API_KEY"] = "test-api-key"

# この後にアプリをインポート（load_dotenvが実行される）
from main import app
```

**注意:** `.env.local` の `override=True` により上書きされる可能性があるため、
APIキー認証のテストは `dependency_overrides` によるバイパスを主軸とする（2.5参照）。
テスト環境に `.env.local` が存在する場合でも `dependency_overrides` でバイパスすれば影響を受けない。

### 2.5 APIキー認証の無効化

FastAPI公式推奨の `dependency_overrides` を使用。
E-2（APIキーなし→403）テスト用に、`dependency_overrides` なしの別fixtureも用意する:

```python
from app.core.security import verify_api_key

@pytest.fixture
def client():
    """認証をバイパスする通常テスト用クライアント"""
    app.dependency_overrides[verify_api_key] = lambda: "test-key"
    yield TestClient(app)
    app.dependency_overrides.clear()

@pytest.fixture
def client_no_auth_override():
    """認証バイパスなしのクライアント（E-2テスト用）"""
    app.dependency_overrides.clear()
    yield TestClient(app)
    app.dependency_overrides.clear()
```

## 3. テストケース設計

### 3.1 test_schemas.py — レスポンスモデルの検証（6ケース）

| # | テストケース | 検証内容 |
|---|------------|---------|
| S-1 | 全フィールドが定義されていること | SummaryResponse に既存5フィールド + 新規16フィールドが存在する。`status` は `@computed_field` のため `model_computed_fields` で確認する |
| S-2 | 成功レスポンスの生成 | 全フィールドに値を入れてインスタンス化できる |
| S-3 | 失敗レスポンスの生成（メタデータあり） | transcript=null でもインスタンス化できる |
| S-4 | 失敗レスポンスの生成（メタデータなし） | 全フィールド null でもインスタンス化できる |
| S-5 | status フィールドの値 | success=True のとき status="ok"、success=False のとき status="error" |
| S-6 | 後方互換性 | 既存5フィールド（success, message, title, channel_name, transcript）の型が変更されていない |

### 3.2 test_youtube_service.py — サービス層の単体テスト（17ケース）

| # | テストケース | モック状態 | 期待結果 |
|---|------------|-----------|---------|
| Y-1 | 正常系: 全データ取得成功 | yt-dlp成功 + transcript成功 | success=True, 全フィールドに値あり, oEmbed呼び出しなし |
| Y-2 | 正常系: yt-dlp失敗→oEmbedフォールバック+transcript成功 | yt-dlp DownloadError + oEmbed成功 + transcript成功 | success=True, title/channel_nameはoEmbedから, yt-dlp由来フィールドはnull |
| Y-3 | 異常系: 字幕なし + メタデータ成功 | yt-dlp成功 + NoTranscriptFound | success=False, error_code="TRANSCRIPT_NOT_FOUND", メタデータはすべて埋まっている |
| Y-4 | 異常系: 動画が存在しない | yt-dlp DownloadError + oEmbed 404 | success=False, error_code="VIDEO_NOT_FOUND" |
| Y-5 | 異常系: 無効なURL | — | success=False, error_code="INVALID_URL" |
| Y-6 | 異常系: レート制限（YouTubeRequestFailed） | YouTubeRequestFailed | success=False, error_code="RATE_LIMITED" |
| Y-7 | 異常系: 予期せぬエラー | 任意のException | success=False, error_code="INTERNAL_ERROR" |
| Y-8 | 安定性中フィールドの欠損 | yt-dlp成功だが like_count=None, channel_follower_count=None | success=True, 該当フィールドがnull |
| Y-9 | transcript_language と is_generated の取得 | transcript `fetch()` 成功 | `FetchedTranscript.language_code` と `FetchedTranscript.is_generated` が正しく設定される |
| Y-10 | yt-dlp DownloadError → error_code マッピング | yt-dlp DownloadError + transcript成功 | error_code="METADATA_FAILED", success=True |
| Y-11 | transcript の後方互換性 | transcript成功 | transcriptフィールドのフォーマットが現在と同一（`[HH:MM:SS] テキスト` のタイムスタンプ付き） |
| Y-12 | yt-dlp戻り値にキーが存在しない場合 | yt-dlp成功だが duration_string, categories 等が欠損 | 該当フィールドがnull, エラーにならない |
| Y-13 | error_code 7種の全カバレッジ | 各例外パターン | INVALID_URL, VIDEO_NOT_FOUND, TRANSCRIPT_NOT_FOUND, TRANSCRIPT_DISABLED, RATE_LIMITED, METADATA_FAILED, INTERNAL_ERROR |
| Y-14 | 異常系: 字幕機能が無効化 | yt-dlp成功 + TranscriptsDisabled | success=False, error_code="TRANSCRIPT_DISABLED", メタデータはすべて埋まっている |
| Y-15 | 異常系: IPブロック（RequestBlocked） | RequestBlocked | success=False, error_code="RATE_LIMITED" |
| Y-16 | 異常系: oEmbedタイムアウト/非JSONレスポンス | yt-dlp DownloadError + oEmbed タイムアウトまたは非JSON | success の判定は字幕取得結果による, oEmbed由来フィールドもnull |
| Y-17 | video_id 正規表現の境界値テスト | 各種URL形式（shorts/, ライブURL, クエリ順序等） | 正しくvideo_idが抽出される/されない |

### 3.3 test_api_endpoint.py — API統合テスト（7ケース）

| # | テストケース | 検証内容 |
|---|------------|---------|
| E-1 | 正常リクエスト | POST /api/v1/summary → 200, 全フィールド存在 |
| E-2 | APIキーなし | POST → 403 |
| E-3 | 無効なURL | POST → 200, success=False, error_code="INVALID_URL" |
| E-4 | 字幕なし動画 | POST → 200, success=False, error_code="TRANSCRIPT_NOT_FOUND", メタデータあり |
| E-5 | 後方互換性 | レスポンスJSONに既存5フィールドが含まれ、型が正しい |
| E-6 | status フィールド | 成功時 status="ok"、失敗時 status="error" |
| E-7 | transcript_language, is_generated がレスポンスに含まれる | 成功時に値が設定されている |

**合計: 30ケース**

## 4. TDD開発サイクル

各タスクで以下のサイクルを繰り返す:

```
1. RED   — 期待する動作のテストを書く → テスト失敗を確認
2. GREEN — テストが通る最小限のコードを書く
3. REFACTOR — コードを整理する（テストは通ったまま）
```

### 実装順序

```
Phase 1: テスト基盤構築
  → pytest + conftest.py のセットアップ（環境変数モック、TestClient、APIキー無効化）
  → requirements-dev.txt 作成
  → test_schemas.py（S-1〜S-6）を書く → RED

Phase 2: レスポンスモデル実装
  → schemas.py を拡張 → GREEN
  → リファクタリング

Phase 3: サービス層テスト → 実装
  → test_youtube_service.py（Y-1〜Y-17）を書く → RED
  → youtube.py に yt-dlp取得関数 + 新transcript-api対応（fetch()ショートカット） + エラーハンドリングを実装 → GREEN
  → リファクタリング

Phase 4: API統合テスト → 確認
  → test_api_endpoint.py（E-1〜E-7）を書く → RED
  → 必要な修正を行う → GREEN

Phase 5: Docker環境更新 + 実環境テスト
  → Dockerfile更新（Denoインストール追加、yt-dlp[default]）
  → Docker Compose でビルド・起動・手動確認
```

## 5. テスト実行方法

### ローカル実行

```bash
# テスト用依存のインストール
pip install -r requirements-dev.txt

# 全テスト実行
pytest tests/ -v

# 特定ファイルのみ
pytest tests/test_schemas.py -v

# 特定テストのみ
pytest tests/test_youtube_service.py::test_success_all_data -v
```

### Docker内実行

```bash
# テスト用イメージでビルド（INSTALL_DEV=true）
docker compose exec api pytest tests/ -v
```
