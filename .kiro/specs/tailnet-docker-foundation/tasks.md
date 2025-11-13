# 実装タスクリスト

## 概要

本タスクリストは、要件定義書（requirements.md）と設計書（design.md）に基づき、Tailnet Docker基盤整備を実装するための具体的なタスクを定義します。各タスクは実装可能な単位に分解され、要件番号を明記しています。

## タスク一覧

### 1. プロジェクト構造の準備

- [ ] 1.1 `docker/`ディレクトリを作成する
  - ルートディレクトリに`docker/`フォルダを作成
  - _要件: 4.1_

- [ ] 1.2 `.env.example`ファイルを作成する
  - 共有可能な環境変数（LOG_LEVEL, TAILSCALE_HOSTNAME）を記載
  - 機密値のプレースホルダーをコメントで記載
  - 各環境変数の用途と設定例をコメントで説明
  - _要件: 3.1, 3.2, 3.3, 3.5_

- [ ] 1.3 `.gitignore`に`.env.local`を追加する
  - 既存の`.env`に加えて`.env.local`を追加
  - _要件: 3.10_

### 2. 環境変数の設定

- [ ] 2.1 `.env`ファイルを作成する
  - `.env.example`をコピーして`.env`を作成
  - LOG_LEVEL, TAILSCALE_HOSTNAMEを設定
  - _要件: 3.4_

- [ ] 2.2 `.env.local`ファイルを作成する
  - API_KEY, TAILSCALE_AUTH_KEY, GEMINI_API_KEYを設定
  - Tailscaleダッシュボードから認証キーを取得（再利用可能オプション推奨）
  - _要件: 3.4, 3.6_

### 3. FastAPI用Dockerfileの作成

- [ ] 3.1 `docker/Dockerfile.api`を作成する
  - `python:3.12-slim`をベースイメージとして使用
  - `requirements.txt`をコピーし、依存パッケージをインストール
  - `main.py`と`app/`ディレクトリをコピー
  - ENTRYPOINTに`uvicorn main:app --host 0.0.0.0 --port 10000`を設定
  - _要件: 4.1, 4.2, 4.3, 4.4, 4.5_

### 4. Tailscale用Dockerfileと起動スクリプトの作成

- [ ] 4.1 `docker/tailscale-entrypoint.sh`を作成する
  - tailscaledをバックグラウンドで起動
  - 既存認証状態の確認ロジックを実装
  - `tailscale status`の結果に基づく条件分岐を実装
  - 接続成功時は`tailscale up`をスキップ
  - 接続失敗時は`tailscale up`を再実行（障害復旧）
  - TAILSCALE_AUTH_KEY未設定時のエラーハンドリング
  - _要件: 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 4.7, 4.8_

- [ ] 4.2 `docker/Dockerfile.tailscale`を作成する
  - `tailscale/tailscale:latest`をベースイメージとして使用
  - `tailscale-entrypoint.sh`をコピーし、実行権限を付与
  - ENTRYPOINTに起動スクリプトを設定
  - _要件: 4.6, 4.7_

### 5. Docker Composeファイルの作成

- [ ] 5.1 `docker-compose.yml`を作成する
  - `tailscale`サービスを定義
    - `docker/Dockerfile.tailscale`をビルド
    - `NET_ADMIN`, `NET_RAW`権限を付与
    - `tailscale-state`, `tailscale-run`ボリュームをマウント
    - `env_file`に`.env`と`.env.local`を指定
    - `ports: ["127.0.0.1:10000:10000"]`を設定（ループバック限定）
    - `restart: unless-stopped`を設定
  - `api`サービスを定義
    - `docker/Dockerfile.api`をビルド
    - `network_mode: "service:tailscale"`を設定
    - `depends_on: [tailscale]`を設定
    - `env_file`に`.env`と`.env.local`を指定
    - `restart: unless-stopped`を設定
  - `tailscale-state`, `tailscale-run`ボリュームを定義
  - `tailnet`ネットワークを定義
  - _要件: 1.1, 1.5, 2.1, 2.2, 2.3, 2.4, 2.12, 2.13, 2.14, 3.5, 3.7, 4.9_

### 6. main.pyの修正

- [ ] 6.1 `main.py`に`.env.local`読み込みを追加する
  - 既存の`.env`読み込み後に`.env.local`を`override=True`で読み込む
  - `.env.local`が存在しない場合でもエラーにならないことを確認
  - _要件: 3.9_

### 7. 既存バッチファイルの非推奨化

- [ ] 7.1 既存バッチファイルに非推奨コメントを追加する
  - `start_api.bat`, `run_fastapi.bat`, `run_funnel.bat`の冒頭に非推奨コメントを追加
  - Docker Composeへの移行を推奨する旨を明記
  - _要件: 5.2_

### 8. ドキュメントの更新

- [ ] 8.1 READMEにセットアップ手順を追加する
  - 環境変数の設定手順（`.env.example`→`.env`、`.env.local`作成）
  - Tailscale認証キーの取得手順
  - Docker Composeによる起動方法
  - 動作確認方法（ヘルスチェック、Tailnet接続確認）
  - _要件: 3.4, 3.6, 5.4_

### 9. 動作確認とテスト

- [ ] 9.1 初回起動テストを実行する
  - `docker compose up -d`でコンテナを起動
  - Tailscaleログで「No existing state found. Authenticating with Tailnet...」を確認
  - Tailscaleログで「Authentication successful.」を確認
  - `curl http://localhost:10000/`でヘルスチェック
  - `docker compose exec tailscale tailscale status`でTailnet接続確認
  - _要件: 6.1, 6.2, 6.3, 6.4_

