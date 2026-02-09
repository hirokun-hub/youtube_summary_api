# Implementation Plan（TDD）

## Phase 1: テスト基盤構築

- [ ] 1. テスト環境のセットアップ
  - [ ] 1.1 `requirements-dev.txt` を作成する
    - `-r requirements.txt` を先頭に記載し、`pytest`, `httpx` を追加
    - _要件: 設計書 1.4_
  - [ ] 1.2 `requirements.txt` を更新する
    - `yt-dlp[default]` を追加（yt-dlp-ejsを含む）
    - `youtube-transcript-api>=1.2.0` に更新
    - `pytube` を削除
    - _要件: US-1, 要件定義書 技術方針_
  - [ ] 1.3 `tests/` ディレクトリと基盤ファイルを作成する
    - `tests/__init__.py`
    - `tests/conftest.py`（環境変数モック、TestClient fixture、APIキー無効化、共通テストデータ）
    - `pytest.ini`
    - _要件: 設計書 1.2, 2.4, 2.5_
  - [ ] 1.4 テスト用依存をローカルにインストールし、`pytest` が実行できることを確認する
    - `pip install -r requirements-dev.txt && pytest --version`
    - _要件: 設計書 5_

## Phase 2: レスポンスモデル（RED → GREEN）

- [ ] 2. スキーマテストを書く（RED）
  - [ ] 2.1 `tests/test_schemas.py` にテストケース S-1〜S-6 を実装する
    - S-1: 全21フィールドが定義されていること
    - S-2: 成功レスポンスの生成（全フィールドに値）
    - S-3: 失敗レスポンスの生成（transcript=null、メタデータあり）
    - S-4: 失敗レスポンスの生成（全フィールドnull）
    - S-5: status フィールド（success=True→"ok", success=False→"error"）
    - S-6: 後方互換性（既存5フィールドの型が変更されていない）
    - テスト実行 → 全件失敗（RED）を確認
    - _要件: US-1, US-4, 設計書 3.1_

- [ ] 3. レスポンスモデルを実装する（GREEN）
  - [ ] 3.1 `app/models/schemas.py` の `SummaryResponse` に16フィールドを追加する
    - `status`, `error_code`, `upload_date`, `duration`, `duration_string`, `view_count`, `like_count`, `thumbnail_url`, `description`, `tags`, `categories`, `channel_id`, `channel_follower_count`, `webpage_url`, `transcript_language`, `is_generated`
    - `status` は `success` の値から自動導出する設計とする
    - _要件: US-1, US-2, US-4_
  - [ ] 3.2 `model_config` のレスポンス例を更新する
    - _要件: US-1_
  - [ ] 3.3 テスト実行 → 全件成功（GREEN）を確認する

## Phase 3: サービス層（RED → GREEN）

- [ ] 4. サービス層テストを書く（RED）
  - [ ] 4.1 `tests/test_youtube_service.py` にテストケース Y-1〜Y-13 を実装する
    - Y-1: 正常系 全データ取得成功（yt-dlp成功 + transcript成功、oEmbed呼び出しなし）
    - Y-2: 正常系 yt-dlp失敗→oEmbedフォールバック + transcript成功
    - Y-3: 異常系 字幕なし + メタデータ成功（error_code="TRANSCRIPT_NOT_FOUND"）
    - Y-4: 異常系 動画不存在（error_code="VIDEO_NOT_FOUND"）
    - Y-5: 異常系 無効URL（error_code="INVALID_URL"）
    - Y-6: 異常系 レート制限（error_code="RATE_LIMITED"）
    - Y-7: 異常系 予期せぬエラー（error_code="INTERNAL_ERROR"）
    - Y-8: 安定性中フィールドの欠損（like_count=None等）
    - Y-9: transcript_language と is_generated の正しい取得
    - Y-10: yt-dlp DownloadError → METADATA_FAILED マッピング
    - Y-11: transcript の後方互換性（タイムスタンプフォーマット同一）
    - Y-12: yt-dlp戻り値にキーが存在しない場合（nullで返す）
    - Y-13: error_code 6種の全カバレッジ
    - モック対象: `app.services.youtube.yt_dlp.YoutubeDL`, `app.services.youtube.YouTubeTranscriptApi`, `app.services.youtube.requests.get`
    - テスト実行 → 全件失敗（RED）を確認
    - _要件: US-1, US-2, US-3, US-4, 設計書 3.2_

