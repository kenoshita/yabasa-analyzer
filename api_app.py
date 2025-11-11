import os, io, base64, math, csv, datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from fastapi import FastAPI, HTTPException, Request, Depends, Body
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

# 日本語フォント（無くてもエラーにしない）
matplotlib.rcParams['font.family'] = ['Noto Sans CJK JP','Noto Sans JP','Hiragino Sans','MS Gothic','sans-serif']

from rules import (
    score_text, label_total, fetch_text_from_url,
    MAX_PER_CATEGORY, DISPLAY_NAME_MAP
)

# ---- App / RateLimit ----
limiter = Limiter(key_func=get_remote_address, default_limits=['30/minute','200/hour'])
app = FastAPI(title='求人票ヤバさ診断 API (seekers-concerns)', version='1.7.0')
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda request, exc: HTTPException(status_code=429, detail='レート制限に達しました'))

app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])
app.add_middleware(SlowAPIMiddleware)

# ---- Optional simple counters (used by /metrics if実装済み) ----
REQUESTS_TOTAL = 0
REQUESTS_OK = 0
REQUESTS_ERROR = 0

# （もし /metrics /healthz をトークン保護している運用なら以下ガードを維持）
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

# ---- 求職者向け「主な懸念点」生成（文面だけ求職者向け。キー名は recommendations のまま） ----
def _concerns_for_seekers(cat_hits: dict, cat_scores: dict) -> list[dict]:
    out = []
    def add(cat_display, msg):
        out.append({"category": cat_display, "suggestion": msg})

    for cat, hits in cat_hits.items():
        disp = DISPLAY_NAME_MAP.get(cat, cat)
        score = cat_scores.get(cat, 0)
        if score < 2 and not hits:
            continue

        # 1カテゴリあたり最大3件まで
        used = 0
        for h in hits:
            r = h.get("reason","") + " " + h.get("pattern","")
            suggestion = None

            s = r
            if any(k in s for k in ["みなし残業", "固定残業"]):
                suggestion = "「みなし残業の超過分の支給」「みなしの算定根拠」は誤読の可能性あり。面接時に要チェック。"
            elif "残業代" in s and any(k in s for k in ["なし","込み","含む"]):
                suggestion = "残業代の支給有無・上限の条件は誤読の可能性あり。就業規則とセットで確認。"
            elif any(k in s for k in ["月平均", "長時間", "60", "80"]):
                suggestion = "実残業の平均/繁忙期の上限、36協定の範囲は誤差が出やすい。面接で数値ベースで確認。"
            elif any(k in s for k in ["未経験歓迎", "未経験　歓迎", "未経験大歓迎"]):
                suggestion = "未経験向けの教育体制・OJT期間・担当切り出しまでの目安を要確認。"
            elif any(k in s for k in ["若手活躍", "20代が中心", "20代中心", "若い人でも活躍"]):
                suggestion = "年齢構成と平均在籍年数、早期離職率を確認。若年比率が高い理由次第で環境は大きく変わる。"
            elif any(k in s for k in ["インセンティブ", "歩合", "出来高"]):
                suggestion = "固定給の割合、歩合の算定式/対象期間、未達時の保証は誤読の可能性あり。要チェック。"
            elif any(k in s for k in ["繁忙期", "土曜出勤"]):
                suggestion = "繁忙期の休日運用と振休取得率、月45h/年360hの上限管理を確認。"
            elif any(k in s for k in ["社員旅行", "飲み会"]):
                suggestion = "参加の任意性・頻度・費用負担は誤解が生じやすい。就業時間外の扱いも確認。"
            elif any(k in s for k in ["ノルマ", "KPI", "厳しい目標"]):
                suggestion = "目標未達時の扱い（減給・配置転換等）と評価軸の透明性は面接時に数値で確認。"
            elif any(k in s for k in ["0→1", "何でもやる", "マルチロール"]):
                suggestion = "想定業務の範囲・優先順位・ヘルプ体制を確認。役割曖昧さは残業増の温床になりやすい。"
            elif "年収幅が広すぎる" in s or "SALARY_RANGE_WIDE" in s:
                suggestion = "想定年収の中央値・達成者割合・評価サイクルを確認。中央値で生活設計を。"

            if suggestion:
                add(disp, suggestion)
                used += 1
                if used >= 3:
                    break

        if used == 0 and score >= 2:
            # 一般形（カテゴリ名だけで警告）
            add(disp, "この項目は表現が曖昧/情報不足の可能性あり。面接時に具体例と数値で裏取りを。")

    # 全体で最大12件に丸め
    return out[:12]

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

        # 上位理由
        reasons=[]
        for cat, hits in cat_hits.items():
            for h in hits:
                reasons.append({'category':DISPLAY_NAME_MAP.get(cat, cat),'reason':h['reason'],'weight':h['weight']})
        reasons.sort(key=lambda x:(-x['weight'], x['category']))

        # ラベル（モード補正）
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

        # エビデンス（赤ハイライト済）
        ev_list=[]
        for cat, snippets in cat_evidence.items():
            for sn in snippets:
                ev_list.append({'category':DISPLAY_NAME_MAP.get(cat, cat), 'snippet':sn})
        ev_list = ev_list[:12]

        # 求職者向けの主な懸念点
        concerns = _concerns_for_seekers(cat_hits, cat_scores)

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
            'recommendations': concerns,     # ← UIはこのキーを読んで表示
            'chart_png_base64':png64,
            'notice': "「測定不能」は該当カテゴリにヒット無しの場合に表示。0点＝安全ではなく『懸念が検出されなかった』の意味。"
        }
    except HTTPException:
        raise
    except Exception as e:
        REQUESTS_ERROR += 1
        raise HTTPException(status_code=500, detail=f'サーバーエラー: {str(e)}')

# --- 管理ダッシュボード（サマリーのみ；既存のadmin.html/jsに合わせて利用） ---
@app.post('/admin/data')
def admin_data(payload: dict = Body(...)):
    password = (payload or {}).get('password', '')
    expected = os.environ.get("ADMIN_PASS", "")
    if not expected or password != expected:
        raise HTTPException(status_code=401, detail="パスワード不一致")

    path = os.path.join("logs","usage.csv")
    daily = {}
    labels = {"低":0,"中":0,"高":0}
    total = 0
    if os.path.exists(path):
        with open(path, newline='', encoding='utf-8') as f:
            r = csv.DictReader(f)
            for row in r:
                total += 1
                day = (row.get("ts_iso") or "")[:10]
                if day:
                    daily[day] = daily.get(day,0)+1
                lb = (row.get("label") or "")[:1]
                if lb in labels: labels[lb]+=1

    days = sorted(daily.keys())
    if len(days) > 7:
        days = days[-7:]
    daily_values = [daily.get(d,0) for d in days]

    return {
        "total_requests": total,
        "by_label": {"low": labels["低"], "mid": labels["中"], "high": labels["高"]},
        "daily": {"labels": days, "values": daily_values},
    }
