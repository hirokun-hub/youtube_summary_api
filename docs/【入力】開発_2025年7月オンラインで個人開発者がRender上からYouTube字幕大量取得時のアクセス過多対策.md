---
created: "[[2025-07-05]]"
aliases:
  - ""
関連:
  - ""
tags:
---

【入力】（開発）_2025年7月オンラインで個人開発者がRender上からYouTube字幕大量取得時のアクセス過多対策

### 前提
- 対象ワークロード  
  - [[【法人】Render]] **Starter** インスタンス（0.5 vCPU/512 MB, 上限 \$7/月）  
  - [[YouTube]] 字幕（auto-caption 含む）を API ではなく **スクレイピング/yt-dl 系**で取得  
  - エラー: HTTP 429 “Too Many Requests”

### 原因の2階層構造
| レイヤ | 判定ロジック | 影響範囲 |
|-------|--------------|----------|
| **① データセンターIP制限** | 商用IPレンジはしきい値が住宅回線の 1/10 以下 | [[【法人】Render]] などクラウド全般 |
| **② ソフトBAN** | 一定閾値を超えると IP 単位で[[30–120 min]] ブロック | しばらく待っても 429 が続く |

### 回避策（MECE）
| # | クラス | 方法 | 定量効果 | コスト |
|---|--------|------|---------|-------|
| 1 | **住宅IP利用** | 自宅PC/Raspberry Pi を字幕 API 化し、iPhone Shortcuts から呼ぶ | ほぼ無制限（実測 1000+ 本/日） | 電気代のみ |
| 2 | **Cookie＋UA** | CAPTCHA を解きブラウザ Cookie を `yt-dl` に渡す | 即復帰例多数 | \$0 |
| 3 | **IP分散** | <ul><li>Render を3リージョンに水平展開 → IP×3</li><li>回転住宅プロキシ（Bright Data 等）</li></ul> | 前者: 3倍, 後者: 1000倍 | \$7×台数 / \$12–120+ |
| 4 | **リクエスト制御** | <ul><li>指数バックオフ (30 s→2 m→10 m→1 h)</li><li>`download-archive` で重複防止</li><li>字幕言語を絞る</li></ul> | ブロック前なら 5–20倍長持ち | \$0 |
| 5 | **エッジキャッシュ** | [[【法人】Cloudflare Workers]] + KV/R2 に字幕 JSON を保存 | 原本ヒット 90 %↓ | \$0–5/月 |
| ✗ | **Static Outbound IPs** | IP を“固定”するだけ | 逆効果（集中） | \$0 |

### 推奨フロー
1. **住宅IPサーバ案**  
   - FastAPI + `yt-dl` を自宅で常駐 → `GET /caption?url=&lang=` が VTT を返す  
   - 公開は <br> • [[【法人】Tailscale]] Funnel (`https://xxxx.ts.net`) <br> • [[【法人】Cloudflare Tunnel]]  
2. iPhone Shortcuts  
   - `URL` → `Get Contents of URL` → `Dictionary Value (text)` で字幕取得 → 保存/読み上げ  
3. 429 なら Cookie 注入 → まだ出るならレンジ IP 変更 → それでも出るなら住宅IPへ全面移行。

### 実装スニペット（FastAPI）
```python
from fastapi import FastAPI, HTTPException
import subprocess, pathlib, tempfile
app = FastAPI()

@app.get("/caption")
def caption(video: str, lang: str = "ja"):
    with tempfile.TemporaryDirectory() as td:
        cmd = ["yt-dlp", "--skip-download", "--write-auto-sub",
               "--sub-lang", lang, "--convert-subs", "vtt",
               "-o", f"{td}/%(id)s.%(ext)s", video]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            raise HTTPException(502, r.stderr[-400:])
        file = next(pathlib.Path(td).glob("*.vtt"))
        return {"text": file.read_text(encoding="utf-8")}
````

### 日付・費用の目安

- 本検証時期 [[2025-07-05]]
    
- [[【法人】Render]] Starter : $7/月上限（秒課金 $0.0097/h）
    
- 帯域超過 : $15/100 GB
    
- 回転住宅プロキシ : $12/GB〜
    
- [[【法人】Tailscale]] Funnel & [[【法人】Cloudflare]] Tunnel: 無料枠あり
    

### まとめ

- **429 を根本的に消す最短ルート**＝住宅回線で字幕 API サーバを立て Shortcuts から叩く。
    
- Render で粘るなら **Cookie＋UA** → **IP分散** の順で漸減策。
    
- **Static Outbound IPs は対策にならない**（むしろ悪化）。
    
- 最後に、ローカルキャッシュや Workers キャッシュを組み合わせれば世界規模でもレートを大幅に削減可能。