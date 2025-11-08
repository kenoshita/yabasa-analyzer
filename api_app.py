import os, io, base64, math, csv, datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

# CJKフォントが無くてもエラーにしない（表示品質のみ低下）
matplotlib.rcParams['font.family'] = ['Noto Sans CJK JP','Noto Sans JP','Hiragino Sans','MS Gothic','sans-serif']

from rules import (
    score_text, label_total, fetch_text_from_url,
    MAX_PER_CATEGORY, DISPLAY_NAME_MAP
)

# ---- Rate limit / app ----
limiter = Limiter(key_func=get_remote_address, default_limits=['30/minute','200/hour'])
app = FastAPI(title='求人票ヤバさ診断 API (secured)', version='1.6.0')
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda request, exc: HTTPException(status_code=429, detail='レート制限に達しました'))

app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])
app.add_middleware(SlowAPIMiddleware)

# ---- Simple in-memory metrics ----
REQUESTS_TOTAL = 0
REQUESTS_OK = 0
REQUESTS_ERROR = 0

# ---- Bearer token guards (必須/自分専用) ----
def _require_token(request: Request, env_var: str):
    expected = os.environ.get(env_var, "")
    if not expected:
        raise HTTPException(status_code=401, detail=f"{env_var} が未設定です")
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization: Bearer <token> が必要です")
    token = auth.split(" ", 1)[1].strip()
    if token != expected:
        raise HTTPException(status_code=403, detail="無効なトークンです")

def guard_metrics(request: Request):
    _require_token(request, "METRICS_TOKEN")

def guard_health(request: Request):
    _require_token(request, "HEALTH_TOKEN")

def _has_static():
    return os.path.isdir('static') and os.path.isfile(os.path.join('static','index.html'))

@app.get('/', response_class=HTMLResponse)
def root_page():
    if _has_static():
        return FileResponse(os.path.join('static','index.html'))
    return HTMLResponse("<html><meta charset='utf-8'><body><h1>セットアップ中</h1></body></html>")

if os.path.isdir('static'):
    app.mount('/ui', StaticFiles(directory='static', html=True), name='static_ui')

class AnalyzeIn(BaseModel):
    url: str | None = None
    text: str | None = None
    sector: str | None = None
    mode: str | None = None  # standard|strict|lenient

def _radar_png64(scores: dict, measured_flags: dict) -> str:
    cats = list(scores.keys())
    if not cats:
        return ""
    labels = [(DISPLAY_NAME_MAP.get(c, c) + (' (測定不能)' if not measured_flags.get(c, True) else '')) for c in cats]
    vals = [scores[c] for c in cats]
    N = len(cats)
    ang = [n/float(N)*2*math.pi for n in range(N)]
    vals += vals[:1]; ang += ang[:1]
    fig, ax = plt.subplots(figsize=(6,6), subplot_kw=dict(polar=True))
    ax.plot(ang, vals, linewidth=2)
    ax.fill(ang, vals, alpha=.25)
    ax.set_xticks(ang[:-1]); ax.set_xticklabels(labels, fontsize=10)
    ax.set_yticks(range(0, MAX_PER_CATEGORY+1)); ax.set_yticklabels([str(i) for i in range(0, MAX_PER_CATEGORY+1)])
    ax.grid(True)
    buf = io.BytesIO(); fig.savefig(buf, format='png', dpi=160, bbox_inches='tight'); plt.close(fig); buf.seek(0)
    return base64.b64encode(buf.read()).decode('ascii')

def _scale_legend():
    return {
        "scale":"0〜5（0=問題なし / 5=大いに問題あり）",
        "detail":[
            {"score":0, "meaning":"該当リスクなし（または安全記述あり）"},
            {"score":1, "meaning":"軽微な懸念（やや曖昧）"},
            {"score":2, "meaning":"懸念あり（要注意の文言が複数）"},
            {"score":3, "meaning":"中程度（制度・条件が不透明）"},
            {"score":4, "meaning":"高いリスク（違法/過重労働の示唆等）"},
            {"score":5, "meaning":"非常に高い（強いサインが繰り返し）"}
        ]
    }

