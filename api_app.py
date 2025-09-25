
import os, io, base64, math, matplotlib
matplotlib.use('Agg')
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import matplotlib.pyplot as plt
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

matplotlib.rcParams['font.family'] = ['Noto Sans CJK JP','Noto Sans JP','Hiragino Sans','MS Gothic','sans-serif']

from rules import score_text, label_total, fetch_text_from_url, MAX_PER_CATEGORY, preprocess_text

limiter = Limiter(key_func=get_remote_address, default_limits=['30/minute','200/hour'])

app = FastAPI(title='求人票ヤバさ診断API v4.2', version='1.4.2')
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda request, exc: HTTPException(status_code=429, detail='レート制限に達しました'))

app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])
app.add_middleware(SlowAPIMiddleware)

def _has_static():
    return os.path.isdir('static') and os.path.isfile(os.path.join('static','index.html'))

@app.get('/', response_class=HTMLResponse)
def root_page():
    if _has_static():
        return FileResponse(os.path.join('static','index.html'))
    return HTMLResponse("""<html><meta charset='utf-8'><body>
    <h1>セットアップ中</h1>
    <p>static/index.html を配置して再デプロイしてください。</p>
    </body></html>""", status_code=200)

if os.path.isdir('static'):
    app.mount('/ui', StaticFiles(directory='static', html=True), name='static_ui')
if os.path.isdir('landing'):
    app.mount('/landing', StaticFiles(directory='landing', html=True), name='landing')

class AnalyzeIn(BaseModel):
    url: str | None = None
    text: str | None = None
    sector: str | None = None
    mode: str | None = None

def _radar_png64(scores: dict) -> str:
    cats=list(scores.keys()); vals=[scores[c] for c in cats]
    N=len(cats); ang=[n/float(N)*2*math.pi for n in range(N)]
    vals+=vals[:1]; ang+=ang[:1]
    fig,ax=plt.subplots(figsize=(6,6), subplot_kw=dict(polar=True))
    ax.plot(ang, vals, linewidth=2); ax.fill(ang, vals, alpha=.3)
    ax.set_xticks(ang[:-1]); ax.set_xticklabels(cats, fontsize=10)
    ax.set_yticks(range(0, MAX_PER_CATEGORY+1)); ax.set_yticklabels([str(i) for i in range(0, MAX_PER_CATEGORY+1)])
    buf=io.BytesIO(); fig.savefig(buf, format='png', dpi=160, bbox_inches='tight'); plt.close(fig); buf.seek(0)
    return base64.b64encode(buf.read()).decode('ascii')

@app.get('/healthz')
@limiter.limit('10/second')
def healthz(request: Request):
    return {'ok': True}

@app.post('/analyze')
@limiter.limit('10/second')
def analyze(request: Request, inp: AnalyzeIn):
    mode = (inp.mode or 'standard').lower()
    body=(inp.text or '').strip(); src='text'
    if not body and inp.url:
        got=fetch_text_from_url(inp.url)
        if not got:
            raise HTTPException(status_code=400, detail='URLの取得に失敗。本文貼り付けでお試しください。')
        body=got; src='url'
    if not body:
        raise HTTPException(status_code=400, detail='入力が空です。url か text のどちらかを指定してください。')
    cat_scores, cat_hits, cat_safe_hits, cat_evidence, total = score_text(body, sector=inp.sector)
    reasons=[]
    for cat, hits in cat_hits.items():
        for h in hits:
            reasons.append({'category':cat,'reason':h['reason'],'weight':h['weight']})
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
    png64=_radar_png64(cat_scores)
    ev_list=[]
    for cat, snippets in cat_evidence.items():
        for sn in snippets:
            ev_list.append({'category':cat, 'snippet':sn})
    ev_list = ev_list[:12]
    return {
        'source':src,
        'sector':inp.sector,
        'mode': mode,
        'total':total,
        'label':label,
        'category_scores':cat_scores,
        'top_reasons':reasons[:10],
        'evidence': ev_list,
        'chart_png_base64':png64
    }
