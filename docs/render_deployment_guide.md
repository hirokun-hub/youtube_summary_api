---
created: "[[2025-07-04]]"
aliases: "Renderデプロイ手順"
tags:
  - "Render"
  - "デプロイ"
  - "インフラ"
  - "IaC"
---

# [[Render]]へのデプロイ手順書

このドキュメントは、`youtube-summary-api` を [[Render]] にデプロイするための手順をまとめたものです。

---

## 🚩 無料枠（Free Tier）での手動デプロイ手順（おすすめ）

Blueprint（render.yaml）を使わず、RenderのWeb UIから「New Web Service」を作成してデプロイする方法です。**クレジットカード不要＆無料枠で試せます。**

### 手順
1. [Renderダッシュボード](https://dashboard.render.com/) にログイン
2. 左メニューから「Web Services」または「+ New」→「Web Service」を選択
3. GitHubリポジトリを連携し、`hirokun-hub/youtube_summary_api` を選択
   - ブランチは `refactor/low-hanging-improvements` を選択
4. サービス名などを入力し、Python環境を選択
5. **Build Command**: `pip install --upgrade pip && pip install -r requirements.txt`
6. **Start Command**: `uvicorn main:app --host 0.0.0.0 --port 10000`
   - ポート番号はRenderの指示に従ってください（`$PORT`など自動設定の場合もあり）
7. 「Environment」セクションで `API_KEY` を追加（必須）
8. 「Create Web Service」でデプロイ開始

> [!TIP]
> render.yamlはこの手動方式では不要です。

---

## 準備するもの

- [[GitHub]] アカウント
- [[Render]] アカウント（[[GitHub]] アカウントでサインアップ可能）
- [[API_KEY]]（[[YouTube Data API]] のキー）

## デプロイ手順

デプロイ作業は、[[Render]] のダッシュボード（Webサイト）で行います。

### 1. Renderへのログインとサービス作成

1.  まず、[Renderのダッシュボード](https://dashboard.render.com/)にアクセスし、[[GitHub]] アカウントでログインします。
2.  次に、以下のリンクから新しい **Blueprint Service** の作成ページを開きます。
    -   **[https://dashboard.render.com/blueprints/new](https://dashboard.render.com/blueprints/new)**

### 2. リポジトリの連携

1.  "Connect a repository" の下にあるリポジトリリストから `hirokun-hub/youtube_summary_api` を選択します。
2.  もしリポジトリが表示されない場合は、`Configure GitHub account` をクリックして、[[Render]] と [[GitHub]] の連携設定を確認・許可してください。

### 3. Blueprint設定の確認と環境変数の登録

1.  リポジトリを選択すると、[[Render]] が自動で `render.yaml` を読み込み、サービス名やビルドコマンドなどの設定内容が画面に表示されます。内容が正しいことを確認してください。

2.  次に、**最も重要な環境変数の設定**を行います。画面を下にスクロールし、`Environment` セクションを見つけます。

3.  `+ Add Environment Variable` をクリックし、以下のように [[API_KEY]] を設定します。
    -   **Key**: `API_KEY`
    -   **Value**: あなたが取得した [[YouTube Data API]] のキーをここに貼り付けます。
    > [!WARNING]
    > このキーは秘密の情報です。絶対に外部に漏らさないでください。`render.yaml` の `sync: false` 設定により、このダッシュボードで設定した値がリポジトリに書き込まれることはありません。

### 4. デプロイの実行

1.  [[API_KEY]] の設定が完了したら、画面下部にある `Create New Blueprint Service` ボタンをクリックします。
2.  クリック後、自動的にデプロイが開始されます。最初のデプロイには数分かかることがあります。

## デプロイ後の確認

### 1. デプロイ状況の確認

-   ダッシュボードの `Events` タブで、デプロイの進捗状況（ビルド、デプロイのログ）をリアルタイムで確認できます。
-   "deploy successful" や "service live" といったメッセージが表示されれば成功です。

### 2. 公開URLの確認

-   デプロイが成功すると、サービスのダッシュボード上部に `https://<サービス名>.onrender.com` という形式の公開URLが表示されます。このURLが、あなたのAPIのエンドポイントになります。

### 3. 動作テスト

デプロイしたAPIが正しく動作するか、`curl` コマンドやAPIテストツール（Postmanなど）を使って確認してみましょう。

```bash
# YOUR_RENDER_URL を実際のURLに、YOUR_API_KEY を実際のキーに置き換えてください
curl -X POST "YOUR_RENDER_URL/api/v1/summary" \
-H "Content-Type: application/json" \
-H "X-API-KEY: YOUR_API_KEY" \
-d '{
  "url": "https://www.youtube.com/watch?v=your_video_id"
}'
```

上記コマンドを実行し、動画のタイトルや文字起こしを含むJSONが返ってくれば、デプロイは成功です。
