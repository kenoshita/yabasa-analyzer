"""
ilora_endpoint.py (v4.8)
-----------------
ILORA Phase 1.5 / v4.8 向けエンドポイント。

v4.8での変更点:
  - リクエスト: ilora_session_id, user_tolerance, hard_limits を受け取り可能に
  - レスポンス: radar_axes, axis_matches, hard_limit_violations, category_scores を追加
  - inquiry: entry_point, resume_id, ilora_session_id を記録

後方互換性:
  v4.8で追加されたフィールドはすべてOptional。既存の呼び出し(yabasa-analyzer単体利用等)
  は変更不要で動作する。

既存の api_app.py への追加:
    from ilora_endpoint import router as ilora_router
    app.include_router(ilora_router)

必要な環境変数:
    GOOGLE_SERVICE_ACCOUNT_JSON  : サービスアカウントJSONの中身をそのまま文字列で
    ILORA_SHEET_ID               : スプレッドシートのID

必要なパッケージ:
    pip install gspread google-auth
"""

import os
import json
import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from rules import label_total
from rules_ilora import fetch_text_from_url
from rules_v48 import score_text_v48, pick_questions_v48, DISPLAY_NAME_MAP_V48
from aggregation import (
    aggregate_to_radar_axes,
    compute_axis_matches,
    check_hard_limit_violations,
    build_category_scores_for_display,
    get_radar_display_names,
)

router = APIRouter(prefix="/ilora", tags=["ilora-phase15"])


# ================================================================== #
#  Google Sheets クライアント(起動時に一度だけ初期化)
# ================================================================== #

_gc = None
_sheet = None


def _get_sheet():
    global _gc, _sheet
    if _sheet is not None:
        return _sheet

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        sheet_id = os.environ.get("ILORA_SHEET_ID", "")

        if not sa_json or not sheet_id:
            return None

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(
            json.loads(sa_json), scopes=scopes
        )
        _gc = gspread.authorize(creds)
        _sheet = _gc.open_by_key(sheet_id).sheet1
        return _sheet

    except Exception as e:
        print(f"[ILORA] Google Sheets 初期化エラー: {e}")
        return None


def _append_inquiry_log(row: dict):
    """スプレッドシートに1行追記。失敗してもエンドポイント自体はエラーにしない。"""
    try:
        sheet = _get_sheet()
        if sheet is None:
            print("[ILORA] スプレッドシート未接続のためログをスキップ")
            return

        existing = sheet.get_all_values()
        if not existing:
            # v4.8: ヘッダー列を拡張
            headers = [
                "受付日時",
                "ユーザー名",
                "連絡先(メール)",
                "企業名",
                "求人URL",
                "懸念点",
                "ステータス",
                "企業問い合わせ日",
                "企業回答日",
                "ユーザーへ返答日",
                "結果",
                "備考",
                # v4.8 追加列
                "ILORAセッションID",
                "流入経路",
                "職務経歴書ID",
                "ペルソナ",
                "hard_limit違反有無",
                "hard_limit違反内容",
            ]
            sheet.append_row(headers)

        now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
        sheet.append_row([
            now.strftime("%Y-%m-%d %H:%M"),
            row.get("user_name", ""),
            row.get("user_email", ""),
            row.get("company_name", ""),
            row.get("job_url", ""),
            row.get("concerns", ""),
            "受付済み",
            "", "", "", "", "",
            # v4.8 追加列
            row.get("ilora_session_id", ""),
            row.get("entry_point", "jobmirror"),
            row.get("resume_id", ""),
            row.get("persona", "standard"),
            "有" if row.get("has_hard_limit_violation") else "無",
            row.get("hard_limit_violation_summary", ""),
        ])
        print(f"[ILORA] スプレッドシートに記録: {row.get('company_name')}")

    except Exception as e:
        print(f"[ILORA] スプレッドシート書き込みエラー: {e}")


# ================================================================== #
#  リクエスト/レスポンスモデル
# ================================================================== #

