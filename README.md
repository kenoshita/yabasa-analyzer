# 求人票ヤバさ診断（Final）

- API: FastAPI（/analyze）
- UI: `/ui`（`static/index.html`）
- レート制限: `30/min`, `200/hour`
- ログ: `logs/usage.csv`
- メトリクス: `/metrics`（簡易 Prometheus）
- 免責事項: UI下部に掲示

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
docker build -t yabasa:final .
docker run --rm -p 8000:8000 -e ENABLE_LOG=1 -v $(pwd)/logs:/app/logs yabasa:final
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
  - `top_reasons`, `evidence`（赤マーク付き）, `recommendations`

## 注意・免責（UIにも掲載）
- 「測定不能」判定は、該当カテゴリにヒットが一切無い場合に表示されます。
- 0点＝安全 ではなく **「該当する懸念が検出されなかった」** の意味です。情報不足の場合は「測定不能」になります。
- 本診断は自動解析であり、企業の実態・法令遵守を保証するものではありません。最終判断は自己責任でお願いします。