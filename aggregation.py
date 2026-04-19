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
"""

import re
from typing import Optional


# ------------------------------------------------------------------ #
#  レーダー8軸のマッピング定義
# ------------------------------------------------------------------ #
#
#  【戦略C:2層構造】
#    UIレーダー(8軸) ←→ 内部分析カテゴリ(rules.py + v4.8)
#
#  「勤務地・募集人数」「求人票サイン(求人票デザイン)」「企業HPサイン(企業HPデザイン)」は
#  レーダー表示上は「仕事内容・スキル」「社風・文化」「企業安定性」等に統合されるが、
#  内部カテゴリ別スコア(画面下部のバー表示)では個別に表示可能。
#
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

    Args:
        cat_scores: 内部カテゴリ別スコア。例:
            {"給与・待遇": 3, "勤務時間・休日": 2, "社風・福利厚生": 1, ...}

    Returns:
        dict: 8軸それぞれのスコア(0-5)。未測定軸は0として返す。
        例:
            {
                "salary_compensation": 3.0,
                "working_hours": 2.0,
                "job_content_skills": 1.5,
                ...
            }
    """
    radar = {}

    for axis_key, mapping in RADAR_AXIS_MAPPING.items():
        score = 0.0
        for cat, weight in mapping["weight"].items():
            score += cat_scores.get(cat, 0) * weight

        # 0-5の範囲に丸める
        radar[axis_key] = round(min(MAX_AXIS_SCORE, max(0, score)), 1)

    return radar


def get_radar_display_names() -> dict:
    """
    レーダー8軸の表示名マップを返す(フロントエンド用)。

    Returns:
        dict: { "salary_compensation": "給与・報酬", ... }
    """
    return {
        key: mapping["display_name"]
        for key, mapping in RADAR_AXIS_MAPPING.items()
    }


# ------------------------------------------------------------------ #
#  2. 赤ポリゴン × 緑ポリゴン の差分判定
# ------------------------------------------------------------------ #
#
#  「あなたの耐性」ラベル:
#    user_tolerance の score が高い = その軸のズレを吸収できる
#    user_tolerance の score が低い = その軸のズレに弱い
#
#  判定ロジック:
#    gap = company_risk - user_tolerance
#    gap が正 = リスクが耐性を上回る(要注意領域)
#    gap が負 = 耐性がリスクを吸収できる(安全領域)
#
# ------------------------------------------------------------------ #

VERDICT_THRESHOLDS = [
    # (下限, 上限, verdict, message)
    (-999, -1.0,  "safe",     "この軸はリスクがあっても吸収できる領域です"),
    (-1.0,  0.5,  "watch",    "ズレは小さく、許容範囲内の可能性"),
    ( 0.5,  2.0,  "warning",  "リスクが耐性を上回っています。確認を推奨"),
    ( 2.0,  999,  "critical", "リスクが耐性を大きく超えています。要注意"),
]


def compute_axis_matches(radar_scores: dict, user_tolerance: dict) -> dict:
    """
    赤ポリゴン(企業リスク) × 緑ポリゴン(ユーザー耐性) の軸ごとのマッチ判定。

    Args:
        radar_scores: aggregate_to_radar_axes() の戻り値(8軸スコア)
        user_tolerance: ILORA側から渡される 8軸の ToleranceScore。
            形式:
            {
                "salary_compensation": {"score": 2.0, "confidence": "high", ...},
                "working_hours": {"score": 4.0, ...},
                ...
            }

    Returns:
        dict: 軸ごとの AxisMatchResult。
            形式:
            {
                "salary_compensation": {
                    "company_risk": 3.5,
                    "user_tolerance": 2.0,
                    "gap": 1.5,
                    "verdict": "warning",
                    "message": "リスクが耐性を上回っています...",
                    "confidence": "high"
                },
                ...
            }
    """
    matches = {}

    for axis_key, company_risk in radar_scores.items():
        # ユーザー耐性データを取得(なければデフォルト3.0=中立)
        tolerance_data = user_tolerance.get(axis_key) or {}

        # dictでもobjectでも受け取れるようにする
        if isinstance(tolerance_data, dict):
            user_score = float(tolerance_data.get("score", 3.0))
            confidence = tolerance_data.get("confidence", "medium")
        else:
            user_score = float(getattr(tolerance_data, "score", 3.0))
            confidence = getattr(tolerance_data, "confidence", "medium")

        gap = company_risk - user_score

        # verdictとmessageの判定
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
#  3. hard_limit違反チェック
# ------------------------------------------------------------------ #

