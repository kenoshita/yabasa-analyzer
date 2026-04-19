"""
aggregation.py
ILORA v4.8 で追加する集約ロジック。

機能:
  1. 内部カテゴリスコア(rules.py + rules_ilora.py + rules_v48.py)
     → レーダー8軸スコアへの集約
  2. 赤ポリゴン(企業リスク) × 緑ポリゴン(ユーザー耐性)の差分判定
  3. hard_limit違反チェック

設計方針:
  - 既存の rules.py, rules_ilora.py, rules_v48.py は変更しない
  - ILORA側との8軸レーダー表示(戦略C:2層構造)に対応
  - 「あなたの優先度」→「あなたの耐性」のラベル変更に追随

変更履歴:
  v4.8.0 (initial): 基本実装
  v4.8.1: hard_limit_violations の年収検出ロジック強化
          - 月給/月額/基本給からの年収換算(×12)に対応
          - 時給からの年収換算(×2080)に対応
          - 2桁年収表記にも対応
          - 年収情報未記載時の警告も追加
"""

import re
from typing import Optional


# ------------------------------------------------------------------ #
#  レーダー8軸のマッピング定義
# ------------------------------------------------------------------ #

RADAR_AXIS_MAPPING = {
    "salary_compensation": {
        "display_name": "給与・報酬",
        "weight": {
            "給与・待遇": 1.0,
        },
    },
    "working_hours": {
        "display_name": "労働時間",
        "weight": {
            "勤務時間・休日": 1.0,
        },
    },
    "job_content_skills": {
        "display_name": "仕事内容・スキル",
        "weight": {
            "仕事内容・募集条件": 0.7,
            "勤務地・募集人数": 0.3,
        },
    },
    "culture": {
        "display_name": "社風・文化",
        "weight": {
            "社風・福利厚生": 0.6,
            "求人票サイン": 0.4,
        },
    },
    "organization_phase": {
        "display_name": "組織フェーズ",
        "weight": {
            "組織フェーズ": 1.0,
        },
    },
    "evaluation_growth": {
        "display_name": "評価・成長",
        "weight": {
            "評価・成長": 1.0,
        },
    },
    "company_stability": {
        "display_name": "企業安定性",
        "weight": {
            "企業HPサイン": 1.0,
        },
    },
    "life_stage": {
        "display_name": "ライフステージ",
        "weight": {
            "ライフステージ適合": 1.0,
        },
    },
}

MAX_AXIS_SCORE = 5


# ------------------------------------------------------------------ #
#  1. 内部カテゴリスコア → レーダー8軸スコア
# ------------------------------------------------------------------ #

def aggregate_to_radar_axes(cat_scores: dict) -> dict:
    """
    内部カテゴリスコア(10カテゴリ)を レーダー8軸スコアに集約する。
    """
    radar = {}

    for axis_key, mapping in RADAR_AXIS_MAPPING.items():
        score = 0.0
        for cat, weight in mapping["weight"].items():
            score += cat_scores.get(cat, 0) * weight

        radar[axis_key] = round(min(MAX_AXIS_SCORE, max(0, score)), 1)

    return radar


def get_radar_display_names() -> dict:
    """レーダー8軸の表示名マップを返す(フロントエンド用)。"""
    return {
        key: mapping["display_name"]
        for key, mapping in RADAR_AXIS_MAPPING.items()
    }


# ------------------------------------------------------------------ #
#  2. 赤ポリゴン × 緑ポリゴン の差分判定
# ------------------------------------------------------------------ #

VERDICT_THRESHOLDS = [
    (-999, -1.0,  "safe",     "この軸はリスクがあっても吸収できる領域です"),
    (-1.0,  0.5,  "watch",    "ズレは小さく、許容範囲内の可能性"),
    ( 0.5,  2.0,  "warning",  "リスクが耐性を上回っています。確認を推奨"),
    ( 2.0,  999,  "critical", "リスクが耐性を大きく超えています。要注意"),
]