class ToleranceScore(BaseModel):
    """8軸それぞれのユーザー耐性スコア"""
    score: float = Field(..., ge=0, le=5)
    confidence: str = Field("medium", pattern="^(high|medium|low)$")
    source_fields: list[str] = Field(default_factory=list)
    reasoning: str = ""


class HardLimits(BaseModel):
    """R1-R5由来の絶対NG条件"""
    income_floor: Optional[int] = None
    geography_exclusion: list[str] = Field(default_factory=list)
    work_style_constraints: list[str] = Field(default_factory=list)
    continuity_patterns: list[str] = Field(default_factory=list)
    relationship_exclusions: list[str] = Field(default_factory=list)


class IloraConcernRequest(BaseModel):
    """
    /ilora/concerns エンドポイントのリクエスト。
    v4.8: ilora_session_id, user_tolerance, hard_limits を追加(すべてOptional)。
    """
    # 既存(v4.7互換)
    url: Optional[str] = None
    text: Optional[str] = None
    persona: str = "standard"
    max_questions: int = 5

    # v4.8 追加(Optional)
    ilora_session_id: Optional[str] = None
    user_tolerance: Optional[dict[str, ToleranceScore]] = None
    hard_limits: Optional[HardLimits] = None


class IloraInquiryRequest(BaseModel):
    """
    /ilora/inquiry エンドポイントのリクエスト。
    v4.8: 流入経路・職務経歴書・セッションID情報を追加(すべてOptional)。
    """
    # 既存
    user_name: str = ""
    user_email: str = ""
    company_name: str = ""
    job_url: str = ""
    selected_concerns: list[str] = Field(default_factory=list)

    # v4.8 追加
    ilora_session_id: Optional[str] = None
    entry_point: str = Field(
        "jobmirror",
        pattern="^(jobmirror|resume_completion|home_menu)$"
    )
    resume_id: Optional[str] = None
    persona: str = Field("standard", pattern="^(standard|lifecycle)$")
    hard_limit_violations: list[str] = Field(default_factory=list)


# ================================================================== #
#  メインエンドポイント: /ilora/concerns
# ================================================================== #

@router.post("/concerns")
async def get_concerns(request: Request, inp: IloraConcernRequest):
    """
    求人票テキストorURLを受け取り、懸念点・問い文・レーダー8軸・マッチ判定を返す。
    """
    # --- 入力の取り込み ---
    body = (inp.text or "").strip()
    source = "text"

    if not body and inp.url:
        body = fetch_text_from_url(inp.url)
        source = "url"
        if not body:
            raise HTTPException(
                status_code=400,
                detail="URLの取得に失敗しました。求人票のテキストを直接貼り付けてください。"
            )

    if not body:
        raise HTTPException(
            status_code=400,
            detail="url または text のどちらかを指定してください。"
        )

    if inp.persona not in ("standard", "lifecycle"):
        raise HTTPException(
            status_code=400,
            detail="persona は 'standard' または 'lifecycle' を指定してください。"
        )

    # --- スコアリング ---
    cat_scores, cat_hits, cat_safe_hits, cat_evidence, total, measured = \
        score_text_v48(body, persona=inp.persona)

    # --- 既存出力(v4.7互換)の生成 ---
    risk_level = label_total(total)

    # 懸念リスト(スコア>0のカテゴリ)
    concerns = []
    for cat, score in sorted(cat_scores.items(), key=lambda x: -x[1]):
        if score == 0:
            continue
        disp = DISPLAY_NAME_MAP_V48.get(cat, cat)
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
    raw_questions = pick_questions_v48(
        cat_hits, cat_scores, max_questions=inp.max_questions
    )
    questions = [
        {**q, "selected": q["score"] >= 3}
        for q in raw_questions
    ]

    # ポジティブシグナル
    positive = []
    for cat, guards in cat_safe_hits.items():
        for g in guards:
            note = g.get("note", "")
            if note:
                positive.append(note)
    positive = list(set(positive))

    # --- v4.8 拡張:レーダー8軸スコア ---
    radar_axes = aggregate_to_radar_axes(cat_scores)

    # --- v4.8 拡張:カテゴリ別スコア(画面下部バー用) ---
    category_scores_display = build_category_scores_for_display(cat_scores)

    # --- v4.8 拡張:レスポンス組み立て ---
    response = {
        # 既存フィールド
        "source": source,
        "persona": inp.persona,
        "risk_level": risk_level,
        "total_score": total,
        "concerns": concerns,
        "questions": questions,
        "positive_signals": positive,

        # v4.8 新規
        "radar_axes": radar_axes,
        "radar_display_names": get_radar_display_names(),
        "category_scores": category_scores_display,
    }

    # --- ILORA耐性データあり → マッチ判定を追加 ---
    if inp.user_tolerance:
        # Pydanticモデル → dict 変換
        user_tol_dict = {
            axis_key: tol_score.model_dump() if hasattr(tol_score, 'model_dump')
            else (tol_score.dict() if hasattr(tol_score, 'dict') else tol_score)
            for axis_key, tol_score in inp.user_tolerance.items()
        }
        response["axis_matches"] = compute_axis_matches(radar_axes, user_tol_dict)

    # --- hard_limits あり → 違反チェックを追加 ---
    if inp.hard_limits:
        hard_limits_dict = (
            inp.hard_limits.model_dump() if hasattr(inp.hard_limits, 'model_dump')
            else inp.hard_limits.dict()
        )
        violations = check_hard_limit_violations(body, hard_limits_dict)
        response["hard_limit_violations"] = violations

    # --- セッションID連携 ---
    if inp.ilora_session_id:
        response["ilora_session_id"] = inp.ilora_session_id

    return response


