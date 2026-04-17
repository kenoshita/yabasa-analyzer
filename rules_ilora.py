"""
rules_ilora.py
yabasa-analyzer の rules.py を ILORA Phase 1.5 向けに拡張したもの。
元の rules.py は変更しない。このファイルで上書き追加する。

変更点:
  1. QUESTION_BANK: カテゴリ別「企業への問い文テンプレ」を追加
  2. RULES_BASE に「ライフステージ適合」カテゴリを追加
  3. SAFE_GUARDS に育休・復職実績系ガードを追加
  4. ilora_concerns() 関数: ILORAのUIが直接使えるJSON構造を返す
"""

from rules import (
    score_text,
    label_total,
    fetch_text_from_url,
    preprocess_text,
    MAX_PER_CATEGORY,
    DISPLAY_NAME_MAP,
    RULES_BASE,
    SAFE_GUARDS,
)
import re

# ------------------------------------------------------------------ #
#  ライフステージ適合カテゴリを追加（元の rules.py を汚さない）
# ------------------------------------------------------------------ #

RULES_LIFECYCLE = {
    "ライフステージ適合": [
        {
            "pattern": r"(育休|産休|育児休業|産前産後)[\s\S]{0,30}(なし|不明|未記載|記載なし)",
            "weight": 3,
            "reason": "育休・産休の記載が見当たらない（法定制度でも明記しない会社は運用意識が低い）"
        },
        {
            "pattern": r"(フルタイム|正社員).{0,20}(のみ|限定|前提)",
            "weight": 2,
            "reason": "フルタイム前提の記載が強い（時短勤務との相性懸念）"
        },
        {
            "pattern": r"(出張|泊まり|深夜|夜間).{0,20}(多い|頻繁|あり)",
            "weight": 2,
            "reason": "出張・深夜業務の記載あり（育児中の制約と衝突する可能性）"
        },
        {
            "pattern": r"体育会系|根性|気合|精神論",
            "weight": 1,
            "reason": "精神論カルチャーの示唆（育児配慮との相性リスク）"
        },
    ]
}

SAFE_GUARDS_LIFECYCLE = {
    "ライフステージ適合": [
        {
            "pattern": r"(育休|産休).{0,30}(取得実績|復職率|100%|推奨|取得率)",
            "negative_weight": 3,
            "note": "育休取得実績・復職率を明記"
        },
        {
            "pattern": r"時短勤務.{0,30}(利用可|対応|あり|実績)",
            "negative_weight": 2,
            "note": "時短勤務の利用実績あり"
        },
        {
            "pattern": r"管理職.{0,30}女性.{0,30}\d+%",
            "negative_weight": 1,
            "note": "管理職女性比率を開示"
        },
        {
            "pattern": r"(子育て|育児).{0,20}(支援|応援|補助|制度)",
            "negative_weight": 1,
            "note": "育児支援制度の明記"
        },
    ]
}

# DISPLAY_NAME_MAP を拡張
DISPLAY_NAME_MAP_EX = {
    **DISPLAY_NAME_MAP,
    "ライフステージ適合": "ライフステージ適合",
}


# ------------------------------------------------------------------ #
#  問い文バンク: カテゴリ別「企業に聞く問い」テンプレ
#  キー = DISPLAY_NAME_MAP のカテゴリ名（日本語）
# ------------------------------------------------------------------ #