def _log_usage(request: Request, source: str, total: int, label: str, mode: str, sector: str | None):
    try:
        if os.environ.get("ENABLE_LOG", "1") != "1":
            return
        os.makedirs("logs", exist_ok=True)
        path = os.path.join("logs", "usage.csv")
        is_new = not os.path.exists(path)
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if is_new:
                w.writerow(["ts_iso","ip","source","total","label","mode","sector","ua"])
            ua = request.headers.get("user-agent","-")
            ts = datetime.datetime.utcnow().isoformat()
            ip = request.client.host if request.client else "-"
            w.writerow([ts, ip, source, total, label, mode, sector or "", ua])
    except Exception:
        pass

@app.get('/healthz', dependencies=[Depends(guard_health)])
@limiter.limit('10/second')
def healthz(request: Request):
    return {'ok': True}

@app.get('/metrics', response_class=PlainTextResponse, dependencies=[Depends(guard_metrics)])
def metrics(request: Request):
    lines = [
        f'yabasa_requests_total {REQUESTS_TOTAL}',
        f'yabasa_requests_ok {REQUESTS_OK}',
        f'yabasa_requests_error {REQUESTS_ERROR}',
    ]
    return "\n".join(lines) + "\n"

@app.post('/analyze')
@limiter.limit('10/second')
def analyze(request: Request, inp: AnalyzeIn):
    global REQUESTS_TOTAL, REQUESTS_OK, REQUESTS_ERROR
    REQUESTS_TOTAL += 1
    try:
        mode = (inp.mode or 'standard').lower()
        body=(inp.text or '').strip(); src='text'
        if not body and inp.url:
            got=fetch_text_from_url(inp.url)
            if not got:
                REQUESTS_ERROR += 1
                raise HTTPException(status_code=400, detail='URLの取得に失敗。本文貼り付けでお試しください。')
            body=got; src='url'
        if not body:
            REQUESTS_ERROR += 1
            raise HTTPException(status_code=400, detail='入力が空です。url か text のどちらかを指定してください。')

        cat_scores, cat_hits, cat_safe_hits, cat_evidence, total, measured_flags = score_text(body, sector=inp.sector)

        reasons=[]
        for cat, hits in cat_hits.items():
            for h in hits:
                reasons.append({'category':DISPLAY_NAME_MAP.get(cat, cat),'reason':h['reason'],'weight':h['weight']})
        reasons.sort(key=lambda x:(-x['weight'], x['category']))

        label = label_total(total)
        max_cat = max(cat_scores.values()) if cat_scores else 0
        safe_count = sum(len(v) for v in cat_safe_hits.values())
        if mode == 'strict':
            if max_cat >= 4 or total >= 12:
                label = '高（ブラックの可能性大）'
        elif mode == 'lenient':
            if label.startswith('高') and safe_count >= 2 and total <= 14:
                label = '中（注意が必要）'

        png64=_radar_png64(cat_scores, measured_flags)

        ev_list=[]
        for cat, snippets in cat_evidence.items():
            for sn in snippets:
                ev_list.append({'category':DISPLAY_NAME_MAP.get(cat, cat), 'snippet':sn})
        ev_list = ev_list[:12]

        REQUESTS_OK += 1
        _log_usage(request, src, total, label, mode, inp.sector)

        return {
            'source':src,
            'sector':inp.sector,
            'mode': mode,
            'total':total,
            'label':label,
            'category_scores':{DISPLAY_NAME_MAP.get(k,k):v for k,v in cat_scores.items()},
            'measured_flags':{DISPLAY_NAME_MAP.get(k,k):bool(measured_flags.get(k, True)) for k in cat_scores.keys()},
            'scale_legend': _scale_legend(),
            'top_reasons':reasons[:10],
            'evidence': ev_list,
            'chart_png_base64':png64,
            'notice': "「測定不能」は該当カテゴリにヒット無しの場合に表示。0点＝安全ではなく『懸念が検出されなかった』の意味。",
        }
    except HTTPException:
        raise
    except Exception as e:
        REQUESTS_ERROR += 1
        raise HTTPException(status_code=500, detail=f'サーバーエラー: {str(e)}')
