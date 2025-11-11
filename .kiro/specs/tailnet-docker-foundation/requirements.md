# 要件定義書

## 概要

本仕様書は、YouTube Summary APIをDocker Compose環境で常駐化し、Tailnetネットワーク内で運用するための基盤整備を定義します。現状のWindowsバッチ依存の手動起動から、OS非依存のコンテナ常駐化へ移行し、設定管理を一元化することで、再現性と保守性を向上させます。

本ステップは、Issue #2「Tailnet内常駐化とGemini要約導入の実装ロードマップ」のステップ1「基盤整備（Docker Compose + tailscaled）」に対応します。

## 用語集

- **System**: YouTube Summary API全体を指すシステム名
- **FastAPI_Container**: FastAPIアプリケーションを実行するDockerコンテナ
- **Tailscale_Container**: tailscaledデーモンを実行するDockerコンテナ（sidecar）
- **Docker_Compose**: 複数のDockerコンテナを定義・管理するオーケストレーションツール
- **Tailnet**: Tailscaleが構築するプライベートVPNネットワーク
- **env_file**: 環境変数を定義する`.env`ファイル
- **Tailscale_Socket**: TailscaleデーモンとAPIコンテナ間の通信に使用するUnixソケット（`/var/run/tailscale.sock`）
- **network_mode**: Dockerコンテナのネットワーク名前空間を指定する設定。`service:tailscale`を指定することで、FastAPI_ContainerがTailscale_Containerと同じネットワークスタックを共有する
- **TAILSCALE_AUTH_KEY**: Tailnetに参加するための認証キー。Tailscaleダッシュボードから取得
- **TAILSCALE_HOSTNAME**: Tailnet内でコンテナを識別するホスト名
- **MVP**: Minimum Viable Product（最小実行可能製品）

## 要件

### 要件1: Docker Compose環境の構築

**ユーザーストーリー:** 開発者として、OS非依存の環境でFastAPIを起動したい。そうすることで、Windows/Mac/Linuxのどの環境でも同じ手順で開発・運用できるようにしたい。

#### 受入基準

1. WHEN 開発者が`docker compose up -d`コマンドを実行したとき、THE System SHALL FastAPI_Containerを起動し、ポート10000番でHTTPリクエストを待機する
2. WHEN FastAPI_Containerが起動したとき、THE System SHALL `main.py`の既存実装（uvicorn起動）を変更せずに利用する
3. WHEN FastAPI_Containerが起動したとき、THE System SHALL `requirements.txt`に記載されたすべての依存パッケージをインストール済みの状態で実行する
4. WHEN 開発者が`docker compose down`コマンドを実行したとき、THE System SHALL すべてのコンテナを停止し、リソースをクリーンアップする
5. WHERE Docker_Composeが設定されている環境において、THE System SHALL `restart: unless-stopped`ポリシーによりコンテナ異常終了時に自動再起動する

### 要件2: Tailscale常駐化とネットワーク統合

**ユーザーストーリー:** 開発者として、Tailnetネットワーク内でAPIを常駐させたい。そうすることで、外部公開せずにプライベートネットワーク経由で安全にアクセスできるようにしたい。

#### 受入基準

