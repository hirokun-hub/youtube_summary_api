# YouTube Summary API

YouTube動画のメタデータと字幕（文字起こし）を取得するFastAPIサーバーです。Docker Composeで常駐し、ホスト側のTailscale経由でTailnet内にプライベート公開して運用します。

## 機能

- YouTube動画のメタデータ取得（**YouTube Data API v3** + oEmbedフォールバック）
- 字幕取得（`youtube-transcript-api`）
- 8種のエラーコードによる障害原因の特定
- クライアント側レート制限（YouTubeへの集中アクセス予防）
- Tailnet経由のセキュアなアクセス
- iPhoneショートカットからの利用を想定した設計

## APIリファレンス

### `POST /api/v1/summary`

YouTube動画のURLを受け取り、メタデータと字幕を返します。

#### リクエスト

```bash
curl -X POST http://<host>:10000/api/v1/summary \
  -H "Content-Type: application/json" \
  -H "X-API-KEY: your-api-key" \
  -d '{"url": "https://www.youtube.com/watch?v=xxxxx"}'
```

#### レスポンスフィールド一覧

| フィールド | 型 | 説明 |
|---|---|---|
| `success` | bool | 字幕取得に成功したか |
| `status` | string | `"ok"` または `"error"`（iPhoneの言語設定に依存しない判定用） |
| `message` | string | 処理結果の説明メッセージ |
| `error_code` | string \| null | エラー種別コード（成功時はnull） |
| `title` | string \| null | 動画タイトル |
| `channel_name` | string \| null | チャンネル名 |
| `channel_id` | string \| null | チャンネルID |
| `channel_follower_count` | int \| null | チャンネル登録者数 |
| `upload_date` | string \| null | 投稿日（ISO 8601: YYYY-MM-DD） |
| `duration` | int \| null | 動画の長さ（秒） |
| `duration_string` | string \| null | 動画の長さ（"6:00"形式） |
| `view_count` | int \| null | 再生回数 |
| `like_count` | int \| null | 高評価数 |
| `thumbnail_url` | string \| null | サムネイルURL |
| `description` | string \| null | 概要欄テキスト |
| `tags` | list[str] \| null | タグ一覧 |
| `categories` | list[str] \| null | カテゴリ一覧 |
| `webpage_url` | string \| null | 正規化された動画URL |
| `transcript` | string \| null | タイムスタンプ付き文字起こし全文 |
| `transcript_language` | string \| null | 取得した字幕の言語コード |
| `is_generated` | bool \| null | 自動生成字幕かどうか |
| `retry_after` | int \| null | 次のリクエストまで待つべき秒数（クライアント側レート制限時のみ） |

#### エラーコード

| error_code | 意味 |
|---|---|
| `null` | エラーなし（success=true） |
| `INVALID_URL` | YouTube URLとして認識できない |
| `VIDEO_NOT_FOUND` | 動画が存在しない・非公開・削除済み |
| `TRANSCRIPT_NOT_FOUND` | 指定言語の字幕が見つからない |
| `TRANSCRIPT_DISABLED` | 字幕機能が無効化されている |
| `RATE_LIMITED` | YouTube側のレート制限・日次クォータ超過 |
| `CLIENT_RATE_LIMITED` | 本APIサーバのクライアント側レート制限（連続リクエスト間隔が短すぎる） |
| `METADATA_FAILED` | メタデータ取得失敗（字幕は取得成功） |
| `INTERNAL_ERROR` | 予期せぬエラー |

#### レスポンス例（成功）

```json
{
  "success": true,
  "status": "ok",
  "message": "Successfully retrieved data.",
  "error_code": null,
  "title": "動画タイトル",
  "channel_name": "チャンネル名",
  "channel_id": "UCxxxx",
  "channel_follower_count": 1250000,
  "upload_date": "2026-02-08",
  "duration": 360,
  "duration_string": "6:00",
  "view_count": 54000,
  "like_count": 1200,
  "thumbnail_url": "https://i.ytimg.com/vi/xxx/maxresdefault.jpg",
  "description": "概要欄テキスト...",
  "tags": ["Python", "Tutorial"],
  "categories": ["Education"],
  "webpage_url": "https://www.youtube.com/watch?v=xxx",
  "transcript": "[00:00:00] こんにちは...",
  "transcript_language": "ja",
  "is_generated": true
}
```

#### レスポンス例（失敗 — 字幕なし、メタデータあり）

```json
{
  "success": false,
  "status": "error",
  "message": "この動画には利用可能な文字起こしがありませんでした。",
  "error_code": "TRANSCRIPT_NOT_FOUND",
  "title": "動画タイトル",
  "channel_name": "チャンネル名",
  "upload_date": "2026-02-08",
  "duration": 360,
  "transcript": null,
  "transcript_language": null,
  "is_generated": null
}
```

