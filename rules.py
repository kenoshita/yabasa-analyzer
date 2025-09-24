
from bs4 import BeautifulSoup
import requests, re

MAX_PER_CATEGORY = 5

RULES_BASE = {
  "仕事内容・募集条件":[
    {"pattern": r"やりがい|夢を実現|情熱|根性", "weight": 1, "reason": "抽象語で仕事内容が曖昧"},
    {"pattern": r"未経験\s*歓迎|学歴\s*不問|経歴\s*不問", "weight": 1, "reason": "要件が甘く大量採用/高離職の恐れ"},
    {"pattern": r"幹部候補|すぐに.*?昇進|キャリアアップ.*?(約束|確約|保証)", "weight": 2, "reason": "過度な昇進保証は誇大表示の懸念"},
    {"pattern": r"\bノルマ\b|厳しい目標|高いKPI", "weight": 2, "reason": "過度な数値プレッシャーの示唆"},
  ],
  "給与・待遇":[
    {"pattern": r"上限\s*なし|青天井|年収.*?(可能|上限なし)|高収入", "weight": 2, "reason": "歩合依存/不安定収入の懸念"},
    {"pattern": r"歩合|出来高|インセンティブ", "weight": 1, "reason": "固定給依存度が低い可能性"},
    {"pattern": r"固定給\s*なし|基本給\s*(未記載|不明|なし)", "weight": 3, "reason": "最低保障不明（高リスク）"},
    {"pattern": r"試用期間.*?(減額|給与.*?下がる|手当.*?なし)", "weight": 2, "reason": "過度な試用条件"},
    {"pattern": r"交通費.*?(支給なし|自費)", "weight": 1, "reason": "基本的な手当が出ない"},
  ],
  "勤務時間・休日":[
    {"pattern": r"自己裁量|裁量労働", "weight": 2, "reason": "時間管理/残業代不透明の恐れ"},
    {"pattern": r"みなし残業|固定残業|裁量労働制", "weight": 2, "reason": "残業代実質不払いの懸念"},
    {"pattern": r"残業\s*代.*?なし|残業代は支給しません", "weight": 3, "reason": "違法の可能性（最重大リスク）"},
    {"pattern": r"休日\s*(不定|不明)|週休\s*1", "weight": 2, "reason": "休日体制が不明確/少ない"},
    {"pattern": r"深夜|早朝|長時間.*?勤務", "weight": 1, "reason": "長時間労働の示唆"},
  ],
  "勤務地・募集人数":[
    {"pattern": r"全国各地|日本全国|海外\s*あり|転勤\s*あり", "weight": 1, "reason": "配属不透明/転勤リスク"},
    {"pattern": r"(大量|大規模)\s*募集|\b(50|100|200|300)\s*名\s*以上", "weight": 2, "reason": "高離職/人海戦術の懸念"},
    {"pattern": r"勤務地\s*(未記載|不明|応相談のみ)", "weight": 2, "reason": "勤務地が特定できない"},
  ],
  "社風・福利厚生":[
    {"pattern": r"アットホーム|社員は家族|一体感|体育会系", "weight": 1, "reason": "精神論でハードワークを正当化の恐れ"},
    {"pattern": r"社員旅行|イベント多数|飲み会.*?多数", "weight": 1, "reason": "プライベート侵食の懸念"},
    {"pattern": r"(社会保険|厚生年金|雇用保険|労災|有給|産休|育休).*(未記載|不明|記載なし)", "weight": 3, "reason": "法定福利の不備（最重大リスク）"},
  ],
}

SAFE_GUARDS = {
  "給与・待遇":[{"pattern": r"基本給\s*[\d,]+\s*円|固定給\s*[\d,]+\s*円", "negative_weight": 1, "note":"基本給が明記"}],
  "勤務時間・休日":[{"pattern": r"残業代.*?(全額|法令どおり|1分単位|別途支給)", "negative_weight": 2, "note":"残業代の適正支給を明記"}],
  "社風・福利厚生":[{"pattern": r"社会保険.*?完備|各種社会保険完備", "negative_weight": 2, "note":"法定福利を明記"}],
}

THRESHOLDS=[(0,4,"低（比較的安全）"),(5,9,"中（注意が必要）"),(10,999,"高（ブラックの可能性大）")]

def fetch_text_from_url(url:str)->str:
  try:
    r=requests.get(url,headers={"User-Agent":"Mozilla/5.0"},timeout=20); r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser")
    for t in soup(["script","style","noscript"]): t.decompose()
    txt=soup.get_text("\n")
    return re.sub(r"\n{2,}","\n",txt).strip()[:80000]
  except Exception: return ""

def score_text(text:str, sector:str|None=None):
  text=text or ""; import re as _re
  cat_scores={}; cat_hits={}; cat_safe_hits={}
  for cat,rs in RULES_BASE.items():
    s=0; hits=[]
    for rule in rs:
      if _re.search(rule["pattern"], text, flags=_re.IGNORECASE|_re.DOTALL):
        s+=rule["weight"]; hits.append({"reason":rule["reason"],"weight":rule["weight"]})
    safe=[]
    for guard in SAFE_GUARDS.get(cat,[]):
      if _re.search(guard["pattern"], text, flags=_re.IGNORECASE|_re.DOTALL):
        s-=guard["negative_weight"]; safe.append(guard)
    s=max(0,min(s,MAX_PER_CATEGORY))
    cat_scores[cat]=s; cat_hits[cat]=hits; cat_safe_hits[cat]=safe
  total=sum(cat_scores.values())
  return cat_scores,cat_hits,cat_safe_hits,total

def label_total(total:int)->str:
  for lo,hi,label in THRESHOLDS:
    if lo<=total<=hi: return label
  return "不明"
