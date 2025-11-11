import os, io, base64, math, csv, datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# CJKフォント（無い環境でも落ちません。見た目のみ低下）
matplotlib.rcParams['font.family'] = ['Noto Sans CJK JP','Noto Sans JP','Hiragino Sans','MS Gothic','sans-serif']

from rules import (
    score_text, label_total, fetch_text_from_url,
    MAX_PER_CATEGORY, DISPLAY_NAME_MAP
)

app = FastAPI(title='求人票ヤバさ診断 API', version='1.7.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)

def _has_static():
    return os.path.isdir('static') and os.path.isfile(os.path.join('static','index.html'))

@app.get('/', response_class=HTMLResponse)
def root_page():
    if _has_static():
        return FileResponse(os.path.join('static','index.html'))
    return HTMLResponse("<html><meta charset='utf-8'><body><h1>セットアップ中</h1></body></html>")

# /ui で static を配信（既存UIをそのまま使える）
if os.path.isdir('static'):
    app.mount('/ui', StaticFiles(directory='static', html=True), name='static_ui')

class AnalyzeIn(BaseModel):
    url: str | None = None
    text: str | None = None
    sector: str | None = None
    mode: str | None = None  # standard|strict|lenient（※今は使っていませんが将来のため残置）

def _radar_png64(scores: dict, measured_flags: dict) -> str:
    cats = list(scores.keys())
    if not cats:
        return ""
    labels = [
        (DISPLAY_NAME_MAP.get(c, c) + (' (測定不能)' if not measured_flags.get(c, True) else ''))
        for c in cats
    ]
    vals = [scores[c] for c in cats]
    N = len(cats)
    ang = [n/float(N)*2*math.pi for n in range(N)]
    vals += vals[:1]; ang += ang[:1]
    fig, ax = plt.subplots(figsize=(6,6), subplot_kw=dict(polar=True))
    ax.plot(ang, vals, linewidth=2); ax.fill(ang, vals, alpha=.25)
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

def _compose_concerns(cat_scores: dict, measured_flags: dict) -> list[dict]:
    """
    求職者向けの『主な懸念点』生成（UI互換のため recommendations でも返す）
    """
    concerns = []
    for cat, score in cat_scores.items():
        name = DISPLAY_NAME_MAP.get(cat, cat)
        measured = bool(measured_flags.get(cat, True))
        if not measured:
            concerns.append({
                "category": name,
                "suggestion": "情報が少なく誤読の可能性あり。面接時に『具体的な制度・条件（数値・運用実績）』の確認を。"
            })
            continue

        if score >= 5:
            concerns.append({
                "category": name,
                "suggestion": "強い懸念サイン。『残業代の支払方法／月の実残業時間／休日の実運用／評価軸／給与内訳』は面接時に要チェック。"
            })
        elif score == 4:
            concerns.append({
                "category": name,
                "suggestion": "リスク高め。表現が曖昧または負荷の示唆あり。数値や実績で裏付けがあるか確認を。"
            })
        elif score == 3:
            concerns.append({
                "category": name,
                "suggestion": "やや注意。読み違えやすい表現が含まれる可能性。運用ルールや例外条件を聞いて齟齬を防ぐ。"
            })
        # 0〜2は原則表示しない（画面をノイズで埋めない）
    return concerns[:12]

@app.post('/analyze')
def analyze(inp: AnalyzeIn):
    body = (inp.text or '').strip()
    src = 'text'
    if not body and inp.url:
        got = fetch_text_from_url(inp.url)
        if not got:
            raise HTTPException(status_code=400, detail='URLの取得に失敗。本文コピペでお試しください。')
        body = got; src = 'url'
    if not body:
        raise HTTPException(status_code=400, detail='入力が空です。url か text のどちらかを指定してください。')

    # スコアリング
    cat_scores, cat_hits, cat_safe_hits, cat_evidence, total, measured_flags = score_text(body, sector=inp.sector)
    label = label_total(total)

    # 上位理由
    reasons = []
    for cat, hits in cat_hits.items():
        for h in hits:
            reasons.append({
                'category': DISPLAY_NAME_MAP.get(cat, cat),
                'reason': h['reason'],
                'weight': h['weight']
            })
    reasons.sort(key=lambda x: (-x['weight'], x['category']))
    reasons = reasons[:10]

    # 証拠（赤ハイライト入り）
    ev_list = []
    for cat, snippets in cat_evidence.items():
        for sn in snippets:
            ev_list.append({'category': DISPLAY_NAME_MAP.get(cat, cat), 'snippet': sn})
    ev_list = ev_list[:12]

    # レーダー
    png64 = _radar_png64(cat_scores, measured_flags)

    # 求職者向け「主な懸念点」
    concerns = _compose_concerns(cat_scores, measured_flags)

    return {
        'source': src,
        'sector': inp.sector,
        'mode': (inp.mode or 'standard'),
        'total': total,
        'label': label,
        'category_scores': {DISPLAY_NAME_MAP.get(k, k): v for k, v in cat_scores.items()},
        'measured_flags': {DISPLAY_NAME_MAP.get(k, k): bool(measured_flags.get(k, True)) for k in cat_scores.keys()},
        'scale_legend': _scale_legend(),
        'top_reasons': reasons,
        'evidence': ev_list,
        'concerns': concerns,               # ← 新キー（求職者向け文言）
        'recommendations': concerns,        # ← 互換のため既存キーも同じ内容で返す
        'chart_png_base64': png64,
        'notice': "「測定不能」は該当カテゴリにヒットが無い場合に表示。0点=安全ではなく『懸念が検出されなかった』の意味。"
    }

