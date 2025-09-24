
from bs4 import BeautifulSoup
import requests, re, unicodedata

MAX_PER_CATEGORY = 5

def preprocess_text(raw: str) -> str:
    if not raw:
        return ""
    txt = unicodedata.normalize("NFKC", raw)
    noise_keys = ["最近見た求人","おすすめ求人","会員登録","キーワードで探す","スカウト","応募履歴","関連の求人","閲覧履歴","人気のキーワード","この求人を保存"]
    for k in noise_keys:
        txt = txt.replace(k, " ")
    txt = re.sub(r"[ \t\u3000]+", " ", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()

RULES_BASE = {
  "仕事内容・募集条件":[
    {"pattern": r"やりがい|夢を実現|情熱|根性|気合|精神論", "weight": 1, "reason": "抽象語で仕事内容が曖昧"},
    {"pattern": r"未経験\s*歓迎|学歴\s*不問|経歴\s*不問|ポテンシャル採用|人物重視", "weight": 1, "reason": "要件が甘く大量採用/高離職の懸念"},
    {"pattern": r"幹部候補|すぐに.*?昇進|キャリアアップ.*?(約束|確約|保証)", "weight": 2, "reason": "過度な昇進保証は誇大表示の懸念"},
    {"pattern": r"(\bノルマ\b|厳しい目標|高いKPI|KPI至上主義)", "weight": 2, "reason": "過度な数値プレッシャーの示唆"},
    {"pattern": r"(0→1|ゼロイチ|何でもやる|マルチロール)", "weight": 2, "reason": "役割不明確・過重負荷の恐れ"},
  ],
  "給与・待遇":[
    {"pattern": r"上限\s*なし|青天井|年収.*?(可能|上限なし)|高収入", "weight": 2, "reason": "歩合依存/不安定収入の懸念"},
    {"pattern": r"(歩合|出来高|インセンティブ)(のみ|中心|比率が高い)?", "weight": 1, "reason": "固定給依存度が低い可能性"},
    {"pattern": r"(固定給|基本給)\s*(未記載|不明|なし)", "weight": 3, "reason": "最低保障不明（高リスク）"},
    {"pattern": r"固定残業\s*(\d+)\s*時間|みなし.*?(\d+)\s*時間", "weight": 3, "reason": "固定/みなし残業の内包"},
    {"pattern": r"残業代.*?(不支給|なし|込み|含む)", "weight": 3, "reason": "残業代不支給/込み"},
    {"pattern": r"試用期間.*?(減額|給与.*?下がる|手当.*?なし)", "weight": 2, "reason": "過度な試用条件"},
    {"pattern": r"交通費.*?(支給なし|自費)", "weight": 1, "reason": "基本的な手当が出ない"},
  ],
  "勤務時間・休日":[
    {"pattern": r"裁量労働(制)?", "weight": 2, "reason": "時間管理/残業代不透明の恐れ"},
    {"pattern": r"みなし残業|固定残業|フレックスタイム.*?コアなし", "weight": 2, "reason": "残業代実質不払い/際限ない稼働の懸念"},
    {"pattern": r"残業\s*代.*?なし|残業代は支給しません", "weight": 3, "reason": "違法の可能性（最重大リスク）"},
    {"pattern": r"(週休|休日).*(不定|シフト制のみ|応相談のみ)", "weight": 2, "reason": "休日体制が不透明"},
    {"pattern": r"(深夜|早朝).*(対応|勤務)|長時間.*?勤務", "weight": 1, "reason": "長時間/変則労働の示唆"},
  ],
  "勤務地・募集人数":[
    {"pattern": r"全国各地|日本全国|海外\s*あり|転勤\s*あり", "weight": 1, "reason": "配属不透明/転勤リスク"},
    {"pattern": r"(大量|大規模)\s*募集|\b(50|100|200|300)\s*名\s*以上", "weight": 2, "reason": "高離職/人海戦術の懸念"},
    {"pattern": r"勤務地\s*(未記載|不明|応相談のみ)", "weight": 2, "reason": "勤務地が特定できない"},
  ],
  "社風・福利厚生":[
    {"pattern": r"アットホーム|社員は家族|一体感|体育会系|家族のよう", "weight": 1, "reason": "精神論でハードワークを正当化の恐れ"},
    {"pattern": r"社員旅行|イベント多数|飲み会.*?多数|毎週飲み会", "weight": 1, "reason": "プライベート侵食の懸念"},
    {"pattern": r"(社会保険|厚生年金|雇用保険|労災|有給|産休|育休).*(未記載|不明|記載なし)", "weight": 3, "reason": "法定福利の不備（最重大リスク）"},
  ],
}

SAFE_GUARDS = {
  "給与・待遇":[
    {"pattern": r"基本給\s*[\d,]+\s*円|固定給\s*[\d,]+\s*円", "negative_weight": 1, "note":"基本給が明記"},
    {"pattern": r"賞与\s*(年\d回|あり)", "negative_weight": 1, "note":"賞与制度あり"},
  ],
  "勤務時間・休日":[
    {"pattern": r"残業代.*?(全額|法令どおり|1分単位|別途支給)", "negative_weight": 2, "note":"残業代の適正支給を明記"},
    {"pattern": r"完全?週休\s*2日|年間休日\s*(120|125|130)\s*日", "negative_weight": 1, "note":"休日制度が明確/十分"},
    {"pattern": r"平均残業\s*(20|30)\s*時間", "negative_weight": 1, "note":"残業実績が控えめ"},
  ],
  "社風・福利厚生":[
    {"pattern": r"社会保険.*?完備|各種社会保険完備", "negative_weight": 2, "note":"法定福利を明記"},
    {"pattern": r"(有給|産休|育休).*(取得実績|100%|推奨|復帰率)", "negative_weight": 1, "note":"休暇取得の実績/推奨を明記"},
  ],
}

THRESHOLDS=[(0,6,"低（比較的安全）"),(7,12,"中（注意が必要）"),(13,999,"高（ブラックの可能性大）")]

def fetch_text_from_url(url:str)->str:
  try:
    r=requests.get(url,headers={"User-Agent":"Mozilla/5.0"},timeout=20); r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser")
    for t in soup(["script","style","noscript"]): t.decompose()
    text=soup.get_text("\n")
    text=re.sub(r"\n{2,}","\n",text)
    return preprocess_text(text)[:80000]
  except Exception:
    return ""

def _collect_evidence(text: str, pattern: str, window: int = 40) -> list[str]:
  out = []
  for m in re.finditer(pattern, text, flags=re.IGNORECASE|re.DOTALL):
    s = max(0, m.start()-window); e = min(len(text), m.end()+window)
    snippet = text[s:e].replace("\n"," ")
    out.append(snippet)
    if len(out) >= 3: break
  return out

def score_text(text: str, sector: str | None = None):
  text = preprocess_text(text or "")
  cat_scores = {}; cat_hits = {}; cat_safe_hits = {}; cat_evidence = {}
  for cat, rs in RULES_BASE.items():
    score = 0; hits = []; evidence=[]
    for rule in rs:
      if re.search(rule["pattern"], text, flags=re.IGNORECASE|re.DOTALL):
        score += rule["weight"]
        hits.append({"pattern": rule["pattern"], "weight": rule["weight"], "reason": rule["reason"], "category": cat})
        evidence.extend(_collect_evidence(text, rule["pattern"]))
    safe_hits=[]
    for guard in SAFE_GUARDS.get(cat, []):
      if re.search(guard["pattern"], text, flags=re.IGNORECASE|re.DOTALL):
        score -= guard["negative_weight"]
        safe_hits.append(guard)
    score = max(0, min(score, MAX_PER_CATEGORY))
    cat_scores[cat]=score; cat_hits[cat]=hits; cat_safe_hits[cat]=safe_hits; cat_evidence[cat]=evidence[:3]
  total = sum(cat_scores.values())
  return cat_scores, cat_hits, cat_safe_hits, cat_evidence, total

def label_total(total: int) -> str:
  for lo, hi, label in THRESHOLDS:
    if lo <= total <= hi:
      return label
  return "不明"