1. WHEN 開発者が`docker compose up -d`コマンドを実行したとき、THE System SHALL Tailscale_Containerを起動し、tailscaledデーモンを常駐させる
2. WHEN Tailscale_Containerが起動したとき、THE System SHALL NET_ADMINおよびNET_RAW権限を付与し、ネットワークインターフェースの操作を可能にする
3. WHEN Tailscale_Containerが起動したとき、THE System SHALL `/var/lib/tailscale`ディレクトリをDockerボリュームとして永続化し、認証状態を保持する
4. WHEN Tailscale_Containerが起動したとき、THE System SHALL Tailscale_Socketを作成し、FastAPI_Containerと共有する
5. WHEN Tailscale_Containerが起動したとき、THE System SHALL `/var/lib/tailscale`ボリューム内に既存の認証状態が存在するか確認する
6. IF 既存の認証状態が存在しない場合、THEN THE System SHALL `tailscale up --authkey $TAILSCALE_AUTH_KEY --hostname $TAILSCALE_HOSTNAME`コマンドを実行し、Tailnetに参加する
7. IF 既存の認証状態が存在する場合、THEN THE System SHALL `tailscale status`コマンドで接続状態を確認する
8. IF `tailscale status`が成功（終了コード0）かつTailnetに接続済みの場合、THEN THE System SHALL `tailscale up`をスキップする
9. IF `tailscale status`が失敗（非0終了コード）または未接続の場合、THEN THE System SHALL `tailscale up --authkey $TAILSCALE_AUTH_KEY --hostname $TAILSCALE_HOSTNAME`コマンドを実行し、Tailnetに再参加する
10. IF TAILSCALE_AUTH_KEYが環境変数に設定されておらず、かつ既存の認証状態が存在しない場合、THEN THE System SHALL Tailscale_Containerの起動を失敗させ、エラーログを出力する
11. WHEN Tailscale_Containerが正常に起動したとき、THE System SHALL `tailscale status`コマンドでTailnet接続状態を確認できる状態にする
12. WHEN FastAPI_Containerが起動したとき、THE System SHALL Tailscale_Containerに依存関係（depends_on）を設定し、Tailscale起動後にFastAPIを起動する
13. WHEN FastAPI_Containerが起動したとき、THE System SHALL `network_mode: "service:tailscale"`設定により、Tailscale_Containerと同じネットワーク名前空間を共有する
14. WHEN Docker_Composeが起動するとき、THE System SHALL Tailscale_Containerに`ports: ["127.0.0.1:10000:10000"]`を設定し、ホストのループバックインターフェース（localhost）のみからFastAPIへアクセス可能にする
15. WHEN 開発者がTailnetネットワーク内の別デバイスからTailscale IPアドレス経由でAPIにアクセスしたとき、THE System SHALL HTTPリクエストを正常に処理し、レスポンスを返す

### 要件3: 設定の一元管理

**ユーザーストーリー:** 開発者として、環境変数を一箇所で管理したい。そうすることで、設定変更時の手間を減らし、設定ミスを防ぎたい。

#### 受入基準

1. THE System SHALL `.env.example`ファイルをルートディレクトリに配置し、すべての必須環境変数をコメント付きで列挙する
2. THE System SHALL `.env.example`に以下の環境変数を含める: API_KEY, LOG_LEVEL, TAILSCALE_AUTH_KEY, TAILSCALE_HOSTNAME, GEMINI_API_KEY（将来用）
3. THE System SHALL `.env.example`の各環境変数に用途と設定例をコメントで説明する
4. WHEN 開発者が新規環境を構築するとき、THE System SHALL `.env.example`をコピーして`.env`を作成する手順をREADMEに記載する
5. WHEN Docker_Composeが起動するとき、THE System SHALL `env_file: .env`設定により`.env`ファイルを読み込み、すべてのコンテナに環境変数を提供する
6. WHEN Docker_Composeが起動するとき、THE System SHALL Tailscale関連環境変数（TAILSCALE_AUTH_KEY, TAILSCALE_HOSTNAME等）をTailscale_Containerの`environment`セクションに渡す
7. WHEN FastAPI_Containerが起動するとき、THE System SHALL `main.py`の`load_dotenv()`により`.env`ファイルを読み込み、既存の環境変数取得ロジック（`os.getenv`）を変更せずに利用する
8. THE System SHALL `.gitignore`に`.env`を含め、機密情報をバージョン管理から除外する

### 要件4: Dockerファイルの構成

**ユーザーストーリー:** 開発者として、FastAPIとTailscaleのDockerイメージを個別に管理したい。そうすることで、各コンポーネントの更新や設定変更を独立して行えるようにしたい。

#### 受入基準

1. THE System SHALL `docker/`ディレクトリをルートに作成し、Dockerfileを集約する
2. THE System SHALL `docker/Dockerfile.api`を作成し、`python:3.12-slim`をベースイメージとして使用する
3. WHEN `docker/Dockerfile.api`がビルドされるとき、THE System SHALL `requirements.txt`をコピーし、すべての依存パッケージをインストールする
4. WHEN `docker/Dockerfile.api`がビルドされるとき、THE System SHALL アプリケーションコード（`main.py`, `app/`ディレクトリ）をコンテナにコピーする
5. WHEN `docker/Dockerfile.api`がビルドされるとき、THE System SHALL ENTRYPOINTまたはCMDに`uvicorn main:app --host 0.0.0.0 --port 10000`を設定する
6. THE System SHALL `docker/Dockerfile.tailscale`を作成し、`tailscale/tailscale`公式イメージをベースとして使用する
7. WHEN `docker/Dockerfile.tailscale`がビルドされるとき、THE System SHALL ENTRYPOINTまたはCMDに`tailscaled`の起動と`tailscale up`の実行を含むスクリプトを設定する
8. WHEN `docker/Dockerfile.tailscale`のコンテナが起動するとき、THE System SHALL 環境変数`TAILSCALE_AUTH_KEY`と`TAILSCALE_HOSTNAME`を使用して`tailscale up --authkey $TAILSCALE_AUTH_KEY --hostname $TAILSCALE_HOSTNAME`を実行する
9. WHERE `docker-compose.yml`でTailscale_Containerを定義する場合、THE System SHALL `command`セクションで`tailscaled`起動と`tailscale up`実行を明文化する

