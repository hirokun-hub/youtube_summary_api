# YouTube Summary API

YouTube動画の字幕を取得し、要約を生成するAPIサーバーです。Docker Compose環境でTailnetネットワーク内に常駐化して運用します。

## 機能

- YouTube動画の字幕取得
- Gemini APIによる要約生成（将来実装予定）
- Tailnetネットワーク経由のセキュアなアクセス

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
GEMINI_API_KEY=your-gemini-api-key-here
EOF
```

#### 環境変数の説明

| ファイル | 変数名 | 説明 | 必須 |
|---------|--------|------|------|
| `.env` | `LOG_LEVEL` | ログレベル（DEBUG, INFO, WARNING, ERROR） | いいえ |
| `.env` | `TAILSCALE_HOSTNAME` | Tailnet内でのホスト名 | はい |
| `.env.local` | `API_KEY` | FastAPI認証キー | はい |
| `.env.local` | `TAILSCALE_AUTH_KEY` | Tailscale認証キー | はい |
| `.env.local` | `GEMINI_API_KEY` | Gemini APIキー（将来用） | いいえ |

### 2. Tailscale認証キーの取得

1. [Tailscaleダッシュボード](https://login.tailscale.com/admin/settings/keys)にアクセス
2. 「Generate auth key」をクリック
3. **「Reusable」オプションを有効にする（推奨）**
   - 再利用可能なキーを使用すると、コンテナ再起動時も同じキーを使用可能
   - single-use（一回限り）のキーを使用する場合、ボリューム削除後は新しいキーが必要
4. 生成されたキーを`.env.local`の`TAILSCALE_AUTH_KEY`に設定

### 3. コンテナの起動

```bash
# コンテナをバックグラウンドで起動
docker compose up -d

# ログを確認（オプション）
docker compose logs -f
```

### 4. 動作確認

```bash
# ローカルホストからのヘルスチェック
curl http://localhost:10000/
# 期待される応答: {"message": "Welcome to the YouTube Summary API!"}

# Tailnet接続状態の確認
docker compose exec tailscale tailscale status

# Tailscale IPアドレスの確認
docker compose exec tailscale tailscale ip -4
```

## 起動方法

### 推奨: Docker Compose（推奨）

```bash
# 起動
docker compose up -d

# 停止
docker compose down

# 停止（ボリュームも削除）
docker compose down -v

# 再起動
docker compose restart

# ログ確認
docker compose logs -f api        # FastAPIのログ
docker compose logs -f tailscale  # Tailscaleのログ
```

### 代替: Windowsバッチファイル（非推奨）

以下のバッチファイルは互換目的で残置されていますが、Docker Composeへの移行後は使用しないでください。

- `start_api.bat`
- `run_fastapi.bat`
- `run_funnel.bat`

## アクセス方法

### ローカルホストから

```bash
curl http://localhost:10000/
curl http://localhost:10000/api/v1/summary?video_id=VIDEO_ID
```

### Tailnetネットワーク内から

Tailnetに接続した別デバイスからアクセスする場合：

```bash
# Tailscale IPを確認
docker compose exec tailscale tailscale ip -4
# 例: 100.x.x.x

# Tailnet経由でアクセス
curl http://100.x.x.x:10000/
curl http://100.x.x.x:10000/api/v1/summary?video_id=VIDEO_ID
```

**注意**: Tailnet経由のアクセスにはHTTPSは不要です（WireGuardで暗号化済み）。

## トラブルシューティング

### Tailscale接続に失敗する

```bash
# ログを確認
docker compose logs tailscale

# 認証状態をリセットして再接続
docker compose down -v
docker compose up -d
```

### FastAPIが起動しない

```bash
# ログを確認
docker compose logs api

# API_KEYが設定されているか確認
grep API_KEY .env.local
```

### ポート10000が使用中

```bash
# 使用中のプロセスを確認
lsof -i :10000

# プロセスを停止してから再起動
docker compose up -d
```

## ディレクトリ構造

```
.
├── app/
│   ├── core/           # コア機能（ログ、セキュリティ）
│   ├── models/         # データモデル
│   ├── routers/        # APIルーター
│   └── services/       # ビジネスロジック
├── docker/
│   ├── Dockerfile.api          # FastAPI用Dockerfile
│   ├── Dockerfile.tailscale    # Tailscale用Dockerfile
│   └── tailscale-entrypoint.sh # Tailscale起動スクリプト
├── docs/               # ドキュメント
├── .env                # 共有可能な環境変数
├── .env.local          # 機密値（Git管理外）
├── .env.example        # 環境変数テンプレート
├── docker-compose.yml  # Docker Compose設定
├── main.py             # FastAPIエントリーポイント
└── requirements.txt    # Python依存パッケージ
```

## セキュリティ

- `.env`と`.env.local`は`.gitignore`に含まれており、バージョン管理されません
- ポートマッピングは`127.0.0.1:10000:10000`に限定され、ホスト外部からの直接アクセスは不可
- Tailnet経由のアクセスのみを許可し、外部公開はしません

## ライセンス

Private
