# 設計書

## 概要

本設計書は、YouTube Summary APIをDocker Compose環境で常駐化し、Tailnetネットワーク内で運用するための技術的な実装方針を定義します。要件定義書（requirements.md）で定義された7つの要件を満たすため、以下のアーキテクチャを採用します：

- **Docker Compose**: FastAPIとTailscaleの2つのコンテナをオーケストレーション
- **network_mode: "service:tailscale"**: FastAPIコンテナがTailscaleコンテナのネットワーク名前空間を共有
- **条件付きtailscale up実行**: 既存認証状態とtailscale statusの結果に基づく障害復旧ロジック
- **機密値の分離**: `.env.example`（共有値）と`.env.local`（機密値）の分離管理

## アーキテクチャ

### システム構成図

```mermaid
---
title: "Docker Compose構成図"
config:
  theme: neutral
---
flowchart TD
    A["開発者"] -->|"docker compose up -d"| B["Docker Compose"]
    B --> C["Tailscale Container"]
    B --> D["FastAPI Container"]
    
    C -->|"network_mode共有"| D
    C -->|"Tailnet接続"| E["Tailnet"]
    
    F[".env"] -->|"env_file"| C
    F -->|"env_file"| D
    G[".env.local"] -->|"env_file"| C
    G -->|"env_file"| D
    
    H["tailscale-state volume"] -->|"永続化"| C
    I["tailscale-run volume"] -->|"ソケット共有"| C
    
    J["localhost:10000"] -->|"127.0.0.1限定"| C
    K["Tailnet IP:10000"] -->|"Tailnet経由"| C
```

### コンテナ間の関係

1. **Tailscale Container**
   - 役割: tailscaledデーモンを実行し、Tailnetに参加
   - ベースイメージ: `tailscale/tailscale:latest`
   - 権限: `NET_ADMIN`, `NET_RAW`
   - ポート: `127.0.0.1:10000:10000`（ループバック限定）

2. **FastAPI Container**
   - 役割: FastAPIアプリケーションを実行
   - ベースイメージ: `python:3.12-slim`
   - ネットワーク: `network_mode: "service:tailscale"`（Tailscaleコンテナと共有）
   - 依存関係: `depends_on: [tailscale]`

3. **ボリューム**
   - `tailscale-state`: Tailscaleの認証状態を永続化（`/var/lib/tailscale`）
   - `tailscale-run`: Tailscaleソケットを共有（`/var/run/tailscale`）

## コンポーネントとインターフェース

### docker-compose.yml

```yaml
version: '3.8'

services:
  # Tailscale sidecarコンテナ
  tailscale:
    build:
      context: .
      dockerfile: docker/Dockerfile.tailscale
    container_name: youtube-api-tailscale
    hostname: ${TAILSCALE_HOSTNAME:-youtube-api-dev}
    cap_add:
      - NET_ADMIN
      - NET_RAW
    volumes:
      - tailscale-state:/var/lib/tailscale
      - tailscale-run:/var/run/tailscale
    # .envと.env.localの両方を読み込む
    # .env.localが存在しない場合は.envのみで動作（フォールバック）
    env_file:
      - ./.env
      - ./.env.local
    ports:
      # ループバック限定でポート公開（localhost:10000でのヘルスチェック用）
      - "127.0.0.1:10000:10000"
    restart: unless-stopped
    networks:
      - tailnet

  # FastAPIコンテナ
  api:
    build:
      context: .
      dockerfile: docker/Dockerfile.api
    container_name: youtube-api-fastapi
    # Tailscaleコンテナと同じネットワーク名前空間を共有
    network_mode: "service:tailscale"
    depends_on:
      - tailscale
    env_file:
      - ./.env
      - ./.env.local
    restart: unless-stopped
    # network_mode使用時はportsは無効化される（Tailscale側で公開）

volumes:
  tailscale-state:
    driver: local
  tailscale-run:
    driver: local

networks:
  tailnet:
    driver: bridge
```