## 必要条件

- Docker Engine 20.10以降
- Docker Compose v2.0以降
- YouTube Data API v3 のAPIキー（[Google Cloud Console](https://console.cloud.google.com/apis/credentials)で発行）
- Tailscaleアカウント（ホスト側にインストール済みのTailscaleクライアント）

## セットアップ手順

### 1. 環境変数の設定

```bash
# .env.exampleを.envにコピー
cp .env.example .env

# .env.localを作成し、機密値を設定
cat > .env.local << 'EOF'
API_KEY=your-secret-api-key-here
YOUTUBE_API_KEY=AIzaSyXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
EOF
```

#### 環境変数

| ファイル | 変数名 | 説明 | 必須 |
|---|---|---|---|
| `.env` | `LOG_LEVEL` | ログレベル（DEBUG, INFO, WARNING, ERROR） | いいえ |
| `.env.local` | `API_KEY` | FastAPI認証キー（X-API-KEYヘッダーで送信） | はい |
| `.env.local` | `YOUTUBE_API_KEY` | YouTube Data API v3 のAPIキー | はい |

### 2. Tailscaleのセットアップ（ホスト側）

本APIはホスト側（Windows 等）のTailscaleクライアントに依存します。サイドカーコンテナは使用しません。

1. ホストOSに[Tailscaleクライアント](https://tailscale.com/download)をインストール
2. ログインしてTailnetに参加
3. 必要に応じてホスト名・ACLを設定

### 3. コンテナの起動

```bash
docker compose up -d
docker compose logs -f  # ログ確認（オプション）
```

### 4. 動作確認

```bash
# ヘルスチェック
curl http://localhost:10000/

# API呼び出し
curl -X POST http://localhost:10000/api/v1/summary \
  -H "Content-Type: application/json" \
  -H "X-API-KEY: your-api-key" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'
```

## 運用

```bash
docker compose up -d        # 起動
docker compose down         # 停止
docker compose restart api  # API再起動
docker compose logs -f api  # APIログ確認
docker compose build api    # APIイメージ再ビルド
```

ローカル開発（Tailscale不要、Docker外で直接起動）:

```bash
uvicorn main:app --host 0.0.0.0 --port 10000
```

## テスト

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

全テストは外部通信なし（すべてモック）。

## ディレクトリ構造

```
.
├── app/
│   ├── core/
│   │   ├── constants.py       # エラーコード・メッセージ・APIエンドポイント等の定数
│   │   ├── logging_config.py  # ロギング設定
│   │   ├── rate_limiter.py    # クライアント側レート制限（プロセス内グローバル）
│   │   └── security.py        # APIキー認証
│   ├── models/
│   │   └── schemas.py         # リクエスト・レスポンスモデル
│   ├── routers/
│   │   └── summary.py         # POST /api/v1/summary エンドポイント
│   └── services/
│       └── youtube.py         # YouTube Data API v3 + youtube-transcript-api 連携
├── tests/
│   ├── conftest.py            # テストfixture・モック定義
│   ├── test_schemas.py        # モデルテスト
│   ├── test_youtube_service.py # サービス層テスト
│   ├── test_rate_limiter.py   # レートリミッタテスト
│   └── test_api_endpoint.py   # API統合テスト
├── docker/
│   └── Dockerfile.api         # FastAPIイメージ
├── docker-compose.yml         # 本番用（Tailscaleはホスト側）
├── docker-compose.override.yml # 開発用プロファイル
├── main.py
├── requirements.txt           # 本番依存
├── requirements-dev.txt       # テスト依存
└── pytest.ini
```

## 技術スタック

| コンポーネント | 技術 |
|---|---|
| フレームワーク | FastAPI + Uvicorn |
| メタデータ取得 | YouTube Data API v3（主）/ oEmbed API（フォールバック） |
| 字幕取得 | youtube-transcript-api v1.2.x |
| ネットワーク | Tailscale（ホスト側、WireGuard暗号化） |
| 認証 | APIキー（X-API-KEYヘッダー） |
| レート制限 | プロセス内グローバル（連続リクエスト最低60秒間隔） |

## セキュリティ

- `.env` / `.env.local` は `.gitignore` に含まれ、バージョン管理されません
- 本APIは公開せず、Tailnet経由のアクセスのみを想定
- APIキーの比較には `secrets.compare_digest` を使用（タイミング攻撃対策）
- YOUTUBE_API_KEYはログ・エラーレスポンスに出力されないことをテストで検証

## ライセンス

Private
