"""
ilora_endpoint.py
-----------------
ILORA Phase 1.5 専用エンドポイント。
既存の api_app.py に以下2行を追加するだけで動作：

    from ilora_endpoint import router as ilora_router
    app.include_router(ilora_router)

【必要な環境変数】
    GOOGLE_SERVICE_ACCOUNT_JSON  : サービスアカウントJSONの中身をそのまま文字列で
    ILORA_SHEET_ID               : スプレッドシートのID
                                   （URLの /d/XXXXXXXX/edit の XXXXXXXX 部分）

【必要なパッケージ】
    pip install gspread google-auth
"""

import os
import json
import datetime
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from rules_ilora import ilora_concerns, fetch_text_from_url

router = APIRouter(prefix="/ilora", tags=["ilora-phase15"])

# ── Google Sheets クライアント（起動時に一度だけ初期化）──────────────────────
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
            return None  # 環境変数未設定時はログをスキップ

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
    """スプレッドシートに1行追記する。失敗してもエンドポイント自体はエラーにしない。"""
    try:
        sheet = _get_sheet()
        if sheet is None:
            print("[ILORA] スプレッドシート未接続のためログをスキップ")
            return

        # ヘッダーがなければ追加
        existing = sheet.get_all_values()
        if not existing:
            headers = [
                "受付日時",
                "ユーザー名",
                "連絡先（メール）",
                "企業名",
                "求人URL",
                "懸念点",
                "ステータス",
                "企業問い合わせ日",
                "企業回答日",
                "ユーザーへ返答日",
                "結果",
                "備考",
            ]
            sheet.append_row(headers)

        now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
        sheet.append_row([
            now.strftime("%Y-%m-%d %H:%M"),   # 受付日時
            row.get("user_name", ""),           # ユーザー名
            row.get("user_email", ""),          # 連絡先
            row.get("company_name", ""),        # 企業名
            row.get("job_url", ""),             # 求人URL
            row.get("concerns", ""),            # 懸念点（カンマ区切り）
            "受付済み",                          # ステータス初期値
            "", "", "", "", "",                 # 残りは空欄
        ])
        print(f"[ILORA] スプレッドシートに記録しました: {row.get('company_name')}")

    except Exception as e:
        print(f"[ILORA] スプレッドシート書き込みエラー: {e}")


# ── リクエストモデル ────────────────────────────────────────────────────────
class IloraConcernRequest(BaseModel):
    url: str | None = None
    text: str | None = None
    persona: str = "standard"
    max_questions: int = 5


class IloraInquiryRequest(BaseModel):
    """ユーザーが「相談する」ボタンを押したときに呼ぶエンドポイント用"""
    user_name: str = ""
    user_email: str = ""
    company_name: str = ""
    job_url: str = ""
    selected_concerns: list[str] = []   # ユーザーが選んだ懸念点のリスト


# ── エンドポイント ──────────────────────────────────────────────────────────
@router.post("/concerns")
async def get_concerns(request: Request, inp: IloraConcernRequest):
    """
    求人票テキストorURLを受け取り、懸念点・問い文をJSON形式で返す。
    """
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

    result = ilora_concerns(
        text=body,
        persona=inp.persona,
        max_questions=inp.max_questions,
    )

    return {
        "source": source,
        "persona": inp.persona,
        **result,
    }


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

    _append_inquiry_log({
        "user_name":    inp.user_name,
        "user_email":   inp.user_email,
        "company_name": inp.company_name,
        "job_url":      inp.job_url,
        "concerns":     concerns_str,
    })

    return {
        "ok": True,
        "message": "お問い合わせを受け付けました。ILORA事務局より折り返しご連絡します。",
        "company_name": inp.company_name,
        "received_at": datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=9))
        ).strftime("%Y-%m-%d %H:%M"),
    }


@router.get("/healthz")
async def ilora_health():
    """ILORA エンドポイントの死活確認"""
    sheet_ok = _get_sheet() is not None
    return {
        "ok": True,
        "service": "ilora-phase15",
        "sheets_connected": sheet_ok,
    }
