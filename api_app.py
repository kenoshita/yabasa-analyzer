# api_app.py
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

from rules import (
    score_text, label_total, fetch_text_from_url,
    MAX_PER_CATEGORY, preprocess_text, CATEGORY_ORDER
)

limiter = Limiter(key_func=get_remote_address, default_limits=['30/minute','200/hour'])

app = FastAPI(title='求人票ヤバさ診断API v4.3', version='1.5.0')
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

def _radar_png64(cat_scores: dict, measured: dict, total: int, label: str) -> str:
    # カテゴリを固定順で並べる
    cats = CATEGORY_ORDER[:]
    vals = [cat_scores.get(c, 0) for c in cats]

    # ラベルに測定不能を付記（measured=False）
    disp = []
    for c in cats:
        if measured.get(c, False):
            disp.append(c)
        else:
            disp.append(f"{c}\n（測定不能）")

    N=len(cats)
    ang=[n/float(N)*2*math.pi for n in range(N)]
    vals+=vals[:1]; ang+=ang[:1]

    fig,ax=plt.subplots(figsize=(7,7), subplot_kw=dict(polar=True))
    # スコアポリゴン
    ax.plot(ang, vals, linewidth=2)
    ax.fill(ang, vals, alpha=.25)

    # 目盛り
    ax.set_xticks(ang[:-1]); ax.set_xticklabels(disp, fontsize=10)
    ax.set_yticks(range(0, MAX_PER_CATEGORY+1))
    ax.set_yticklabels([str(i) for i in range(0, MAX_PER_CATEGORY+1)])

    # タイトル領域に総合スコアを大きく
    ax.set_title(f"総合スコア {total} ／ {label}", fontsize=16, pad=24)

    # 凡例（0〜5の意味）
    fig.text(
        0.5, 0.02,
        "スコア凡例：0＝問題なし　1＝軽微　2＝小　3＝中　4＝大　5＝大いに問題あり　／　※「（測定不能）」は情報不足で判定不可",
        ha="center", va="bottom", fontsize=10
    )

    buf=io.BytesIO()
    fig.savefig(buf, format='png', dpi=160, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
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

    cat_scores, cat_hits, cat_safe_hits, cat_evidence, total, cat_measured, improvements = score_text(body, sector=inp.sector)

    # ラベル判定の前後でモード補正（既存仕様を踏襲しつつ順序を明確化）
    label = label_total(total)
    max_cat = max(cat_scores.values()) if cat_scores else 0
    safe_count = sum(len(v) for v in cat_safe_hits.values())

    if mode == 'strict':
        if max_cat >= 4 or total >= 12:
            label = '高（ブラックの可能性大）'
    elif mode == 'lenient':
        if label.startswith('高') and safe_count >= 2 and total <= 14:
            label = '中（注意が必要）'

    png64=_radar_png64(cat_scores, cat_measured, total, label)

    # エビデンスは少なすぎると冗長なので最大12件
    ev_list=[]
    for cat, snippets in cat_evidence.items():
        for sn in snippets:
            ev_list.append({'category':cat, 'snippet':sn})
    ev_list = ev_list[:12]

    # フロント側でそのまま出せるよう整形
    reasons=[]
    for cat, hits in cat_hits.items():
        for h in hits:
            reasons.append({'category':cat,'reason':h['reason'],'weight':h['weight']})
    reasons.sort(key=lambda x:(-x['weight'], x['category']))

    return {
        'source':src,
        'sector':inp.sector,
        'mode': mode,
        'total':total,
        'label':label,
        'category_scores':{c: cat_scores.get(c,0) for c in CATEGORY_ORDER},
        'category_measured':{c: bool(cat_measured.get(c, False)) for c in CATEGORY_ORDER},
        'top_reasons':reasons[:10],
        'evidence': ev_list,
        'improvements': improvements[:20],
        'chart_png_base64':png64
    }