### 要件5: 既存バッチファイルの移行管理

**ユーザーストーリー:** 開発者として、既存のWindowsバッチファイルからDocker Composeへ段階的に移行したい。そうすることで、移行期間中も既存の起動方法を維持しつつ、新しい方法への切り替えを準備できるようにしたい。

#### 受入基準

1. WHEN 既存バッチファイル（`start_api.bat`, `run_fastapi.bat`, `run_funnel.bat`）が存在するとき、THE System SHALL ファイルを削除せずに保持する
2. WHEN 既存バッチファイルが更新されるとき、THE System SHALL 冒頭コメントに「Docker Composeへの移行後は非推奨／互換目的で残置」と明記する
3. THE System SHALL 要件定義書または設計書に「移行完了後にバッチファイルを削除予定」と記載し、削除方針を明確化する
4. WHEN 開発者がREADMEを参照するとき、THE System SHALL Docker Composeによる起動方法を推奨手順として記載し、バッチファイルは代替手段として記載する

### 要件6: 完了条件の検証

**ユーザーストーリー:** 開発者として、基盤整備が完了したことを確認したい。そうすることで、次のステップ（ネットワーク設計、Gemini連携）へ安心して進めるようにしたい。

#### 受入基準

1. WHEN 開発者が`docker compose up -d`を実行したとき、THE System SHALL エラーなくすべてのコンテナを起動する
2. WHEN FastAPI_Containerが起動したとき、THE System SHALL `http://localhost:10000/`にアクセスすると`{"message": "Welcome to the YouTube Summary API!"}`を返す（Tailscale_Containerの`ports: ["127.0.0.1:10000:10000"]`設定により、ループバック限定のポートマッピングで実現）
3. WHEN FastAPI_Containerが起動したとき、THE System SHALL `docker compose exec api curl http://127.0.0.1:10000/`コマンドでコンテナ内からヘルスチェックを実行できる
4. WHEN Tailscale_Containerが起動したとき、THE System SHALL `docker compose exec tailscale tailscale status`コマンドでTailnet接続状態を確認できる
5. WHEN 開発者がTailnetネットワーク内の別デバイスからアクセスするとき、THE System SHALL TailscaleのIPアドレス経由で`http://<tailscale-ip>:10000/`にアクセスできる
6. WHEN 開発者が`.env`ファイルの環境変数を変更し`docker compose restart`を実行したとき、THE System SHALL 変更後の設定値を反映してコンテナを再起動する

### 要件7: ディレクトリ構造の保持

**ユーザーストーリー:** 開発者として、既存のアプリケーション構造を維持したい。そうすることで、既存コードへの影響を最小限に抑え、将来の機能追加にも対応できるようにしたい。

#### 受入基準

1. THE System SHALL `app/core`, `app/routers`, `app/services`, `app/models`ディレクトリ構造を変更しない
2. THE System SHALL `main.py`の配置場所（ルートディレクトリ）を変更しない
3. THE System SHALL `requirements.txt`の配置場所（ルートディレクトリ）を変更しない
4. THE System SHALL Docker関連ファイルのみを`docker/`ディレクトリに集約し、他のファイル配置は変更しない

## 非機能要件

### パフォーマンス

1. WHEN FastAPI_Containerが起動するとき、THE System SHALL 起動完了まで30秒以内に完了する
2. WHEN Tailscale_Containerが起動するとき、THE System SHALL Tailnet接続完了まで60秒以内に完了する

### セキュリティ

