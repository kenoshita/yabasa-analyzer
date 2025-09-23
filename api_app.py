from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Yabasa Analyzer")

# 静的ファイルのマウント
app.mount("/static", StaticFiles(directory="static", html=True), name="static")
app.mount("/landing", StaticFiles(directory="landing", html=True), name="landing")

class InputText(BaseModel):
    text: str

@app.post("/analyze")
def analyze(inp: InputText):
    # 仮の判定ロジック（rules.pyを利用する想定）
    score = 42
    return {"score": score, "message": "判定結果のサンプル"}
