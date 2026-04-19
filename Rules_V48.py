"""
rules_v48.py
ILORA v4.8 で追加するカテゴリのルール定義。

変更点:
  - RULES_V48: 「組織フェーズ」「評価・成長」カテゴリを追加
  - SAFE_GUARDS_V48: 上記2カテゴリのセーフガード
  - QUESTION_BANK_V48: 上記2カテゴリの企業への問い文テンプレ
  - score_text_v48(): rules_ilora.py の score_text_ilora を拡張

設計方針:
  - rules.py, rules_ilora.py は一切変更しない
  - persona に関係なく常に評価される(case C採用)
  - 既存の rules_ilora.py の関数パターンを踏襲
"""

import re
from rules import MAX_PER_CATEGORY, DISPLAY_NAME_MAP, preprocess_text
from rules_ilora import (
    RULES_LIFECYCLE,
    SAFE_GUARDS_LIFECYCLE,
    DISPLAY_NAME_MAP_EX,
    QUESTION_BANK,
)


# ------------------------------------------------------------------ #
#  v4.8 追加カテゴリ:組織フェーズ
# ------------------------------------------------------------------ #

RULES_ORG_PHASE = {
    "組織フェーズ": [
        {
            "pattern": r"(第二創業|急成長|急拡大|スケール).{0,20}(フェーズ|期|中)",
            "weight": 1,
            "reason": "急成長フェーズ(業務負荷急変の可能性)"
        },
        {
            "pattern": r"シリーズ[A-D]|プレ?シード|資金調達.{0,20}(完了|実施)",
            "weight": 1,
            "reason": "スタートアップ特有の不確実性"
        },
        {
            "pattern": r"IPO.{0,20}(目指|準備|予定)",
            "weight": 2,
            "reason": "IPO準備期は業務負荷が急増しやすい"
        },
        {
            "pattern": r"(0→1|ゼロイチ).{0,20}(立ち上げ|フェーズ|開発)",
            "weight": 2,
            "reason": "ゼロイチフェーズは役割不明確になりがち"
        },
        {
            "pattern": r"組織.{0,10}(拡大中|変革期|再編|過渡期)",
            "weight": 1,
            "reason": "組織再編期は評価制度が未確立の可能性"
        },
        {
            "pattern": r"(ピボット|方向転換|事業転換).{0,20}(中|直後)",
            "weight": 2,
            "reason": "事業転換直後は役割・方針が流動的"
        },
    ]
}

SAFE_GUARDS_ORG_PHASE = {
    "組織フェーズ": [
        {
            "pattern": r"創業.{0,10}\d{2,3}\s*年",
            "negative_weight": 1,
            "note": "創業からの年数を明記(安定フェーズの示唆)"
        },
        {
            "pattern": r"従業員\s*\d{3,}\s*名",
            "negative_weight": 1,
            "note": "従業員数を明記"
        },
        {
            "pattern": r"(東証|プライム|スタンダード|グロース).{0,10}上場",
            "negative_weight": 2,
            "note": "上場企業(情報開示・ガバナンスの担保)"
        },
        {
            "pattern": r"(黒字|営業利益|経常利益).{0,20}(達成|確保|継続)",
            "negative_weight": 1,
            "note": "黒字・利益確保の明記"
        },
    ]
}


# ------------------------------------------------------------------ #
#  v4.8 追加カテゴリ:評価・成長
# ------------------------------------------------------------------ #

RULES_EVAL_GROWTH = {
    "評価・成長": [
        {
            "pattern": r"評価制度.{0,10}(未記載|不明|なし|記載なし)",
            "weight": 3,
            "reason": "評価制度が不透明(重大リスク)"
        },
        {
            "pattern": r"昇給.{0,10}(応相談|年1回のみ|実績による|ケースバイケース)",
            "weight": 1,
            "reason": "昇給条件が曖昧"
        },
        {
            "pattern": r"(幹部|管理職).{0,10}(候補|即|すぐ|早期)",
            "weight": 2,
            "reason": "急速な昇進前提(実体不透明の可能性)"
        },
        {
            "pattern": r"研修制度.{0,10}(未記載|なし|特になし)",
            "weight": 1,
            "reason": "教育体制が不明確"
        },
        {
            "pattern": r"(評価|査定).{0,10}(上司次第|属人|主観)",
            "weight": 2,
            "reason": "評価が属人的・主観的"
        },
        {
            "pattern": r"(成果|実力).{0,5}(主義|重視).{0,30}(若手|年齢).{0,10}関係",
            "weight": 1,
            "reason": "成果主義の強調(評価基準が不透明な可能性)"
        },
    ]
}