- [ ] 9.2 再起動テスト（認証状態維持）を実行する
  - `docker compose down`でコンテナを停止
  - `docker compose up -d`で再起動
  - Tailscaleログで「Already connected to Tailnet. Skipping 'tailscale up'.」を確認
  - `curl http://localhost:10000/`でヘルスチェック
  - _要件: 6.1, 6.2, 6.5_

- [ ] 9.3 ボリューム削除後の再起動テストを実行する
  - `docker compose down -v`でコンテナとボリュームを削除
  - `docker compose up -d`で再起動
  - Tailscaleログで「No existing state found. Authenticating with Tailnet...」を確認
  - `curl http://localhost:10000/`でヘルスチェック
  - _要件: 6.1, 6.2_

- [ ] 9.4 コンテナ内ヘルスチェックを実行する
  - `docker compose exec api curl http://127.0.0.1:10000/`を実行
  - 正常なレスポンスを確認
  - _要件: 6.3_

- [ ] 9.5 Tailnet IP経由のアクセステストを実行する
  - Tailnetネットワーク内の別デバイスから`http://<tailscale-ip>:10000/`にアクセス
  - 正常なレスポンスを確認
  - _要件: 2.15, 6.5_

- [ ]* 9.6 パフォーマンステストを実行する
  - FastAPI起動時間が30秒以内であることを確認
  - Tailscale接続時間が60秒以内であることを確認
  - API応答時間が1秒以内であることを確認
  - _要件: 非機能要件（パフォーマンス）_

### 10. 最終確認とクリーンアップ

- [ ] 10.1 ディレクトリ構造が保持されていることを確認する
  - `app/core`, `app/routers`, `app/services`, `app/models`が変更されていないことを確認
  - `main.py`, `requirements.txt`の配置場所が変更されていないことを確認
  - Docker関連ファイルが`docker/`ディレクトリに集約されていることを確認
  - _要件: 7.1, 7.2, 7.3, 7.4_

- [ ] 10.2 セキュリティ要件を確認する
  - `.env`と`.env.local`が`.gitignore`に含まれていることを確認
  - ポートマッピングが`127.0.0.1:10000:10000`（ループバック限定）であることを確認
  - Tailscale_Containerに最小限の権限（NET_ADMIN, NET_RAW）のみが付与されていることを確認
  - _要件: 非機能要件（セキュリティ）_

- [ ] 10.3 環境変数の設定を再確認する
  - `.env`に共有可能な設定値のみが含まれていることを確認
  - `.env.local`に機密値が含まれていることを確認
  - `.env.example`にすべての環境変数がコメント付きで列挙されていることを確認
  - _要件: 3.1, 3.2, 3.3, 3.4, 3.5_

## タスク実行時の注意事項

### 実装順序

タスクは上記の順序で実行することを推奨します。特に以下の依存関係に注意してください：

1. **タスク1-2**: 環境変数とディレクトリ構造の準備（他のタスクの前提条件）
2. **タスク3-4**: Dockerfileと起動スクリプトの作成（タスク5の前提条件）
3. **タスク5**: Docker Composeファイルの作成（タスク9の前提条件）
4. **タスク6**: main.pyの修正（タスク9の前提条件）
5. **タスク7-8**: ドキュメント更新（並行実行可能）
6. **タスク9**: 動作確認とテスト（すべてのタスク完了後）
7. **タスク10**: 最終確認（タスク9完了後）

### テストタスクについて

- タスク9.6（パフォーマンステスト）は`*`マークで任意化されています
- コア機能の動作確認を優先し、パフォーマンステストは必要に応じて実施してください

### エラー発生時の対処

各タスクでエラーが発生した場合は、設計書（design.md）の「エラーハンドリング」セクションを参照してください。主なエラーケースと対処方法が記載されています。

### 既存コードへの影響

- `main.py`の修正（タスク6.1）以外、既存のアプリケーションコードへの変更はありません
- `app/`ディレクトリ配下のファイルは変更不要です
- 既存のバッチファイルは非推奨化されますが、削除はされません（移行期間中の互換性維持）

## 完了条件

すべてのタスク（`*`マークの任意タスクを除く）が完了し、以下の条件を満たすことで、Issue #2のステップ1「基盤整備（Docker Compose + tailscaled）」が完了します：

1. ✅ `docker compose up -d`でFastAPIとTailscaleが起動する
2. ✅ `http://localhost:10000/`でヘルスチェックが成功する
3. ✅ `docker compose exec tailscale tailscale status`でTailnet接続が確認できる
4. ✅ Tailnet IP経由で`http://<tailscale-ip>:10000/`にアクセスできる
5. ✅ コンテナ再起動時に認証状態が維持される
6. ✅ `.env.local`に機密値が分離管理されている
7. ✅ ループバック限定ポートマッピング（`127.0.0.1:10000:10000`）が設定されている
8. ✅ 既存のアプリケーション構造が保持されている

## 次のステップ

本タスクリスト完了後、Issue #2の次のステップに進むことができます：

- **ステップ2**: ネットワーク&セキュリティ設計（Tailnet ACL、APIキー配布、ログ監査）
- **ステップ3**: Gemini連携サービス層（Gemini API統合、Markdown生成）
- **ステップ4**: APIエンドポイント拡張（字幕＋Gemini生成Markdown）
- **ステップ5**: iPhoneショートカット連携仕様
- **ステップ6**: 運用検証（E2E動作確認、課題と改善策）
