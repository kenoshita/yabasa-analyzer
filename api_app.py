import os, io, base64, math, csv, datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 日本語フォント（環境にあるものを優先）
matplotlib.rcParams['font.family'] = ['Noto Sans CJK JP','Noto Sans JP','Hiragino Sans','MS Gothic','sans-serif']

from rules import (
    score_text, label_total, fetch_text_from_url,
    MAX_PER_CATEGORY, DISPLAY_NAME_MAP
)

app = FastAPI(title='求人票ヤバさ診断API v5.0', version='1.6.0')

app.add_middleware(
    CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*']
)

# ---- Simple in-memory metrics ----
REQUESTS_TOTAL = 0
REQUESTS_OK = 0
REQUESTS_ERROR = 0

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

class AnalyzeIn(BaseModel):
    url: str | None = None
    text: str | None = None
    sector: str | None = None
    mode: str | None = None  # "standard" | "strict" | "lenient"

def _radar_png64(scores: dict, measured_flags: dict) -> str:
    cats = list(scores.keys())
    labels = [
        (DISPLAY_NAME_MAP.get(c, c) + (' (測定不能)' if not measured_flags.get(c, True) else ''))
        for c in cats
    ]
    vals = [scores[c] for c in cats]
    N = len(cats)
    ang = [n/float(N)*2*math.pi for n in range(N)]
    vals += vals[:1]
    ang  += ang[:1]
    fig, ax = plt.subplots(figsize=(6,6), subplot_kw=dict(polar=True))
    ax.plot(ang, vals, linewidth=2)
    ax.fill(ang, vals, alpha=.25)
    ax.set_xticks(ang[:-1]); ax.set_xticklabels(labels, fontsize=10)
    ax.set_yticks(range(0, MAX_PER_CATEGORY+1))
    ax.set_yticklabels([str(i) for i in range(0, MAX_PER_CATEGORY+1)])
    ax.grid(True)
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=160, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