SAFE_GUARDS_EVAL_GROWTH = {
    "評価・成長": [
        {
            "pattern": r"評価制度.{0,30}(360|MBO|OKR|コンピテンシー|目標管理)",
            "negative_weight": 2,
            "note": "明示的な評価手法を採用"
        },
        {
            "pattern": r"(1on1|ワンオンワン|1 on 1).{0,20}(実施|定期|毎週|毎月)",
            "negative_weight": 1,
            "note": "1on1制度あり"
        },
        {
            "pattern": r"(研修|OJT|メンター).{0,20}(制度|あり|実施|充実)",
            "negative_weight": 1,
            "note": "育成制度の明記"
        },
        {
            "pattern": r"(評価|昇給).{0,10}(半期|四半期|年2回)",
            "negative_weight": 1,
            "note": "評価サイクルが明確"
        },
        {
            "pattern": r"資格取得.{0,20}(支援|補助|手当)",
            "negative_weight": 1,
            "note": "資格取得支援あり"
        },
    ]
}


# ------------------------------------------------------------------ #
#  DISPLAY_NAME_MAP を v4.8 用に拡張
# ------------------------------------------------------------------ #

DISPLAY_NAME_MAP_V48 = {
    **DISPLAY_NAME_MAP_EX,
    "組織フェーズ": "組織フェーズ",
    "評価・成長": "評価・成長",
}


# ------------------------------------------------------------------ #
#  v4.8 追加カテゴリの問い文テンプレ
# ------------------------------------------------------------------ #

QUESTION_BANK_V48 = {
    "組織フェーズ": [
        {
            "id": "phase_clarity",
            "trigger_keywords": ["急成長", "第二創業", "ゼロイチ", "0→1", "拡大中"],
            "question": "現在の組織フェーズと直近1-2年の組織変化の予定について教えていただけますか。また役割が固まるまでの期間の目安もお聞かせください",
        },
        {
            "id": "funding_runway",
            "trigger_keywords": ["シリーズ", "資金調達", "シード"],
            "question": "直近の資金調達状況と、次の調達までの見通しを差し支えない範囲で教えていただけますか",
        },
        {
            "id": "ipo_pressure",
            "trigger_keywords": ["IPO"],
            "question": "IPO準備に伴う業務負荷の増加について、現場レベルでどのような影響があるか具体的に教えていただけますか",
        },
        {
            "id": "pivot_stability",
            "trigger_keywords": ["ピボット", "方向転換", "事業転換"],
            "question": "直近の事業方針の変更について、背景と今後の安定性の見通しを教えていただけますか。現在の方針がどの程度定まっているかも確認させてください",
        },
    ],
    "評価・成長": [
        {
            "id": "eval_process",
            "trigger_keywords": ["評価制度", "MBO", "OKR", "360", "目標管理"],
            "question": "評価サイクル(半期/四半期等)と、評価者・評価基準の開示度合いについて教えていただけますか",
        },
        {
            "id": "promotion_path",
            "trigger_keywords": ["幹部候補", "管理職", "昇進"],
            "question": "入社後のキャリアパスと、昇進の実績(直近1-2年で昇進された方の前職経歴や在籍年数)を教えていただけますか",
        },
        {
            "id": "growth_support",
            "trigger_keywords": ["1on1", "研修", "OJT", "メンター"],
            "question": "入社後のオンボーディングと、継続的な学習支援(書籍購入・勉強会・外部研修費補助など)について教えていただけますか",
        },
        {
            "id": "eval_transparency",
            "trigger_keywords": ["評価", "査定", "上司次第", "属人"],
            "question": "評価基準の透明性について教えてください。評価者間での基準合わせや、評価のフィードバック方法についても確認させてください",
        },
    ],
}


# ------------------------------------------------------------------ #
#  統合スコアリング関数(v4.8)
# ------------------------------------------------------------------ #