1. THE System SHALL `.env`ファイルをバージョン管理から除外し、機密情報の漏洩を防ぐ
2. THE System SHALL API_KEYが未設定の場合、`app/core/security.py`の既存ロジックによりエラーログを出力する
3. THE System SHALL Tailscale_Containerに最小限の権限（NET_ADMIN, NET_RAW）のみを付与する
4. THE System SHALL ポートマッピングを`127.0.0.1:10000:10000`に限定し、ホスト外部からの直接アクセスを防ぐ
5. THE System SHALL Tailnet経由のアクセスのみを許可し、Issue #2の「Tailnet外公開はやめる」方針に準拠する

### 保守性

1. THE System SHALL `.env.example`にすべての環境変数の用途をコメントで説明する
2. THE System SHALL `docker-compose.yml`にサービスごとのコメントを記載し、構成を理解しやすくする
3. THE System SHALL READMEに初回セットアップ手順を記載し、新規開発者が30分以内に環境構築できるようにする

### 互換性

1. THE System SHALL Docker Engine 20.10以降で動作する
2. THE System SHALL Docker Compose v2.0以降で動作する
3. THE System SHALL Windows, macOS, Linuxの各OSで同じ手順で動作する

## スコープ外

以下の項目は本ステップのスコープ外とし、後続ステップで対応します：

- Tailnet ACLの詳細設計（ステップ2: ネットワーク&セキュリティ設計）
- Gemini API連携の実装（ステップ3: Gemini連携サービス層）
- iPhoneショートカット連携（ステップ5: iPhoneショートカット連携仕様）
- 本番環境へのデプロイ設定（ステップ6: 運用検証）
- パフォーマンスチューニング（ステップ6: 運用検証）
- ログ監査の詳細設計（ステップ2: ネットワーク&セキュリティ設計）

## 技術的決定事項と代替案の排除

### 決定事項1: network_mode: "service:tailscale"とループバック限定ポートマッピングの併用

**採用理由:**
- FastAPI_ContainerがTailscale_Containerと同じネットワーク名前空間を共有することで、Tailnet IPへのinboundトラフィックが直接FastAPIに届く
- Tailscale_Containerに`ports: ["127.0.0.1:10000:10000"]`を設定することで、ホストのループバックインターフェース（localhost）のみからアクセス可能
- `127.0.0.1`を明示することで、ホスト外部からの直接アクセスを防ぎ、Issue #2の「Tailnet外公開はやめる」方針に準拠
- この構成により、Tailnet経由のアクセスとローカルホストからのヘルスチェックの両方が実現可能

**排除した代替案:**
- **ソケット共有のみ**: Tailscale_Socketを共有するだけでは、inboundトラフィックがFastAPIに到達しない。outbound通信（FastAPIからTailnet内の他サービスへのアクセス）には有効だが、今回の要件（Tailnet経由でFastAPIにアクセス）には不十分
- **tailscale serveの使用**: `tailscale serve`でポート10000をプロキシする方法も可能だが、追加の設定が必要で複雑化する。MVPでは`network_mode`の方がシンプル
- **FastAPI_Containerに直接portsを設定**: `network_mode: "service:tailscale"`を使用すると、FastAPI_Containerの`ports`設定は無効化される。Tailscale_Container側でポートマッピングを行う必要がある
- **全インターフェース公開（`0.0.0.0:10000:10000`）**: ホスト外部から直接アクセス可能になり、Issue #2の「Tailnet外公開はやめる」方針と矛盾するため不採用
- **`--network host`の使用**: ホストのネットワークスタックを直接使用する方法は、Tailnet限定の運用方針と衝突し、セキュリティリスクが高いため不採用

### 決定事項2: tailscale upの条件付き実行と障害復旧

**採用理由:**
- `/var/lib/tailscale`ボリューム内に既存の認証状態が存在する場合、まず`tailscale status`で接続状態を確認
- `tailscale status`が成功（終了コード0）かつTailnetに接続済みの場合のみ`tailscale up`をスキップ
- `tailscale status`が失敗または未接続の場合は、ACL改訂やキー失効などの障害から自動復旧するため`tailscale up`を再実行
- Tailscaleの認証キーはデフォルトでsingle-use（一回限り）のため、毎回実行すると2回目以降の起動に失敗する
- 認証状態の永続化により、コンテナ再起動時も再認証不要で運用可能