### docker/Dockerfile.api

```dockerfile
# FastAPI用Dockerfile
FROM python:3.12-slim

# 作業ディレクトリを設定
WORKDIR /app

# 依存パッケージをインストール
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# アプリケーションコードをコピー
COPY main.py .
COPY app/ ./app/

# ポート10000を公開（ドキュメント用、実際はnetwork_mode経由）
EXPOSE 10000

# Uvicornでアプリケーションを起動
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
```

### docker/Dockerfile.tailscale

```dockerfile
# Tailscale用Dockerfile
FROM tailscale/tailscale:latest

# 起動スクリプトをコピー
COPY docker/tailscale-entrypoint.sh /usr/local/bin/tailscale-entrypoint.sh
RUN chmod +x /usr/local/bin/tailscale-entrypoint.sh

# ENTRYPOINTで起動スクリプトを実行
ENTRYPOINT ["/usr/local/bin/tailscale-entrypoint.sh"]
```

### docker/tailscale-entrypoint.sh

```bash
#!/bin/sh
set -e

echo "Starting tailscaled..."
# tailscaledをバックグラウンドで起動
tailscaled --state=/var/lib/tailscale/tailscaled.state --socket=/var/run/tailscale/tailscaled.sock &

# tailscaledの起動を待機
sleep 2

echo "Checking for existing Tailscale state..."
# 既存の認証状態を確認
if [ -f "/var/lib/tailscale/tailscaled.state" ] && [ -s "/var/lib/tailscale/tailscaled.state" ]; then
    echo "Existing state found. Checking connection status..."
    
    # tailscale statusで接続状態を確認
    if tailscale status --socket=/var/run/tailscale/tailscaled.sock > /dev/null 2>&1; then
        echo "Already connected to Tailnet. Skipping 'tailscale up'."
    else
        echo "Connection failed. Re-authenticating with Tailnet..."
        
        # TAILSCALE_AUTH_KEYが設定されているか確認
        if [ -z "$TAILSCALE_AUTH_KEY" ]; then
            echo "ERROR: TAILSCALE_AUTH_KEY is not set and connection failed."
            exit 1
        fi
        
        # tailscale upで再接続
        tailscale up \
            --socket=/var/run/tailscale/tailscaled.sock \
            --authkey="$TAILSCALE_AUTH_KEY" \
            --hostname="$TAILSCALE_HOSTNAME"
        
        echo "Re-authentication successful."
    fi
else
    echo "No existing state found. Authenticating with Tailnet..."
    
    # TAILSCALE_AUTH_KEYが設定されているか確認
    if [ -z "$TAILSCALE_AUTH_KEY" ]; then
        echo "ERROR: TAILSCALE_AUTH_KEY is not set. Cannot authenticate."
        exit 1
    fi
    
    # tailscale upで初回接続
    tailscale up \
        --socket=/var/run/tailscale/tailscaled.sock \
        --authkey="$TAILSCALE_AUTH_KEY" \
        --hostname="$TAILSCALE_HOSTNAME"
    
    echo "Authentication successful."
fi

echo "Tailscale is ready."
echo "Tailnet status:"
tailscale status --socket=/var/run/tailscale/tailscaled.sock

# tailscaledプロセスをフォアグラウンドで維持
wait
```

## データモデル

### 環境変数

#### .env（共有可能な設定値）

```bash
# ログレベル
LOG_LEVEL=INFO

# Tailscaleホスト名（環境ごとに変更）
TAILSCALE_HOSTNAME=youtube-api-dev
```

#### .env.local（機密値）

```bash
# FastAPI認証キー（必須）
API_KEY=your-secret-api-key-here

# Tailscale認証キー（必須）
# Tailscaleダッシュボードから取得
# 推奨: 再利用可能（Reusable）オプションを有効にする
TAILSCALE_AUTH_KEY=tskey-auth-xxxxxxxxxxxxx

# Gemini APIキー（将来用）
GEMINI_API_KEY=your-gemini-api-key-here
```