- [ ] 5. サービス層を実装する（GREEN）
  - [ ] 5.1 `app/services/youtube.py` に yt-dlp メタデータ取得関数を追加する
    - `yt_dlp.YoutubeDL` で `extract_info(url, download=False)` を呼び出し
    - `ydl.sanitize_info(info)` でデータをサニタイズ
    - すべてのフィールドを `info.get("key")` で取得（キー不在時はNone）
    - yt-dlpのキー名からレスポンスのフィールド名にマッピング（例: `thumbnail` → `thumbnail_url`、`channel` → `channel_name`）
    - 例外 `yt_dlp.utils.DownloadError` をキャッチ
    - _要件: US-1, 要件定義書 フィールド定義_
  - [ ] 5.2 yt-dlp 失敗時の oEmbed フォールバック処理を実装する
    - yt-dlp が `DownloadError` を投げた場合のみ oEmbed API を呼び出す
    - oEmbed から title, channel_name（author_name）, thumbnail_url を取得
    - _要件: US-3, 要件定義書 フォールバック_
  - [ ] 5.3 youtube-transcript-api を v1.2.x の新APIに移行する
    - `YouTubeTranscriptApi()` でインスタンス生成
    - `api.list(video_id)` → `transcript_list.find_transcript(['ja', 'en'])` → `transcript.fetch()`
    - `transcript.language_code` → `transcript_language`
    - `transcript.is_generated` → `is_generated`
    - `fetched.to_raw_data()` で `list[dict]` に変換し、現在と同一のタイムスタンプフォーマットで文字列化
    - _要件: US-1, 要件定義書 youtube-transcript-api の破壊的変更_
  - [ ] 5.4 エラーコード体系を実装する
    - 各例外に対応する `error_code` を設定
    - `DownloadError` → `METADATA_FAILED`（字幕成功時）/ `VIDEO_NOT_FOUND`（全体失敗時）
    - `NoTranscriptFound` → `TRANSCRIPT_NOT_FOUND`
    - `YouTubeRequestFailed` → `RATE_LIMITED`
    - URL正規表現不一致 → `INVALID_URL`
    - その他 → `INTERNAL_ERROR`
    - _要件: US-2, 要件定義書 エラーコード定義_
  - [ ] 5.5 `status` フィールドを `success` と連動して設定する
    - _要件: US-4_
  - [ ] 5.6 処理順序を変更する（メタデータ取得 → 字幕取得）
    - 字幕取得に失敗してもメタデータは返す
    - _要件: US-3_
  - [ ] 5.7 テスト実行 → 全件成功（GREEN）を確認する

## Phase 4: API統合テスト（RED → GREEN）

- [ ] 6. API統合テストを書く（RED）
  - [ ] 6.1 `tests/test_api_endpoint.py` にテストケース E-1〜E-7 を実装する
    - E-1: 正常リクエスト（200, 全フィールド存在）
    - E-2: APIキーなし（403）
    - E-3: 無効なURL（200, error_code="INVALID_URL"）
    - E-4: 字幕なし動画（200, error_code="TRANSCRIPT_NOT_FOUND", メタデータあり）
    - E-5: 後方互換性（既存5フィールドの存在と型）
    - E-6: status フィールド（成功時"ok"、失敗時"error"）
    - E-7: transcript_language, is_generated の存在確認
    - テスト実行 → 失敗があれば修正 → GREEN
    - _要件: US-1, US-2, US-3, US-4, 設計書 3.3_

## Phase 5: Docker環境更新 + 実環境テスト

- [ ] 7. Docker環境を更新する
  - [ ] 7.1 `docker/Dockerfile.api` を更新する
    - Deno（JavaScriptランタイム）のインストールを追加（yt-dlp 2025.11.12以降のYouTube対応に必須）
    - `yt-dlp[default]` が正しくインストールされることを確認
    - _要件: 要件定義書 yt-dlp のシステム要件_
  - [ ] 7.2 Docker Compose でビルド・起動し、手動で動作確認する
    - 公開動画で全フィールドが取得できることを確認
    - 字幕なし動画で error_code="TRANSCRIPT_NOT_FOUND" + メタデータ返却を確認
    - 存在しない動画URLで error_code="VIDEO_NOT_FOUND" を確認
    - 既存のiPhoneショートカットが変更なしで動作することを確認
    - _要件: US-1, US-2, US-3, US-4, 要件定義書 最重要方針: 後方互換性_