def score_text_v48(text: str, persona: str = "standard"):
    """
    v4.8: rules.py + rules_ilora.py(ライフステージ) + rules_v48.py の統合スコアリング。

    persona:
        "standard"  = 基本カテゴリ + 組織フェーズ + 評価・成長
        "lifecycle" = 基本カテゴリ + ライフステージ + 組織フェーズ + 評価・成長

    戻り値: (cat_scores, cat_hits, cat_safe_hits, cat_evidence, total, measured_flags)
    """
    from rules import (
        RULES_BASE, SAFE_GUARDS,
        _collect_evidence, _katakana_density, _wide_salary_range,
    )

    text = preprocess_text(text or "")

    # --- ルールセットの統合 ---
    rules_all = dict(RULES_BASE)
    safe_all = dict(SAFE_GUARDS)

    # lifecycle persona時はライフステージ適合を追加
    if persona == "lifecycle":
        rules_all.update(RULES_LIFECYCLE)
        safe_all.update(SAFE_GUARDS_LIFECYCLE)

    # v4.8: 組織フェーズ・評価・成長は常に追加(persona非依存)
    rules_all.update(RULES_ORG_PHASE)
    rules_all.update(RULES_EVAL_GROWTH)
    safe_all.update(SAFE_GUARDS_ORG_PHASE)
    safe_all.update(SAFE_GUARDS_EVAL_GROWTH)

    cat_scores = {}
    cat_hits = {}
    cat_safe_hits = {}
    cat_evidence = {}
    measured_flags = {}

    for cat, rs in rules_all.items():
        score = 0
        hits = []
        evidence = []
        measured = False

        for rule in rs:
            if re.search(rule["pattern"], text, flags=re.IGNORECASE | re.DOTALL):
                score += rule["weight"]
                hits.append(rule)
                evidence.extend(_collect_evidence(text, rule["pattern"]))
                measured = True

        safe_hits = []
        for guard in safe_all.get(cat, []):
            if re.search(guard["pattern"], text, flags=re.IGNORECASE | re.DOTALL):
                score -= guard["negative_weight"]
                safe_hits.append(guard)
                measured = True

        score = max(0, min(score, MAX_PER_CATEGORY))
        cat_scores[cat] = score
        cat_hits[cat] = hits
        cat_safe_hits[cat] = safe_hits
        cat_evidence[cat] = evidence[:3]
        measured_flags[cat] = measured

    # --- カタカナ密度(既存ロジック) ---
    dens = _katakana_density(text)
    if dens >= 0.18:
        cat = "求人票サイン"
        cat_scores[cat] = min(MAX_PER_CATEGORY, cat_scores.get(cat, 0) + 1)
        cat_hits.setdefault(cat, []).append({
            "pattern": "KATAKANA_DENSITY>=0.18",
            "weight": 1,
            "reason": "見慣れない横文字の職種が多い可能性"
        })
        cat_evidence.setdefault(cat, []).append(
            "… カタカナ語が多い(比率{:.0%}) …".format(dens)
        )
        measured_flags[cat] = True

    # --- 年収幅(既存ロジック) ---
    ranges = _wide_salary_range(text)
    if ranges:
        cat = "給与・待遇"
        add = 2 if any(hi - lo >= 500 for lo, hi, _, _ in ranges) else 1
        cat_scores[cat] = min(MAX_PER_CATEGORY, cat_scores.get(cat, 0) + add)
        cat_hits.setdefault(cat, []).append({
            "pattern": "SALARY_RANGE_WIDE",
            "weight": add,
            "reason": "年収幅が広すぎる(例:300万〜1000万)"
        })
        for _, _, s, e in ranges[:2]:
            snippet = text[max(0, s-40):min(len(text), e+40)].replace("\n", " ")
            cat_evidence.setdefault(cat, []).append("… " + snippet + " …")
        measured_flags[cat] = True

    total = sum(cat_scores.values())
    return cat_scores, cat_hits, cat_safe_hits, cat_evidence, total, measured_flags


# ------------------------------------------------------------------ #
#  問い文選択ロジック(v4.8用、QUESTION_BANK_V48統合版)
# ------------------------------------------------------------------ #

def pick_questions_v48(cat_hits: dict, cat_scores: dict, max_questions: int = 5) -> list[dict]:
    """
    スコアが高いカテゴリから順に、該当する問い文テンプレを選択して返す。
    QUESTION_BANK(rules_ilora.py) + QUESTION_BANK_V48(rules_v48.py)を統合。
    """
    # 既存のQUESTION_BANKとv4.8追加分をマージ
    question_bank_all = {**QUESTION_BANK, **QUESTION_BANK_V48}

    sorted_cats = sorted(
        [(score, cat) for cat, score in cat_scores.items() if score > 0],
        key=lambda x: -x[0]
    )

    selected = []
    seen_ids = set()

    for score, cat in sorted_cats:
        if len(selected) >= max_questions:
            break

        disp = DISPLAY_NAME_MAP_V48.get(cat, cat)
        bank = question_bank_all.get(disp, [])
        hits = cat_hits.get(cat, [])

        matched_q = None
        hit_reason = ""

        for hit in hits:
            hit_reason = hit.get("reason", "")
            hit_pattern = hit.get("pattern", "")

            for q in bank:
                if q["id"] in seen_ids:
                    continue
                if any(kw.lower() in (hit_reason + hit_pattern).lower()
                       for kw in q["trigger_keywords"]):
                    matched_q = q
                    break

            if matched_q:
                break

        # マッチしなければカテゴリ先頭の問いを使う
        if not matched_q and bank:
            for q in bank:
                if q["id"] not in seen_ids:
                    matched_q = q
                    break

        if matched_q:
            seen_ids.add(matched_q["id"])
            selected.append({
                "id": matched_q["id"],
                "category": disp,
                "question": matched_q["question"],
                "score": score,
                "trigger_reason": hit_reason,
            })

    return selected