#### .env.example（テンプレート）

```bash
# ログレベル
# 設定例: DEBUG, INFO, WARNING, ERROR
LOG_LEVEL=INFO

# Tailscaleホスト名
# Tailnet内でこのコンテナを識別する名前
# 環境ごとに変更してください（例: youtube-api-dev, youtube-api-prod）
TAILSCALE_HOSTNAME=youtube-api-dev

# ===== 以下の機密値は .env.local で設定してください =====

# FastAPI認証キー（必須）
# .env.local に設定: API_KEY=your-secret-api-key-here

# Tailscale認証キー（必須）
# Tailscaleダッシュボードから取得してください
# 推奨: 再利用可能（Reusable）オプションを有効にする
# .env.local に設定: TAILSCALE_AUTH_KEY=tskey-auth-xxxxxxxxxxxxx

# Gemini APIキー（将来用）
# .env.local に設定: GEMINI_API_KEY=your-gemini-api-key-here
```

### ボリューム構成

| ボリューム名 | マウント先 | 用途 | 永続化 |
|-------------|-----------|------|--------|
| `tailscale-state` | `/var/lib/tailscale` | Tailscale認証状態 | ✅ |
| `tailscale-run` | `/var/run/tailscale` | Tailscaleソケット | ❌（コンテナ間共有のみ） |

### ネットワーク構成

```mermaid
---
title: "ネットワーク構成"
config:
  theme: neutral
---
flowchart LR
    A["ホスト<br>127.0.0.1:10000"] -->|"ループバック限定"| B["Tailscale Container<br>10000番ポート"]
    B -->|"network_mode共有"| C["FastAPI Container<br>0.0.0.0:10000"]
    D["Tailnet IP<br>100.x.x.x:10000"] -->|"Tailnet経由"| B
    B -->|"同じネットワーク<br>名前空間"| C
```

**ポイント:**
- `127.0.0.1:10000:10000`: ホストのループバックインターフェースのみに公開（ヘルスチェック用）
- Tailnet IP経由のアクセスは、Tailscaleコンテナ→FastAPIコンテナへ直接届く（network_mode共有）
- ホスト外部からの直接アクセスは不可（Issue #2の方針に準拠）

## エラーハンドリング

### 障害復旧ロジック

#### ケース1: 初回起動（認証状態なし）

```
1. tailscaledを起動
2. /var/lib/tailscale/tailscaled.stateが存在しない
3. TAILSCALE_AUTH_KEYを確認
   - 未設定 → エラー終了
   - 設定済み → tailscale upを実行
4. Tailnetに接続成功
```

#### ケース2: 再起動（認証状態あり・接続成功）

```
1. tailscaledを起動
2. /var/lib/tailscale/tailscaled.stateが存在
3. tailscale statusを実行
   - 終了コード0 → 接続済み → tailscale upをスキップ
4. Tailnet接続を維持
```

#### ケース3: 再起動（認証状態あり・接続失敗）

```
1. tailscaledを起動
2. /var/lib/tailscale/tailscaled.stateが存在
3. tailscale statusを実行
   - 非0終了コード → 未接続
4. TAILSCALE_AUTH_KEYを確認
   - 未設定 → エラー終了
   - 設定済み → tailscale upを再実行
5. Tailnetに再接続成功（ACL改訂・キー失効から自動復旧）
```

### エラーケースと対処

| エラーケース | 原因 | 対処方法 |
|-------------|------|---------|
| `TAILSCALE_AUTH_KEY is not set` | 環境変数未設定 | `.env.local`に`TAILSCALE_AUTH_KEY`を設定 |
| `tailscale up`失敗（初回） | Auth Key無効 | Tailscaleダッシュボードで新しいキーを生成 |
| `tailscale status`失敗（再起動時） | ACL改訂・キー失効 | 自動的に`tailscale up`を再実行（スクリプトで対応） |
| `docker compose up`失敗 | ポート競合 | ホストの10000番ポートを使用中のプロセスを停止 |
| FastAPI起動失敗 | `API_KEY`未設定 | `.env.local`に`API_KEY`を設定 |