def compute_axis_matches(radar_scores: dict, user_tolerance: dict) -> dict:
    """
    赤ポリゴン(企業リスク) × 緑ポリゴン(ユーザー耐性) の軸ごとのマッチ判定。
    """
    matches = {}

    for axis_key, company_risk in radar_scores.items():
        tolerance_data = user_tolerance.get(axis_key) or {}

        if isinstance(tolerance_data, dict):
            user_score = float(tolerance_data.get("score", 3.0))
            confidence = tolerance_data.get("confidence", "medium")
        else:
            user_score = float(getattr(tolerance_data, "score", 3.0))
            confidence = getattr(tolerance_data, "confidence", "medium")

        gap = company_risk - user_score

        verdict = "watch"
        message = "判定不可"
        for lower, upper, v, m in VERDICT_THRESHOLDS:
            if lower <= gap < upper:
                verdict = v
                message = m
                break

        matches[axis_key] = {
            "company_risk": round(company_risk, 1),
            "user_tolerance": round(user_score, 1),
            "gap": round(gap, 1),
            "verdict": verdict,
            "message": message,
            "confidence": confidence,
        }

    return matches


# ------------------------------------------------------------------ #
#  3. hard_limit違反チェック (v4.8.1で年収検出を強化)
# ------------------------------------------------------------------ #

def _estimate_annual_salaries(text: str) -> list[dict]:
    """
    求人票テキストから想定される年収候補を抽出して、年収換算で返す。

    年収表記/月給表記/基本給表記/時給表記のすべてに対応。

    Returns:
        list[dict]: [{"annual": 240, "source": "月給20万→年収換算", "raw": "月給20万円"}, ...]
    """
    candidates = []

    # --- 1. 年収表記(直接) ---
    # 例: 「年収500万円」「年収500万〜800万」
    for m in re.finditer(
        r"年収\s*(\d{2,4})\s*万",
        text
    ):
        val = int(m.group(1))
        candidates.append({
            "annual": val,
            "source": "年収直接表記",
            "raw": m.group(0),
        })

    # --- 2. 年収レンジ表記 ---
    # 例: 「500万〜800万円」「300万円-1000万円」
    for m in re.finditer(
        r"(\d{3,4})\s*万\s*円?\s*[-〜~ー]\s*(\d{3,4})\s*万",
        text
    ):
        lo = int(m.group(1))
        hi = int(m.group(2))
        candidates.append({
            "annual": hi,
            "source": "年収レンジ上限",
            "raw": m.group(0),
        })
        candidates.append({
            "annual": lo,
            "source": "年収レンジ下限",
            "raw": m.group(0),
        })

    # --- 3. 月給/月額/基本給表記 → 年収換算(×12) ---
    # 例: 「月給20万円」「月額25万」「基本給18万円」
    monthly_pattern = re.compile(
        r"(月\s*給|月\s*額|基本\s*給|月\s*収)\s*[:：]?\s*(\d{1,3})\s*万",
        re.IGNORECASE
    )
    for m in monthly_pattern.finditer(text):
        monthly_man = int(m.group(2))
        annual = monthly_man * 12
        candidates.append({
            "annual": annual,
            "source": f"{m.group(1)}{monthly_man}万→年収換算(×12)",
            "raw": m.group(0),
        })

    # --- 4. 月給「○○円」表記(万円表記なし) ---
    # 例: 「月給200,000円」「基本給180,000円」
    for m in re.finditer(
        r"(月\s*給|月\s*額|基本\s*給|月\s*収)\s*[:：]?\s*([\d,]{6,9})\s*円",
        text
    ):
        try:
            monthly_yen = int(m.group(2).replace(",", ""))
            annual_man = (monthly_yen * 12) // 10000
            if annual_man >= 100:
                candidates.append({
                    "annual": annual_man,
                    "source": f"{m.group(1)}{monthly_yen:,}円→年収換算",
                    "raw": m.group(0),
                })
        except ValueError:
            pass

    # --- 5. 時給表記 → 年収換算(×2080:週40h × 52週) ---
    # 例: 「時給1500円」「時給1,200円〜」
    for m in re.finditer(
        r"時\s*給\s*[:：]?\s*([\d,]{3,5})\s*円",
        text
    ):
        try:
            hourly = int(m.group(1).replace(",", ""))
            annual_yen = hourly * 2080
            annual_man = annual_yen // 10000
            if annual_man >= 100:
                candidates.append({
                    "annual": annual_man,
                    "source": f"時給{hourly:,}円→年収換算(×2080h)",
                    "raw": m.group(0),
                })
        except ValueError:
            pass

    return candidates


