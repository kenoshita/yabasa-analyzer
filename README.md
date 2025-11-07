# 求人票ヤバさ診断（Complete）

- API: FastAPI（/analyze）
- UI: `/ui`（`static/index.html`）
- レート制限: `30/min`, `200/hour`
- ログ: `logs/usage.csv`
- メトリクス: `/metrics`（簡易 Prometheus）

## 使い方（ローカル）
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ENABLE_LOG=1
uvicorn api_app:app --reload
# ブラウザで http://localhost:8000/ui
```

## Docker
```bash
docker build -t yabasa:complete .
docker run --rm -p 8000:8000 -e ENABLE_LOG=1 -v $(pwd)/logs:/app/logs yabasa:complete
# http://localhost:8000/ui
```

## API
- `POST /analyze`
```json
{ "url": "https://...", "text": "本文", "mode":"standard|strict|lenient" }
```
- レスポンスには以下を含みます：
  - `total`（総合スコア）, `label`（総合ラベル）
  - `category_scores`（カテゴリ別スコア 0-5）
  - `measured_flags`（true=測定済 / false=測定不能）
  - `chart_png_base64`（レーダーチャートPNG）
  - `scale_legend`（スコアの見方 0〜5）
  - `top_reasons`, `evidence`, `recommendations`

## ログ / メトリクス
- `logs/usage.csv` に以下を追記します：
  - `ts_iso, ip, source(text|url), total, label, mode, sector, ua`
- `/metrics` は以下を返します：
  - `yabasa_requests_total`, `yabasa_requests_ok`, `yabasa_requests_error`

## 注意
- 「測定不能」判定は、該当カテゴリにヒットが一切無い場合に表示されます。
- 0点＝安全 ではなく **「該当する懸念が検出されなかった」** の意味です。情報不足の場合は「測定不能」になります。