## テスト戦略

### ヘルスチェック

#### 1. ローカルホストからのヘルスチェック

```bash
# ホストから実行
curl http://localhost:10000/

# 期待される応答
{"message": "Welcome to the YouTube Summary API!"}
```

#### 2. コンテナ内からのヘルスチェック

```bash
# FastAPIコンテナ内から実行
docker compose exec api curl http://127.0.0.1:10000/

# 期待される応答
{"message": "Welcome to the YouTube Summary API!"}
```

#### 3. Tailnet接続状態の確認

```bash
# Tailscaleコンテナ内から実行
docker compose exec tailscale tailscale status

# 期待される出力例
# 100.x.x.x   youtube-api-dev      user@       linux   -
# ...
```

#### 4. Tailnet IP経由のアクセステスト

```bash
# Tailnetネットワーク内の別デバイスから実行
# （Tailscale IPは `docker compose exec tailscale tailscale status` で確認）
curl http://100.x.x.x:10000/

# 期待される応答
{"message": "Welcome to the YouTube Summary API!"}
```

### 統合テストシナリオ

#### シナリオ1: 初回起動

```bash
# 1. 環境変数を設定
cp .env.example .env
# .env.local を作成し、API_KEY と TAILSCALE_AUTH_KEY を設定

# 2. コンテナを起動
docker compose up -d

# 3. ログを確認
docker compose logs tailscale
# 期待: "No existing state found. Authenticating with Tailnet..."
# 期待: "Authentication successful."

# 4. ヘルスチェック
curl http://localhost:10000/
# 期待: {"message": "Welcome to the YouTube Summary API!"}

# 5. Tailnet接続確認
docker compose exec tailscale tailscale status
# 期待: youtube-api-dev が表示される
```

#### シナリオ2: 再起動（認証状態維持）

```bash
# 1. コンテナを停止
docker compose down

# 2. コンテナを再起動
docker compose up -d

# 3. ログを確認
docker compose logs tailscale
# 期待: "Existing state found. Checking connection status..."
# 期待: "Already connected to Tailnet. Skipping 'tailscale up'."

# 4. ヘルスチェック
curl http://localhost:10000/
# 期待: {"message": "Welcome to the YouTube Summary API!"}
```

#### シナリオ3: ボリューム削除後の再起動

```bash
# 1. コンテナとボリュームを削除
docker compose down -v

# 2. コンテナを再起動
docker compose up -d

# 3. ログを確認
docker compose logs tailscale
# 期待: "No existing state found. Authenticating with Tailnet..."
# 期待: "Authentication successful."

# 4. ヘルスチェック
curl http://localhost:10000/
# 期待: {"message": "Welcome to the YouTube Summary API!"}
```

### パフォーマンステスト

| 項目 | 目標値 | 測定方法 |
|------|--------|---------|
| FastAPI起動時間 | 30秒以内 | `docker compose logs api` でタイムスタンプ確認 |
| Tailscale接続時間 | 60秒以内 | `docker compose logs tailscale` でタイムスタンプ確認 |
| API応答時間 | 1秒以内 | `curl -w "@curl-format.txt" http://localhost:10000/` |

## 実装上の注意事項

### 1. main.pyの修正（重要）

現在の`main.py:9-17`は`.env`のみを読み込んでいますが、`.env.local`も読み込むように修正が必要です。この修正により、ローカルでUvicorn単体実行した際にも`.env.local`の機密値が読み込まれ、Docker Compose実行時と同じ挙動になります。

**修正前（main.py:9-17）:**
```python
from pathlib import Path
from dotenv import load_dotenv

env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)
```

