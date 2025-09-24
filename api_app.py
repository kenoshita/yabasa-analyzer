import os, io, base64, math, matplotlib
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import matplotlib.pyplot as plt
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

matplotlib.rcParams['font.family'] = ['Noto Sans CJK JP','Noto Sans JP','Hiragino Sans','MS Gothic','sans-serif']

from rules import score_text, label_total, fetch_text_from_url, MAX_PER_CATEGORY
from metrics import record as metrics_record, summary as metrics_summary

limiter = Limiter(key_func=get_remote_address, default_limits=['30/minute','200/hour'])

app = FastAPI(title='求人票ヤバさ診断API（SAFE）', version='1.3.0')
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda request, exc: HTTPException(status_code=429, detail='レート制限に達しました'))

app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])
app.add_middleware(SlowAPIMiddleware)

# SAFE static mounts
if os.path.isdir('static'):
    app.mount('/', StaticFiles(directory='static', html=True), name='static_root')
else:
    @app.get('/', response_class=HTMLResponse)
    def _fallback_root():
        return """<html><meta charset='utf-8'><body>
        <h1>セットアップ中</h1>
        <p>static/ フォルダが見つからないため、簡易ページを表示しています。</p>
        <p>GitHub に <code>static/index.html</code> を置いて再デプロイしてください。</p>
        </body></html>"""

if os.path.isdir('landing'):
    app.mount('/landing', StaticFiles(directory='landing', html=True), name='landing')

class AnalyzeIn(BaseModel):
    url: str | None = None
    text: str | None = None
    sector: str | None = None

def _radar_png64(scores: dict) -> str:
    import matplotlib.pyplot as plt
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
def healthz(request: Request): return {'ok': True}

class TrackIn(BaseModel):
    path: str
    ref: str | None = None

@app.post('/metrics/track')
@limiter.limit('20/second')
def metrics_track(request: Request, inp: TrackIn):
    client_ip = request.client.host if request.client else ''
    metrics_record(page_path=inp.path, ip=client_ip, user_agent=request.headers.get('user-agent',''), ref=(inp.ref or ''))
    return {'ok': True}

@app.get('/metrics/summary')
def metrics_summary_api(): return metrics_summary()

@app.get('/metrics/dashboard', response_class=HTMLResponse)
def metrics_dashboard():
    s=metrics_summary()
    rows_day=''.join(f"<tr><td>{d}</td><td>{v['views']}</td><td>{v['unique_ips']}</td></tr>" for d,v in sorted(s['by_day'].items()))
    rows_path=''.join(f"<tr><td>{p}</td><td>{v['views']}</td></tr>" for p,v in sorted(s['by_path'].items()))
    return HTMLResponse(f"""<html><meta charset='utf-8'><body style='font-family:sans-serif'>
    <h1>Metrics</h1><h2>By Day</h2><table border='1'><tr><th>Day</th><th>Views</th><th>Unique</th></tr>{rows_day}</table>
    <h2>By Path</h2><table border='1'><tr><th>Path</th><th>Views</th></tr>{rows_path}</table></body></html>""")

@app.post('/analyze')
@limiter.limit('10/second')
def analyze(inp: AnalyzeIn):
    body=(inp.text or '').strip(); src='text'
    if not body and inp.url:
        got=fetch_text_from_url(inp.url)
        if not got: raise HTTPException(status_code=400, detail='URLの取得に失敗。本文貼り付けでお試しください。')
        body=got; src='url'
    if not body: raise HTTPException(status_code=400, detail='入力が空です。url か text のどちらかを指定してください。')
    cat_scores, cat_hits, cat_safe_hits, total = score_text(body, sector=inp.sector)
    label=label_total(total); png64=_radar_png64(cat_scores)
    reasons=[]
    for cat,hits in cat_hits.items():
        for h in hits: reasons.append({'category':cat,'reason':h['reason'],'weight':h['weight']})
    reasons.sort(key=lambda x:(-x['weight'], x['category']))
    uniq=[]; seen=set()
    for r in reasons:
        k=(r['category'], r['reason'])
        if k not in seen: seen.add(k); uniq.append(r)
    return {'source':src,'sector':inp.sector,'total':total,'label':label,'category_scores':cat_scores,'top_reasons':uniq[:8],'chart_png_base64':png64}