QUESTION_BANK = {
    "給与・待遇": [
        {
            "id": "salary_range",
            "trigger_keywords": ["年収幅", "SALARY_RANGE_WIDE", "上限なし", "青天井"],
            "question": "年収レンジが幅広く記載されていますが、入社1年目・3年目の方の平均的な年収水準を参考までに教えていただけますか",
        },
        {
            "id": "fixed_salary",
            "trigger_keywords": ["固定残業", "みなし残業", "固定給未記載", "基本給"],
            "question": "求人票に基本給・固定給の記載がございませんでした。月額固定給の水準と、固定残業代が含まれる場合はその時間数を教えていただけますか",
        },
        {
            "id": "incentive_ratio",
            "trigger_keywords": ["歩合", "インセンティブ", "出来高"],
            "question": "インセンティブが含まれるとのことですが、固定給とインセンティブの比率の目安と、未達時の最低保障があれば教えていただけますか",
        },
    ],
    "勤務時間・休日": [
        {
            "id": "overtime_actual",
            "trigger_keywords": ["みなし残業", "裁量労働", "固定残業", "フレックス"],
            "question": "月平均の残業時間と、繁忙期のピーク時の目安を教えていただけますか。また残業代の支給ルール（全額支給・固定超分のみ等）も確認させてください",
        },
        {
            "id": "holiday_actual",
            "trigger_keywords": ["シフト制", "休日応相談", "週休"],
            "question": "年間休日数と有給取得率の実績を教えていただけますか。また有給を取りやすい雰囲気かどうか率直にお聞かせいただけますか",
        },
    ],
    "仕事内容・募集条件": [
        {
            "id": "scope_clarity",
            "trigger_keywords": ["0→1", "ゼロイチ", "何でもやる", "マルチロール", "第二創業"],
            "question": "入社後最初の6ヶ月で主に担っていただく業務を3つほど具体的に教えていただけますか。また業務範囲の変化スピードの実態も知りたいと思っています",
        },
        {
            "id": "kpi_pressure",
            "trigger_keywords": ["ノルマ", "KPI", "厳しい目標"],
            "question": "数値目標の設定と評価の仕組みについて教えてください。未達の場合のフォロー体制と、目標の決め方（トップダウン/ボトムアップ）も確認させてください",
        },
        {
            "id": "onboarding",
            "trigger_keywords": ["未経験歓迎", "ポテンシャル採用", "人物重視"],
            "question": "入社後の教育・OJT体制について教えてください。一人立ちまでの標準的な期間と、担当者がつくかどうかも確認させてください",
        },
    ],
    "社風・福利厚生": [
        {
            "id": "culture_actual",
            "trigger_keywords": ["アットホーム", "体育会系", "社員は家族", "飲み会"],
            "question": "業務時間外の社内イベントや懇親会への参加について、実態を率直に教えていただけますか（任意か強制か、頻度、費用負担など）",
        },
        {
            "id": "legal_benefits",
            "trigger_keywords": ["社会保険未記載", "福利厚生"],
            "question": "社会保険（健康保険・厚生年金・雇用保険・労災）の加入状況を確認させてください。また入社時点から適用されますか",
        },
    ],
    "勤務地・募集人数": [
        {
            "id": "transfer_risk",
            "trigger_keywords": ["転勤あり", "全国各地", "配属"],
            "question": "転勤の頻度と、発生する場合の事前通知期間の目安を教えていただけますか。また転勤を断ることは可能ですか",
        },
        {
            "id": "headcount_reason",
            "trigger_keywords": ["大量募集", "50名", "100名"],
            "question": "今回の採用規模の背景を教えていただけますか。事業拡大なのか、欠員補充なのかによって入社後の環境が変わると思いますので確認させてください",
        },
    ],
    "求人票デザイン": [
        {
            "id": "tenure_reality",
            "trigger_keywords": ["若手活躍", "20代中心", "平均年齢20代"],
            "question": "社員の年齢構成と、3年・5年以上在籍されている方の比率を教えていただけますか。長期在籍者のキャリア事例も伺えると参考になります",
        },
    ],
    "企業HPデザイン": [
        {
            "id": "business_track_record",
            "trigger_keywords": ["実績非公開", "事業内容不明"],
            "question": "直近の主要取引先・サービス導入実績を教えていただけますか。守秘義務の範囲で構いません。事業の安定性を確認したいと思っています",
        },
    ],
    "ライフステージ適合": [
        {
            "id": "parental_leave",
            "trigger_keywords": ["育休", "産休", "ライフステージ"],
            "question": "育休・産休の取得実績（取得率・復職率）を教えていただけますか。また育児中の社員が現在どのくらい在籍されているか参考までに伺えますか",
        },
        {
            "id": "short_time_work",
            "trigger_keywords": ["時短", "育児", "フルタイム限定"],
            "question": "時短勤務制度の利用実績と、時短社員の評価における扱いについて教えていただけますか。通常勤務者と評価軸に違いはありますか",
        },
        {
            "id": "sick_child",
            "trigger_keywords": ["子供", "急病", "育児"],
            "question": "お子さんの急な体調不良時など、突発的な対応が必要な場面での社内の雰囲気について率直に教えていただけますか",
        },
        {
            "id": "women_in_management",
            "trigger_keywords": ["管理職", "女性", "キャリア"],
            "question": "管理職に占める女性の比率と、育児経験のある社員が管理職として活躍されているケースがあれば教えていただけますか",
        },
    ],
}


# ------------------------------------------------------------------ #
#  拡張スコアリング関数（ライフステージ込み）
# ------------------------------------------------------------------ #