def check_hard_limit_violations(
    text: str,
    hard_limits: Optional[dict]
) -> list[dict]:
    """
    求人票テキストが hard_limits(絶対NG条件)に抵触するかチェック。

    v4.8.1: 月給・基本給・時給表記からの年収換算に対応。
    """
    if not hard_limits:
        return []

    violations = []

    # --- income_floor (R1: 年収下限) ---
    floor = hard_limits.get("income_floor")
    if floor:
        salary_candidates = _estimate_annual_salaries(text)
        if salary_candidates:
            # 最も高い候補を採用(企業側の上限値で評価)
            best = max(salary_candidates, key=lambda x: x["annual"])
            max_annual = best["annual"]

            if max_annual < floor:
                violations.append({
                    "type": "income_floor",
                    "message": f"求人票の最高想定年収({max_annual}万円)が下限({floor}万円)を下回ります。根拠:{best['source']}",
                    "severity": "critical",
                    "detected_annual": max_annual,
                    "required_floor": floor,
                    "estimation_source": best["source"],
                })
        else:
            # 年収情報そのものが見つからない場合
            violations.append({
                "type": "income_floor_unconfirmed",
                "message": f"求人票に年収・月給などの給与情報が見つかりません。下限({floor}万円)を満たすか確認が必要です",
                "severity": "warning",
                "required_floor": floor,
            })

    # --- geography_exclusion (R2: 地理制約) ---
    for geo in hard_limits.get("geography_exclusion", []) or []:
        if geo and isinstance(geo, str) and geo.strip() and geo in text:
            violations.append({
                "type": "geography_exclusion",
                "message": f"除外地域「{geo}」が求人票に含まれます",
                "severity": "critical",
            })

    # --- work_style_constraints (R3: 働き方制約) ---
    for constraint in hard_limits.get("work_style_constraints", []) or []:
        if not constraint or not isinstance(constraint, str):
            continue

        keywords = _extract_constraint_keywords(constraint)
        for kw in keywords:
            if kw and kw in text:
                violations.append({
                    "type": "work_style_constraints",
                    "message": f"働き方制約「{constraint}」に関連する記載が見られます:「{kw}」",
                    "severity": "warning",
                })
                break

    # --- relationship_exclusions (R5: 関係性制約) ---
    for exclusion in hard_limits.get("relationship_exclusions", []) or []:
        if not exclusion or not isinstance(exclusion, str):
            continue

        keywords = _extract_constraint_keywords(exclusion)
        for kw in keywords:
            if kw and kw in text:
                violations.append({
                    "type": "relationship_exclusions",
                    "message": f"関係性制約「{exclusion}」に関連する記載:「{kw}」",
                    "severity": "warning",
                })
                break

    return violations


def _extract_constraint_keywords(constraint: str) -> list[str]:
    """
    制約文から重要キーワードを抽出する簡易ヘルパー。
    """
    keyword_patterns = [
        # 働き方
        "フルタイム", "残業", "休日出勤", "夜勤", "転勤", "出張",
        "リモート", "在宅", "フレックス", "時短",
        # 関係性・文化
        "体育会系", "飲み会", "縦社会", "上下関係", "精神論", "根性",
        "アットホーム", "家族", "ノルマ", "成果主義",
    ]

    found = []
    for kw in keyword_patterns:
        if kw in constraint:
            found.append(kw)

    return found


# ------------------------------------------------------------------ #
#  4. カテゴリ別スコアの display データ生成(UI用)
# ------------------------------------------------------------------ #

def build_category_scores_for_display(cat_scores: dict) -> list[dict]:
    """
    カテゴリ別スコアをUI表示用に整形する。
    """
    from rules_v48 import DISPLAY_NAME_MAP_V48

    result = []
    for cat, score in sorted(cat_scores.items(), key=lambda x: -x[1]):
        if score <= 0:
            continue
        result.append({
            "category_key": cat,
            "display_name": DISPLAY_NAME_MAP_V48.get(cat, cat),
            "score": score,
            "max_score": MAX_AXIS_SCORE,
        })
    return result