def check_hard_limit_violations(
    text: str,
    hard_limits: Optional[dict]
) -> list[dict]:
    """
    求人票テキストが hard_limits(絶対NG条件)に抵触するかチェック。

    Args:
        text: 求人票テキスト(preprocessed)
        hard_limits: ILORA側から渡される hard_limits データ。
            形式:
            {
                "income_floor": 500,  # 万円
                "geography_exclusion": ["大阪", "福岡"],
                "work_style_constraints": ["フルタイムのみの環境"],
                "continuity_patterns": [...],
                "relationship_exclusions": [...]
            }

    Returns:
        list[dict]: 違反項目のリスト。空リストなら違反なし。
            形式:
            [
                {
                    "type": "income_floor",
                    "message": "求人票の最高年収(400万円)が下限(500万円)を下回ります",
                    "severity": "critical"
                },
                ...
            ]
    """
    if not hard_limits:
        return []

    violations = []

    # --- income_floor (R1: 年収下限) ---
    floor = hard_limits.get("income_floor")
    if floor:
        salary_matches = re.findall(
            r"(\d{3,4})\s*万\s*[円]?\s*[-〜~]\s*(\d{3,4})\s*万|"
            r"年収\s*(\d{3,4})\s*万\s*[円]?\s*以上|"
            r"(\d{3,4})\s*万\s*[円]?\s*スタート",
            text
        )
        if salary_matches:
            # 抽出したすべての数値から最大値を取る
            all_values = []
            for match in salary_matches:
                for v in match:
                    if v:
                        all_values.append(int(v))
            if all_values:
                max_salary = max(all_values)
                if max_salary < floor:
                    violations.append({
                        "type": "income_floor",
                        "message": f"求人票の最高年収({max_salary}万円)が下限({floor}万円)を下回ります",
                        "severity": "critical",
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
    # 求人票のテキスト中で、ユーザーが避けたい働き方を示すキーワードが見つかるかチェック
    for constraint in hard_limits.get("work_style_constraints", []) or []:
        if not constraint or not isinstance(constraint, str):
            continue

        # 簡易マッチング:制約文中の重要キーワードを抽出してテキスト検索
        # (v4.8では簡易実装、v5.0でより高度なマッチング)
        keywords = _extract_constraint_keywords(constraint)
        for kw in keywords:
            if kw and kw in text:
                violations.append({
                    "type": "work_style_constraints",
                    "message": f"働き方制約「{constraint}」に関連する記載が見られます:「{kw}」",
                    "severity": "warning",
                })
                break  # 同じ制約で複数ヒットしないよう1件で打ち切り

    # --- relationship_exclusions (R5: 関係性制約) ---
    # 求人票には上司・組織文化の明確な記述が少ないため、
    # v4.8では簡易的に文化キーワードマッチのみ
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

    v4.8では単純なキーワード辞書ベース。v5.0ではセマンティック検索に置き換え予定。
    """
    # 働き方・関係性系の定型キーワード
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
    レーダー8軸に集約されないカテゴリ(例:求人票デザイン、企業HPデザイン)も
    画面下部のバー表示用に保持する。

    Args:
        cat_scores: 内部カテゴリスコア

    Returns:
        list[dict]: 表示順に並んだカテゴリスコアのリスト
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