**修正後:**
```python
from pathlib import Path
from dotenv import load_dotenv

# .envを読み込み（共有可能な設定値）
env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

# .env.localを読み込み（機密値、存在する場合は上書き）
# override=Trueにより、.envと.env.localで同じキーがある場合は.env.localの値を優先
env_local_path = Path('.') / '.env.local'
load_dotenv(dotenv_path=env_local_path, override=True)
```

**注意:**
- `.env.local`が存在しない場合でもエラーにならない（`load_dotenv`は存在しないファイルを無視）
- Docker Compose実行時は`env_file`で両方のファイルを読み込むため、この修正と整合性が取れる
- ローカル開発時（Uvicorn単体実行）でも同じ環境変数が読み込まれる

### 2. .gitignoreの更新

`.env.local`を`.gitignore`に追加する必要があります。

**追加内容:**
```
# Environment variables
.env
.env.local
```

### 3. 既存バッチファイルの非推奨化

`start_api.bat`, `run_fastapi.bat`, `run_funnel.bat`の冒頭に以下のコメントを追加：

```batch
@echo off
REM =============================================
REM 【非推奨】Docker Composeへの移行後は使用しない予定
REM 互換目的で残置しています
REM 推奨: docker compose up -d を使用してください
REM =============================================
```

### 4. READMEの更新

以下の内容をREADMEに追加：

```markdown
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

### 2. Tailscale認証キーの取得

1. [Tailscaleダッシュボード](https://login.tailscale.com/admin/settings/keys)にアクセス
2. 「Generate auth key」をクリック
3. 「Reusable」オプションを有効にする（推奨）
4. 生成されたキーを`.env.local`の`TAILSCALE_AUTH_KEY`に設定

### 3. コンテナの起動

```bash
docker compose up -d
```

### 4. 動作確認

```bash
# ローカルホストからのヘルスチェック
curl http://localhost:10000/

# Tailnet接続状態の確認
docker compose exec tailscale tailscale status
```
```

## 設計上の決定事項

### 1. network_mode: "service:tailscale"の採用

**理由:**
- FastAPIコンテナがTailscaleコンテナと同じネットワーク名前空間を共有
- Tailnet IPへのinboundトラフィックが直接FastAPIに届く
- 追加のプロキシ設定が不要でシンプル

**トレードオフ:**
- FastAPIコンテナの`ports`設定が無効化される
- Tailscaleコンテナ側でポートマッピングを行う必要がある

### 2. ループバック限定ポートマッピング

**理由:**
- `127.0.0.1:10000:10000`でホストのループバックインターフェースのみに公開
- ホスト外部からの直接アクセスを防ぎ、Issue #2の「Tailnet外公開はやめる」方針に準拠
- localhost:10000でのヘルスチェックとTailnet IP経由のアクセスの両方が可能

**トレードオフ:**
- ホスト外部からの直接アクセスは不可（意図的な制限）

### 3. 条件付きtailscale up実行

**理由:**
- 既存認証状態とtailscale statusの結果に基づく条件分岐
- single-use/reusableの両方のAuth Keyに対応
- ACL改訂、キー失効時の自動復旧を実現

**トレードオフ:**
- 起動スクリプトが複雑化（約60行）
- 初回起動時に若干の遅延（2秒のsleep）

### 4. 機密値の分離

**理由:**
- `.env.example`（共有値）と`.env.local`（機密値）の分離
- CI/CDでのSecrets Manager連携が容易
- 機密情報の漏洩リスクを最小化

**トレードオフ:**
- 環境構築時に2つのファイルを管理する必要がある
- `.env.local`が存在しない環境では`.env`のみで動作するフォールバックが必要

## 参照ドキュメント

- 要件定義書: `.kiro/specs/tailnet-docker-foundation/requirements.md`
- Issue #2: Tailnet内常駐化とGemini要約導入の実装ロードマップ
- Docker Compose公式ドキュメント: https://docs.docker.com/compose/
- Tailscale公式ドキュメント: https://tailscale.com/kb/
