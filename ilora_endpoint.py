"""
ilora_endpoint.py
-----------------
既存の api_app.py に追加する ILORA Phase 1.5 専用エンドポイント。

【notsu-san への作業依頼】
1. このファイルを yabasa-analyzer リポジトリに追加
2. api_app.py の末尾に下記 1 行を追加するだけで完了:
   from ilora_endpoint import router as ilora_router
   app.include_router(ilora_router)

3. rules_ilora.py も同じディレクトリに配置すること

それだけです。既存の /analyze エンドポイントには一切手を加えない。
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from rules_ilora import ilora_concerns, fetch_text_from_url

router = APIRouter(prefix="/ilora", tags=["ilora-phase15"])


class IloraConcernRequest(BaseModel):
    url: str | None = None          # 求人票のURL（url か text のどちらか必須）
    text: str | None = None         # 求人票テキスト直貼り
    persona: str = "standard"       # "standard" | "lifecycle"（35歳以上・子持ち女性向け）
    max_questions: int = 5          # 返す問い文の最大数（デフォルト5、UIで絞り込み）


@router.post("/concerns")
async def get_concerns(request: Request, inp: IloraConcernRequest):
    """
    ILORA Phase 1.5 メインエンドポイント。

    求人票テキストorURLを受け取り、ILORAのUIが直接使えるJSONを返す。

    レスポンス例:
    {
      "risk_level": "中（注意が必要）",
      "total_score": 8,
      "concerns": [
        {
          "category": "給与・待遇",
          "score": 4,
          "summary": "固定給の記載なし（最重大リスク）",
          "evidence": ["...求人票からの抜粋..."]
        }
      ],
      "questions": [
        {
          "id": "fixed_salary",
          "category": "給与・待遇",
          "question": "求人票に基本給の記載がございませんでした...",
          "score": 4,
          "trigger_reason": "固定給の記載なし",
          "selected": true    ← score>=3 はデフォルトtrue
        }
      ],
      "positive_signals": ["育休取得実績・復職率を明記"]
    }
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


@router.get("/healthz")
async def ilora_health():
    """ILORA エンドポイントの死活確認"""
    return {"ok": True, "service": "ilora-phase15"}