# ================================================================== #
#  メインエンドポイント: /ilora/inquiry
# ================================================================== #

@router.post("/inquiry")
async def submit_inquiry(request: Request, inp: IloraInquiryRequest):
    """
    ユーザーが「相談する」ボタンを押したときに呼ぶ。
    スプレッドシートに記録し、受付確認を返す。
    """
    if not inp.user_email and not inp.user_name:
        raise HTTPException(
            status_code=400,
            detail="user_name または user_email のどちらかを指定してください。"
        )

    concerns_str = "、".join(inp.selected_concerns) if inp.selected_concerns else ""

    # v4.8: hard_limit違反情報の整形
    has_violation = bool(inp.hard_limit_violations)
    violation_summary = "、".join(inp.hard_limit_violations) if inp.hard_limit_violations else ""

    _append_inquiry_log({
        "user_name": inp.user_name,
        "user_email": inp.user_email,
        "company_name": inp.company_name,
        "job_url": inp.job_url,
        "concerns": concerns_str,
        # v4.8 追加
        "ilora_session_id": inp.ilora_session_id or "",
        "entry_point": inp.entry_point,
        "resume_id": inp.resume_id or "",
        "persona": inp.persona,
        "has_hard_limit_violation": has_violation,
        "hard_limit_violation_summary": violation_summary,
    })

    return {
        "ok": True,
        "message": "お問い合わせを受け付けました。ILORA事務局より折り返しご連絡します。",
        "company_name": inp.company_name,
        "received_at": datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=9))
        ).strftime("%Y-%m-%d %H:%M"),
        # v4.8: エコーバックでフロント側の状態同期を助ける
        "ilora_session_id": inp.ilora_session_id,
        "entry_point": inp.entry_point,
    }


# ================================================================== #
#  ヘルスチェック
# ================================================================== #

@router.get("/healthz")
async def ilora_health():
    """ILORA エンドポイントの死活確認"""
    sheet_ok = _get_sheet() is not None
    return {
        "ok": True,
        "service": "ilora-phase15",
        "version": "v4.8",
        "sheets_connected": sheet_ok,
        "supported_personas": ["standard", "lifecycle"],
        "radar_axes": list(get_radar_display_names().keys()),
    }
