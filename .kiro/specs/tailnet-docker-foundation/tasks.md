# Implementation Plan

- [x] 1. プロジェクト構造の準備
  - [x] 1.1 `docker/`ディレクトリを作成する
    - ルートディレクトリに`docker/`フォルダを作成
    - _要件: 4.1_
  - [x] 1.2 `.env.example`ファイルを作成する
    - 共有可能な環境変数（LOG_LEVEL, TAILSCALE_HOSTNAME）を記載
    - 機密値のプレースホルダーをコメントで記載
    - _要件: 3.1, 3.2, 3.3, 3.5_
  - [x] 1.3 `.gitignore`に`.env.local`を追加する
    - 既存の`.env`に加えて`.env.local`を追加
    - _要件: 3.10_
  - [x] 1.4 `.dockerignore`ファイルを作成する
    - `.venv`, `.git`, `docs/`, `__pycache__`, `*.md`（README.mdを除く）等を除外
    - _要件: 4.10_

- [x] 2. 環境変数の設定
  - [x] 2.1 `.env`ファイルを作成する
    - `.env.example`をコピーして`.env`を作成
    - _要件: 3.4_
  - [x] 2.2 `.env.local`ファイルを作成する
    - API_KEY, TAILSCALE_AUTH_KEY, GEMINI_API_KEYを設定
    - _要件: 3.4 3.6_

- [x] 3. FastAPI用Dockerfileの作成
  - [x] 3.1 `docker/Dockerfile.api`を作成する
    - `python:3.12-slim`をベースイメージとして使用
    - `requirements.txt`をコピーし、依存パッケージをインストール
    - `main.py`と`app/`ディレクトリをコピー
    - _要件: 4.2, 4.3, 4.4, 4.5_

- [x] 4. Tailscale用Dockerfileと起動スクリプトの作成
  - [x] 4.1 `docker/tailscale-entrypoint.sh`を作成する
    - tailscaledをバックグラウンドで起動
    - 既存認証状態の確認ロジックを実装
    - `tailscale status`の結果に基づく条件分岐を実装
    - _要件: 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 4.7, 4.8_
  - [x] 4.2 `docker/Dockerfile.tailscale`を作成する
    - `tailscale/tailscale:latest`をベースイメージとして使用
    - `tailscale-entrypoint.sh`をコピーし、実行権限を付与
    - _要件: 4.6, 4.7_

- [x] 5. Docker Composeファイルの作成
  - [x] 5.1 `docker-compose.yml`を作成する
    - `tailscale`サービスと`api`サービスを定義
    - `network_mode: "service:tailscale"`を設定
    - `ports: ["127.0.0.1:10000:10000"]`を設定
    - _要件: 1.1, 1.5, 2.1, 2.2, 2.3, 2.4, 2.12, 2.13, 2.14, 3.7, 4.9_

- [x] 6. main.pyの修正
  - [x] 6.1 `main.py`に`.env.local`読み込みを追加する
    - 既存の`.env`読み込み後に`.env.local`を`override=True`で読み込む
    - _要件: 3.9_

- [x] 7. 既存バッチファイルの非推奨化
  - [x] 7.1 既存バッチファイルに非推奨コメントを追加する
    - `start_api.bat`, `run_fastapi.bat`, `run_funnel.bat`の冒頭に非推奨コメントを追加
    - _要件: 5.2_

- [x] 8. ドキュメントの更新
  - [x] 8.1 READMEにセットアップ手順を追加する
    - 環境変数の設定手順、Docker Composeによる起動方法を記載
    - _要件: 3.6, 5.4_

- [x] 9. Checkpoint - すべてのファイルが作成されていることを確認
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. 動作確認とテスト
  - [ ] 10.1 初回起動テストを実行する
    - `docker compose up -d`でコンテナを起動
    - `curl http://localhost:10000/`でヘルスチェック
    - _要件: 6.1, 6.2, 6.3, 6.4_
  - [ ] 10.2 再起動テスト（認証状態維持）を実行する
    - `docker compose down`→`docker compose up -d`で再起動
    - _要件: 6.1, 6.2, 6.5_
  - [ ] 10.3 ボリューム削除後の再起動テストを実行する
    - `docker compose down -v`→`docker compose up -d`で再起動
    - _要件: 6.1, 6.2_
  - [ ] 10.4 コンテナ内ヘルスチェックを実行する
    - `docker compose exec api curl http://127.0.0.1:10000/`を実行
    - _要件: 6.3_
  - [ ] 10.5 Tailnet IP経由のアクセステストを実行する
    - Tailnetネットワーク内の別デバイスからアクセス
    - _要件: 2.15, 6.5_
  - [ ]* 10.6 パフォーマンステストを実行する
    - FastAPI起動時間が30秒以内、Tailscale接続時間が60秒以内であることを確認
    - _要件: 非機能要件（パフォーマンス）_

- [ ] 11. 端末側（iPhoneショートカット）のURL変更
  - [ ] 11.1 Tailscale IPアドレスを確認する
    - `docker compose exec tailscale tailscale ip -4`でIPを取得
    - または`docker compose exec tailscale tailscale status`で確認
  - [ ] 11.2 iPhoneショートカットのURLを変更する
    - 変更前: `https://endoke-pc.tailee48cd.ts.net/api/v1/summary`
    - 変更後: `http://<Tailscale IP>:10000/api/v1/summary`
    - プロトコルをHTTPSからHTTPに変更（Tailnet内はWireGuardで暗号化済み）
    - ポート10000を明示的に指定
  - [ ] 11.3 iPhoneでTailscale VPNがオンになっていることを確認する
    - Tailnetに接続していないとAPIにアクセスできない

- [ ] 12. 最終確認とクリーンアップ
  - [ ] 12.1 ディレクトリ構造が保持されていることを確認する
    - `app/core`, `app/routers`, `app/services`, `app/models`が変更されていないことを確認
    - _要件: 7.1, 7.2, 7.3, 7.4_
  - [ ] 12.2 セキュリティ要件を確認する
    - `.env`と`.env.local`が`.gitignore`に含まれていることを確認
    - ポートマッピングが`127.0.0.1:10000:10000`であることを確認
    - _要件: 非機能要件（セキュリティ）_
  - [ ] 12.3 環境変数の設定を再確認する
    - `.env`に共有可能な設定値のみが含まれていることを確認
    - _要件: 3.1, 3.2, 3.3, 3.4, 3.5_

- [ ] 13. Final Checkpoint - すべてのテストが通ることを確認
  - Ensure all tests pass, ask the user if questions arise.
