# YouTube Data API v3 移行 — 技術的制約（専門家調査結果）

> 調査日: 2026-02-27
> 回答者: 専門家O（アーキテクト）、専門家A（Web検索確認済）、専門家G（AI調査）
> 信頼度: 以下の情報は3名の専門家の合意、および公式ドキュメントとの照合により信頼性97%以上と判断したもの

---

## 1. HTTP クライアント選択

**結論: `requests` で REST API を直接呼び出し（3名全員一致）**

| 根拠 | 詳細 |
|------|------|
| 依存追加ゼロ | `requests==2.32.4` は既に導入済み |
| 規模に適合 | 1日最大50件、同期サービス層、エンドポイント2つのみ |
| Docker影響なし | `google-api-python-client` は50MB超の依存増 |
| 十分な制御性 | タイムアウト・リトライ・エラーハンドリングを明示的に記述可能 |

- 参考: [google-api-python-client (PyPI)](https://pypi.org/project/google-api-python-client/)

---

## 2. videos.list API レスポンス仕様

API: `GET https://www.googleapis.com/youtube/v3/videos?part=snippet,contentDetails,statistics&id={video_id}&key={API_KEY}`

### 2.1 snippet.publishedAt

- **ISO 8601 形式、UTC（Z suffix）付き**
- 例: `"2026-02-27T10:00:00Z"`
- 変換: `YYYY-MM-DD` への切り出しはタイムゾーン `Z`（UTC）を前提に日付部分を取得

### 2.2 contentDetails.duration

- **ISO 8601 duration 形式**
- 具体例:
  - 1時間2分3秒 → `"PT1H2M3S"`
  - 30秒 → `"PT30S"`
  - 10分 → `"PT10M"` または `"PT10M0S"`
  - ライブ配信処理中/不明 → `"P0D"` または `"PT0S"`（秒数0として扱う）
  - 1日以上 → `"P1DT2H3M4S"`（稀だが対応必要）

### 2.3 statistics フィールドの型

- `viewCount`, `likeCount`, `favoriteCount`, `commentCount` は **すべて文字列型（string）**
- 例: `"viewCount": "12345"` → `int("12345")` への変換が必須
- 理由: 64bit整数のJSON表現の都合（[Google APIs Discovery type/format](https://docs.cloud.google.com/docs/discovery/type-format)）

### 2.4 likeCount が非公開の場合

- **フィールド自体がレスポンスから省略される**（`null` や `"0"` ではない）
- 実装: `.get("likeCount")` で `None` を許容するか、デフォルト値を設定

### 2.5 snippet.tags が未設定の場合

- **フィールド自体がレスポンスに存在しない**（空配列ではない）
- 実装: `.get("tags", [])` で安全にデフォルト値を取得

### 2.6 snippet.thumbnails のキーと解像度

| キー | 解像度 | 全動画で存在 |
|------|--------|-------------|
| `default` | 120×90 | はい |
| `medium` | 320×180 | はい |
| `high` | 480×360 | はい |
| `standard` | 640×480 | **いいえ** |
| `maxres` | 1280×720 | **いいえ** |

- 選択優先順位: `maxres` → `standard` → `high` → `medium` → `default`

### 2.7 存在しない・非公開・削除済み動画

- HTTP ステータスは **200 OK**
- `items` は **空配列 `[]`**
- 404 エラーにはならない

### ソース

- [Videos リソース](https://developers.google.com/youtube/v3/docs/videos)
- [Videos: list](https://developers.google.com/youtube/v3/docs/videos/list)

---

## 3. channels.list API — subscriberCount 仕様

API: `GET https://www.googleapis.com/youtube/v3/channels?part=statistics&id={channel_id}&key={API_KEY}`

- `subscriberCount` の型: **文字列（string）** → `int()` 変換が必要
- `subscriberCount` は **3桁の有効数字に丸められた概数**（例: 登録者123,456人 → `"123000"`）
- `hiddenSubscriberCount` が `true` の場合: 実装は**フィールド欠損または `"0"` の両方に対応**すべき（専門家間で見解が分かれるため防御的に実装）
- クォータコスト: **1ユニット**

### ソース

- [Channels リソース](https://developers.google.com/youtube/v3/docs/channels)
- [Channels: list](https://developers.google.com/youtube/v3/docs/channels/list)

---

## 4. categoryId → カテゴリ名変換

**結論: 静的マッピングテーブル + 未知ID時のAPIフォールバック（専門家A・G推奨、専門家Oも条件付き合意）**

### 根拠

- YouTube のカテゴリ ID は **2012年頃からほぼ変更なし**で非常に安定
- `videoCategories.list` はクォータ1ユニットを消費 + ネットワークレイテンシ増
- `regionCode` パラメータにより返されるカテゴリのサブセットが変わる問題がある

### カテゴリ ID → 名前マッピング（US基準、専門家A提供）

```python
YOUTUBE_CATEGORY_MAP = {
    "1": "Film & Animation",
    "2": "Autos & Vehicles",
    "10": "Music",
    "15": "Pets & Animals",
    "17": "Sports",
    "18": "Short Movies",
    "19": "Travel & Events",
    "20": "Gaming",
    "21": "Videoblogging",
    "22": "People & Blogs",
    "23": "Comedy",
    "24": "Entertainment",
    "25": "News & Politics",
    "26": "Howto & Style",
    "27": "Education",
    "28": "Science & Technology",
    "29": "Nonprofits & Activism",
    "30": "Movies",
    "31": "Anime/Animation",
    "32": "Action/Adventure",
    "33": "Classics",
    "34": "Comedy",
    "35": "Documentary",
    "36": "Drama",
    "37": "Family",
    "38": "Foreign",
    "39": "Horror",
    "40": "Sci-Fi/Fantasy",
    "41": "Thriller",
    "42": "Shorts",
    "43": "Shows",
    "44": "Trailers",
}
```

> 注意: yt-dlp が英語名で返していたため、既存との後方互換を保つには英語名（US基準）で統一する

### ソース

- [VideoCategories: list](https://developers.google.com/youtube/v3/docs/videoCategories/list)

---

## 5. クォータ制度

| 項目 | 値 |
|------|-----|
| デフォルト日次上限 | **10,000 ユニット/日** |
| `videos.list` コスト | **1 ユニット**（part複数指定でも1） |
| `channels.list` コスト | **1 ユニット** |
| 1動画あたり合計 | **2 ユニット**（videos + channels） |
| 1日50件時の消費 | **100 ユニット/日**（上限の1%） |
| リセットタイミング | **太平洋時間（PT）午前0時**（JST: 午後5時/夏時間午後4時） |
| 引き上げ申請 | 可能。ただし Compliance Audit（規約準拠監査）が前提 |

### クォータ超過時のレスポンス

- HTTP ステータス: **403**
- `error.errors[0].reason`: `"quotaExceeded"`
- `error.errors[0].domain`: `"youtube.quota"`

```json
{
  "error": {
    "code": 403,
    "message": "The request cannot be completed because you have exceeded your quota.",
    "errors": [
      {
        "message": "The request cannot be completed because you have exceeded your quota.",
        "domain": "youtube.quota",
        "reason": "quotaExceeded"
      }
    ]
  }
}
```

### ソース

- [YouTube Data API Overview](https://developers.google.com/youtube/v3/getting-started)
- [Quota Calculator](https://developers.google.com/youtube/v3/determine_quota_cost)
- [Quota and Compliance Audits](https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits)

---

## 6. API キー制限

| 項目 | 推奨 |
|------|------|
| 制限方式 | **IP アドレス制限**（サーバー to サーバー用途） |
| API 制限 | **YouTube Data API v3 のみ**に制限 |
| ローテーション | **90日〜半年**ごと |

- HTTP リファラー制限はブラウザ向け、サーバーサイドの `requests` には不適
- Docker + Tailscale 環境では外向き Egress IP で固定できるなら IP 制限が最適
- IP 固定が難しい場合は API 制限のみでも許容

### ソース

- [API keys best practices](https://cloud.google.com/docs/authentication/api-keys-best-practices)

---

## 7. ISO 8601 Duration パース

**結論: 正規表現で自前パース（専門家A・G推奨）**

- YouTube Data API が返す duration は ISO 8601 の限定サブセット
- `isodate` ライブラリ（専門家O推奨）は追加依存になり、この用途には過剰
- `P#DT#H#M#S` まで対応すれば十分

### 対応すべきパターン

| 入力 | 秒数 | 文字列 |
|------|------|--------|
| `PT1H2M3S` | 3723 | `"1:02:03"` |
| `PT30S` | 30 | `"0:30"` |
| `PT10M` | 600 | `"10:00"` |
| `P0D` | 0 | `"0:00"` |
| `PT0S` | 0 | `"0:00"` |
| `P1DT2H3M4S` | 93784 | `"26:03:04"` |

---

## 8. エラーハンドリング

### エラーレスポンス共通構造

```json
{
  "error": {
    "code": <HTTPステータスコード>,
    "message": "<メッセージ>",
    "errors": [
      {
        "message": "<詳細>",
        "domain": "<ドメイン>",
        "reason": "<理由コード>"
      }
    ]
  }
}
```

### エラー分類とアプリ内マッピング

| HTTP | reason | 意味 | アプリの error_code | リトライ |
|------|--------|------|-------------------|---------|
| 400 | `badRequest` | パラメータ不正 | `INTERNAL_ERROR` | 不可 |
| 401 | `unauthorized` | 認証エラー | `INTERNAL_ERROR` | 不可 |
| 403 | `quotaExceeded` | クォータ超過 | `RATE_LIMITED` | 不可（リセット待ち） |
| 403 | `forbidden` | 権限不足 | `VIDEO_NOT_FOUND` | 不可 |
| 403 | `accessNotConfigured` | API未有効化 | `INTERNAL_ERROR` | 不可 |
| 404 | `notFound` | リソースなし | `VIDEO_NOT_FOUND` | 不可 |
| 200 | items: [] | 動画なし/非公開 | `VIDEO_NOT_FOUND` | 不可 |
| 500 | `backendError` | サーバー障害 | (リトライ後) `METADATA_FAILED` | **指数バックオフ** |
| 503 | — | サービス停止 | (リトライ後) `METADATA_FAILED` | **指数バックオフ** |

### ソース

- [YouTube Data API Errors](https://developers.google.com/youtube/v3/docs/errors)

---

## 9. requests 直接呼び出しの実装指針

### タイムアウト

- 接続タイムアウト: 3秒、読み取りタイムアウト: 10秒
- `requests.get(url, timeout=(3.05, 10))`

### リトライ

- 対象: 500, 502, 503, 504 のみ
- 指数バックオフ: 1秒 → 2秒 → 4秒（最大3回）
- 400系・403系は即時失敗（リトライ不可）

### セキュリティ

- API キーは環境変数から読み込み（`os.getenv("YOUTUBE_API_KEY")`）
- `verify=False` は **絶対に設定しない**（デフォルトで証明書検証ON）
- API キーがログに漏洩しないよう注意（URLクエリパラメータに含まれるため）

---

## 10. 後方互換フィールドマッピング（実装チェックリスト）

| レスポンスフィールド | 変換元 | 変換処理 | 欠損時のデフォルト |
|---------------------|--------|---------|-------------------|
| `title` | `snippet.title` | そのまま | `None` |
| `channel_name` | `snippet.channelTitle` | そのまま | `None` |
| `channel_id` | `snippet.channelId` | そのまま | `None` |
| `upload_date` | `snippet.publishedAt` | ISO 8601 datetime → `YYYY-MM-DD` 切り出し | `None` |
| `duration` | `contentDetails.duration` | ISO 8601 duration → 秒数（int） | `None` |
| `duration_string` | `contentDetails.duration` | ISO 8601 duration → `"H:MM:SS"` / `"M:SS"` | `None` |
| `view_count` | `statistics.viewCount` | `int(str)` | `None` |
| `like_count` | `statistics.likeCount` | `int(str)`、**フィールド欠損時は `None`** | `None` |
| `thumbnail_url` | `snippet.thumbnails` | maxres→standard→high→medium→default の優先順 | `None` |
| `description` | `snippet.description` | そのまま | `None` |
| `tags` | `snippet.tags` | そのまま、**フィールド欠損時は `None`** | `None` |
| `categories` | `snippet.categoryId` | 静的マッピングで名前に変換 → `[name]` リスト化 | `None` |
| `webpage_url` | — | `https://www.youtube.com/watch?v={video_id}` を構築 | — |
| `channel_follower_count` | `statistics.subscriberCount` (channels.list) | `int(str)`、hidden時は `None` | `None` |
