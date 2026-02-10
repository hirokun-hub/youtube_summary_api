# YouTube Summary API

YouTube動画のメタデータと字幕（文字起こし）を取得するAPIサーバーです。Docker Compose環境でTailnetネットワーク内に常駐化して運用します。

## 機能

- YouTube動画のメタデータ一括取得（yt-dlp）
- 字幕取得（youtube-transcript-api）
- 7種のエラーコードによる障害原因の特定
- Tailnetネットワーク経由のセキュアなアクセス
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

#### エラーコード

| error_code | 意味 |
|---|---|
| `null` | エラーなし（success=true） |
| `INVALID_URL` | YouTube URLとして認識できない |
| `VIDEO_NOT_FOUND` | 動画が存在しない・非公開・削除済み |
| `TRANSCRIPT_NOT_FOUND` | 指定言語の字幕が見つからない |
| `TRANSCRIPT_DISABLED` | 字幕機能が無効化されている |
| `RATE_LIMITED` | リクエスト過多・IPブロック |
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
- Tailscaleアカウント

## セットアップ手順

### 1. 環境変数の設定

```bash
# .env.exampleを.envにコピー
cp .env.example .env

# .env.localを作成し、機密値を設定
cat > .env.local << EOF
API_KEY=your-secret-api-key-here
TAILSCALE_AUTH_KEY=tskey-auth-xxxxxxxxxxxxx
EOF
```

#### 環境変数の説明

| ファイル | 変数名 | 説明 | 必須 |
|---|---|---|---|
| `.env` | `LOG_LEVEL` | ログレベル（DEBUG, INFO, WARNING, ERROR） | いいえ |
| `.env` | `TAILSCALE_HOSTNAME` | Tailnet内でのホスト名 | はい |
| `.env.local` | `API_KEY` | FastAPI認証キー（X-API-KEYヘッダーで送信） | はい |
| `.env.local` | `TAILSCALE_AUTH_KEY` | Tailscale認証キー | はい |

### 2. Tailscale認証キーの取得

1. [Tailscaleダッシュボード](https://login.tailscale.com/admin/settings/keys)にアクセス
2. 「Generate auth key」をクリック
3. **「Reusable」オプションを有効にする（推奨）**
4. 生成されたキーを`.env.local`の`TAILSCALE_AUTH_KEY`に設定

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
docker compose down          # 停止
docker compose restart api   # API再起動（Tailscale維持）
docker compose logs -f api   # APIログ確認
docker compose build api     # APIイメージ再ビルド
```

## テスト

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

全38テスト（モデル6件 + サービス層17件 + API統合7件 + パラメタライズ8件）。外部通信なし（すべてモック）。

## ディレクトリ構造

```
.
├── app/
│   ├── core/
│   │   ├── constants.py       # エラーコード・メッセージ・キーマッピング定数
│   │   ├── logging_config.py  # ロギング設定
│   │   └── security.py        # APIキー認証
│   ├── models/
│   │   └── schemas.py         # リクエスト・レスポンスモデル（21フィールド）
│   ├── routers/
│   │   └── summary.py         # POST /api/v1/summary エンドポイント
│   └── services/
│       └── youtube.py         # yt-dlp + youtube-transcript-api連携
├── tests/
│   ├── conftest.py            # テストfixture・モック定義
│   ├── test_schemas.py        # モデルテスト（S-1〜S-6）
│   ├── test_youtube_service.py # サービス層テスト（Y-1〜Y-17）
│   └── test_api_endpoint.py   # API統合テスト（E-1〜E-7）
├── docker/
│   ├── Dockerfile.api         # FastAPI + Deno（yt-dlp用）
│   ├── Dockerfile.tailscale   # Tailscaleサイドカー
│   └── tailscale-entrypoint.sh
├── docker-compose.yml
├── main.py
├── requirements.txt           # 本番依存
├── requirements-dev.txt       # テスト依存
└── pytest.ini
```

## 技術スタック

| コンポーネント | 技術 |
|---|---|
| フレームワーク | FastAPI + Uvicorn |
| メタデータ取得 | yt-dlp（主）/ oEmbed API（フォールバック） |
| 字幕取得 | youtube-transcript-api v1.2.x |
| JSランタイム | Deno（yt-dlpのYouTube JS challenge対応） |
| ネットワーク | Tailscale（WireGuard暗号化） |
| 認証 | APIキー（X-API-KEYヘッダー） |

## セキュリティ

- `.env.local`は`.gitignore`に含まれ、バージョン管理されません
- ポートマッピングは`127.0.0.1:10000:10000`に限定（ホスト外部からの直接アクセス不可）
- Tailnet経由のアクセスのみを許可し、外部公開はしません
- APIキーの比較には`secrets.compare_digest`を使用（タイミング攻撃対策）

## ライセンス

Private
