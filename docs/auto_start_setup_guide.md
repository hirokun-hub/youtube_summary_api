---
created: "[[2025-07-05]]"
aliases: "APIサーバー自動起動設定手順"
tags:
  - "Windows"
  - "自動化"
  - "バッチスクリプト"
---

# APIサーバー自動起動 設定手順書

このドキュメントは、PC起動時にFastAPIサーバーとTailscale Funnelを自動で起動するための設定手順をまとめたものです。

## 1. 自動起動スクリプトの確認

プロジェクトのルートフォルダに `start_api.bat` というファイルがあることを確認します。このファイルは、サーバーとFunnelを同時に起動するためのものです。

```batch
@echo off
ECHO YouTube Summary APIサーバーを起動しています...

REM プロジェクトのディレクトリに移動します
cd C:\Users\hirok\Documents\Windsurf\811【開発】\youtube_summary_api

REM 1. FastAPIサーバーを新しいウィンドウで起動します
ECHO FastAPIサーバーを起動中...
start "FastAPI Server" cmd /k ".\.venv\Scripts\activate.bat && uvicorn main:app --host 127.0.0.1 --port 10000"

REM サーバーが起動するまで少し待ちます (5秒)
timeout /t 5 /nobreak

REM 2. Tailscale Funnelを新しいウィンドウで起動します
ECHO Tailscale Funnelを起動中...
start "Tailscale Funnel" cmd /k "\"C:\Program Files\Tailscale\tailscale.exe\" funnel 10000"

ECHO 自動起動スクリプトの処理が完了しました。
```

## 2. 動作テスト

`start_api.bat` を手動でダブルクリックし、「FastAPI Server」と「Tailscale Funnel」の2つのウィンドウが正常に起動することを確認します。

## 3. スタートアップへの登録

1.  **「ファイル名を指定して実行」を開きます。**
    -   `Windowsキー + R` を押します。

2.  **スタートアップフォルダを開きます。**
    -   入力欄に `shell:startup` と入力して「OK」をクリックします。
    -   エクスプローラーでスタートアップフォルダが開きます。

3.  **ショートカットを作成して配置します。**
    -   `start_api.bat` ファイルを**右クリックしながら**、先ほど開いたスタートアップフォルダまでドラッグ＆ドロップします。
    -   メニューが表示されたら、「ショートカットをここに作成」を選択します。

これで設定は完了です。次回以降、PCにサインインすると自動的にAPIサーバーが起動します。

## 4. 注意事項

- PC起動直後は、サーバーが完全に立ち上がるまで数十秒かかる場合があります。
- 自動起動を停止したい場合は、スタートアップフォルダに作成したショートカットを削除してください。