**排除した代替案:**
- **毎回tailscale upを実行**: single-use Auth Keyの場合、初回起動後にキーが失効し、2回目以降の起動に失敗する。運用上不可能
- **手動実行**: コンテナ起動後に手動で`tailscale up`を実行する方法は、自動化の観点から不適切
- **再利用可能キーの強制**: 管理者に再利用可能なAuth Keyの発行を強制する方法も可能だが、デフォルト設定で動作する方が望ましい。ただし、移行時の注意事項に「再利用可能キーの推奨」を記載
- **tailscale statusのみでスキップ**: 状態ファイルが残っていても`tailscale status`が失敗するケース（ACL改訂、キー失効等）で再接続できず、APIが孤立する。障害復旧ができないため不採用

### 決定事項3: 環境変数のテンプレート化

**採用理由:**
- `.env.example`にすべての環境変数を列挙することで、新規環境構築時の手順が明確化
- `TAILSCALE_HOSTNAME`等をハードコードせず、環境変数で管理することで、複数環境での再現性が向上

**排除した代替案:**
- **Dockerfileへのハードコード**: ホスト名等を`Dockerfile`に直接記述する方法は、環境ごとにDockerfileを変更する必要があり、保守性が低下
- **JSON/YAML設定ファイル**: 既存の`load_dotenv`実装と整合しないため、環境変数ベースの管理を継続

## 移行時の注意事項

1. **既存の`.venv`環境との並行運用**
   - Docker環境と既存のローカル仮想環境は並行して動作可能
   - 移行期間中は両方の環境で動作確認を推奨

2. **Tailscale認証キーの取得**
   - 初回起動前にTailscaleダッシュボードから認証キー（Auth Key）を取得
   - `.env`ファイルに`TAILSCALE_AUTH_KEY`として設定
   - **推奨**: Tailscaleダッシュボードで「Reusable（再利用可能）」オプションを有効にしてAuth Keyを生成。これにより、コンテナ再起動時も同じキーを使用可能
   - **注意**: single-use（一回限り）のAuth Keyを使用する場合、初回起動後は認証状態がボリュームに保存されるため、2回目以降は`tailscale up`がスキップされる。ボリュームを削除した場合は新しいAuth Keyが必要
   - Auth Keyが未設定で、かつ既存の認証状態が存在しない場合、Tailscale_Containerは起動に失敗する

3. **Tailscaleホスト名の設定**
   - `.env`ファイルに`TAILSCALE_HOSTNAME`を設定（例: `youtube-api-dev`）
   - 複数環境で異なるホスト名を使用することで、Tailnet内での識別が容易になる

4. **ネットワーク名前空間の共有**
   - FastAPI_ContainerはTailscale_Containerと`network_mode: "service:tailscale"`で同じネットワークスタックを共有
   - この設定により、Tailnet IPへのアクセスが直接FastAPIに届く
   - ソケット共有のみではinboundトラフィックが届かないため、この設定が必須

5. **ポートマッピングの設定**
   - `network_mode: "service:tailscale"`を使用する場合、FastAPI_Containerの`ports`設定は無効化される
   - ローカルホストからのヘルスチェックを可能にするため、Tailscale_Containerに`ports: ["127.0.0.1:10000:10000"]`を設定する（必須）
   - **重要**: `127.0.0.1`を明示することで、ループバックインターフェースのみに限定し、ホスト外部からの直接アクセスを防ぐ
   - この設定により、`http://localhost:10000/`でのヘルスチェックとTailnet IP経由のアクセスの両方が可能になり、Issue #2の「Tailnet外公開はやめる」方針に準拠

6. **ボリュームの永続化**
   - Tailscaleの認証状態は`tailscale-state`ボリュームに保存
   - `docker compose down -v`を実行するとボリュームが削除され、再認証が必要

7. **ログの確認方法**
   - `docker compose logs -f api`: FastAPIのログをリアルタイム表示
   - `docker compose logs -f tailscale`: Tailscaleのログをリアルタイム表示
   - `docker compose exec tailscale tailscale status`: Tailnet接続状態の確認

8. **環境変数の設定例**
   - `.env.example`に記載されたすべての環境変数を`.env`にコピーし、適切な値を設定
   - 特に`TAILSCALE_AUTH_KEY`と`TAILSCALE_HOSTNAME`は必須

## 参照ドキュメント

- Issue #2: Tailnet内常駐化とGemini要約導入の実装ロードマップ
- Issue #1: Tailnet内運用・Docker Compose常駐化・Gemini要約導入の決定事項
- 既存実装: `main.py`, `app/core/security.py`, `app/core/logging_config.py`
