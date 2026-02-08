# Implementation Plan

- [ ] 1. 依存ライブラリの更新
  - [ ] 1.1 `yt-dlp` を `requirements.txt` に追加する
    - _要件: US-1_
  - [ ] 1.2 `pytube` を `requirements.txt` から削除する
    - メンテナンス停滞中（2023年5月以降リリースなし）のため廃止
    - コード内に `pytube` のimportが残っていないことを確認する
    - _要件: US-1_
  - [ ] 1.3 `youtube-transcript-api` を最新版に更新する
    - 1.1.0 → 最新版（1.2.x系）
    - APIの破壊的変更がないか確認する（`list_transcripts` → `list` 等の変更の可能性）
    - _要件: US-1_

- [ ] 2. レスポンスモデルの拡張
  - [ ] 2.1 `app/models/schemas.py` の `SummaryResponse` にフィールドを追加する
    - `status`: string（`"ok"` / `"error"`）
    - `error_code`: string | null
    - `upload_date`: string | null
    - `duration`: int | null
    - `duration_string`: string | null
    - `view_count`: int | null
    - `like_count`: int | null
    - `thumbnail_url`: string | null
    - `description`: string | null
    - `tags`: list | null
    - `categories`: list | null
    - `channel_id`: string | null
    - `channel_follower_count`: int | null
    - `webpage_url`: string | null
    - `transcript_language`: string | null
    - `is_generated`: bool | null
    - _要件: US-1, US-2, US-4_
  - [ ] 2.2 `model_config` のレスポンス例を更新する
    - 成功時の全フィールドを含むサンプルに更新
    - _要件: US-1_

- [ ] 3. yt-dlp によるメタデータ取得の実装
  - [ ] 3.1 `app/services/youtube.py` に yt-dlp メタデータ取得関数を追加する
    - `extract_info(url, download=False)` でメタデータのみ取得
    - `quiet=True`, `no_warnings=True`, `skip_download=True` オプション設定
    - 必要なフィールドのみ抽出して dict で返す
    - _要件: US-1_
  - [ ] 3.2 yt-dlp 取得失敗時のフォールバック処理を実装する
    - yt-dlp が失敗しても oEmbed + transcript で最低限返す
    - _要件: US-3_

- [ ] 4. oEmbed API からの追加データ取得
  - [ ] 4.1 既存の oEmbed レスポンスから `thumbnail_url` を取得する
    - `meta_json.get("thumbnail_url")` を追加するだけ
    - _要件: US-1_

- [ ] 5. youtube-transcript-api の拡張活用
  - [ ] 5.1 字幕の言語情報と自動生成判定を取得する
    - `list_transcripts` （または最新APIの `list`）で字幕メタデータを取得
    - `transcript_language` と `is_generated` をレスポンスに含める
    - _要件: US-1_

- [ ] 6. エラーハンドリングの改善
  - [ ] 6.1 エラーコード体系を実装する
    - 各例外に対応する `error_code` を設定
    - `INVALID_URL`, `VIDEO_NOT_FOUND`, `TRANSCRIPT_NOT_FOUND`, `RATE_LIMITED`, `METADATA_FAILED`, `INTERNAL_ERROR`
    - _要件: US-2_
  - [ ] 6.2 失敗時でも取得済みメタデータを返すよう処理順序を変更する
    - メタデータ取得 → 字幕取得の順で実行し、字幕失敗時もメタデータは返す
    - _要件: US-3_
  - [ ] 6.3 `status` フィールド（`"ok"` / `"error"`）をレスポンスに含める
    - `success` の bool 値と連動させる
    - _要件: US-4_

- [ ] 7. Docker環境の更新
  - [ ] 7.1 `docker/Dockerfile.api` に yt-dlp の依存を考慮した更新を行う
    - 必要に応じてシステムパッケージを追加（yt-dlp が必要とするもの）
    - _要件: US-1_

- [ ] 8. 動作確認テスト
  - [ ] 8.1 正常系テスト: 公開動画で全フィールドが取得できることを確認する
    - 全新規フィールドが期待通りの型と値で返ることを確認
    - _要件: US-1, US-4_
  - [ ] 8.2 異常系テスト: 字幕なし動画で適切なエラーレスポンスを確認する
    - `success: false`, `status: "error"`, `error_code: "TRANSCRIPT_NOT_FOUND"` を確認
    - メタデータが返されていることを確認
    - _要件: US-2, US-3_
  - [ ] 8.3 異常系テスト: 存在しない動画URLで適切なエラーレスポンスを確認する
    - `error_code: "VIDEO_NOT_FOUND"` を確認
    - _要件: US-2_
  - [ ] 8.4 後方互換性テスト: 既存フィールド（success, message, title, channel_name, transcript）が変更されていないことを確認する
    - _要件: US-4_