def score_text_ilora(text: str, persona: str = "standard"):
    """
    persona: "standard" | "lifecycle"
      lifecycle = 35歳以上・子持ち女性向けに ライフステージ適合 カテゴリも評価
    """
    from rules import (
        preprocess_text, _collect_evidence, _katakana_density, _wide_salary_range
    )
    import re

    text = preprocess_text(text or "")

    # --- 元の rules.py の RULES_BASE + 拡張カテゴリ ---
    rules_all = dict(RULES_BASE)
    safe_all = dict(SAFE_GUARDS)

    if persona == "lifecycle":
        rules_all.update(RULES_LIFECYCLE)
        safe_all.update(SAFE_GUARDS_LIFECYCLE)

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

    # カタカナ密度
    dens = _katakana_density(text)
    if dens >= 0.18:
        cat = "求人票サイン"
        cat_scores[cat] = min(MAX_PER_CATEGORY, cat_scores.get(cat, 0) + 1)
        cat_hits.setdefault(cat, []).append({
            "pattern": "KATAKANA_DENSITY>=0.18", "weight": 1,
            "reason": "見慣れない横文字の職種が多い可能性"
        })
        measured_flags[cat] = True

    # 年収幅
    ranges = _wide_salary_range(text)
    if ranges:
        cat = "給与・待遇"
        add = 2 if any(hi - lo >= 500 for lo, hi, _, _ in ranges) else 1
        cat_scores[cat] = min(MAX_PER_CATEGORY, cat_scores.get(cat, 0) + add)
        cat_hits.setdefault(cat, []).append({
            "pattern": "SALARY_RANGE_WIDE", "weight": add,
            "reason": "年収幅が広すぎる（例：300万〜1000万）"
        })
        measured_flags[cat] = True

    total = sum(cat_scores.values())
    return cat_scores, cat_hits, cat_safe_hits, cat_evidence, total, measured_flags


# ------------------------------------------------------------------ #
#  問い文選択ロジック
# ------------------------------------------------------------------ #

def pick_questions(cat_hits: dict, cat_scores: dict, max_questions: int = 5) -> list[dict]:
    """
    スコアが高いカテゴリから順に、該当する問い文テンプレを選択して返す。
    戻り値: [{ id, category, question, score, reason }, ...]
    """
    # (score, cat) 降順ソート
    sorted_cats = sorted(
        [(score, cat) for cat, score in cat_scores.items() if score > 0],
        key=lambda x: -x[0]
    )

    selected = []
    seen_ids = set()

    for score, cat in sorted_cats:
        if len(selected) >= max_questions:
            break

        disp = DISPLAY_NAME_MAP_EX.get(cat, cat)
        bank = QUESTION_BANK.get(disp, [])
        hits = cat_hits.get(cat, [])

        # ヒットしたパターンのキーワードと問い文を照合
        matched_q = None
        hit_reason = ""

        for hit in hits:
            hit_reason = hit.get("reason", "")
            hit_pattern = hit.get("pattern", "")

            for q in bank:
                if q["id"] in seen_ids:
                    continue
                # trigger_keywordsのどれかがhit内容に含まれるか
                if any(kw.lower() in (hit_reason + hit_pattern).lower() for kw in q["trigger_keywords"]):
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


# ------------------------------------------------------------------ #
#  ILORA メイン出力関数
# ------------------------------------------------------------------ #

def ilora_concerns(
    text: str,
    persona: str = "standard",
    max_questions: int = 5,
) -> dict:
    """
    ILORAのUIが直接consumeできる構造を返す。

    Returns:
    {
      "risk_level": "低|中|高",
      "total_score": int,
      "concerns": [           ← ユーザーに見せる懸念一覧
        {
          "category": str,
          "score": int,       ← 0-5
          "summary": str,     ← 懸念の要旨（1行）
          "evidence": [str],  ← 求人票から抜粋
        }
      ],
      "questions": [          ← 企業に送る問い文の候補（最大5件）
        {
          "id": str,
          "category": str,
          "question": str,
          "score": int,
          "selected": bool,   ← UIでデフォルト選択するか（score>=3）
        }
      ],
      "positive_signals": [str],   ← SafeGuard発動したポジティブ情報
    }
    """
    cat_scores, cat_hits, cat_safe_hits, cat_evidence, total, measured_flags = \
        score_text_ilora(text, persona=persona)

    risk_level = label_total(total)

    # 懸念リスト（スコア>0のカテゴリ）
    concerns = []
    for cat, score in sorted(cat_scores.items(), key=lambda x: -x[1]):
        if score == 0:
            continue
        disp = DISPLAY_NAME_MAP_EX.get(cat, cat)
        hits = cat_hits.get(cat, [])
        summary = hits[0]["reason"] if hits else f"{disp}に懸念が検出されました"
        ev = [e for e in cat_evidence.get(cat, []) if e]
        concerns.append({
            "category": disp,
            "score": score,
            "summary": summary,
            "evidence": ev[:2],
        })

    # 問い文候補
    raw_questions = pick_questions(cat_hits, cat_scores, max_questions=max_questions)
    questions = [
        {
            **q,
            "selected": q["score"] >= 3,   # score3以上はデフォルト選択
        }
        for q in raw_questions
    ]

    # ポジティブシグナル
    positive = []
    for cat, guards in cat_safe_hits.items():
        for g in guards:
            positive.append(g.get("note", ""))
    positive = list(set(p for p in positive if p))

    return {
        "risk_level": risk_level,
        "total_score": total,
        "concerns": concerns,
        "questions": questions,
        "positive_signals": positive,
    }
