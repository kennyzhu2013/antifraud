"""FastAPI 服务：案例入库查询 + 通话风险检测。

启动：uvicorn antifraud_agent.api:app --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import settings
from .crawler import crawl_urls
from .detection import CallRiskDetector
from .extraction import extract_case
from .schemas import DetectionResult, FraudCase
from .store import CaseStore

store: CaseStore | None = None
detector: CallRiskDetector | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global store, detector
    store = CaseStore(settings.db_path)
    detector = CallRiskDetector(store)
    yield
    store.close()


app = FastAPI(title="反诈案例库与通话风险检测", version="0.1.0", lifespan=lifespan)


class DetectRequest(BaseModel):
    transcript: str = Field(..., description="ASR 转写后的通话文本")


class CrawlRequest(BaseModel):
    urls: list[str] = Field(..., description="来源白名单内的文章 URL 列表")


class CrawlResponse(BaseModel):
    fetched: int
    ingested: int
    case_ids: list[str]


@app.post("/detect", response_model=DetectionResult, summary="通话文本风险检测")
def detect(req: DetectRequest) -> DetectionResult:
    if not req.transcript.strip():
        raise HTTPException(400, "transcript 不能为空")
    return detector.detect(req.transcript)


@app.post("/crawl", response_model=CrawlResponse, summary="抓取 URL 并抽取入库")
def crawl(req: CrawlRequest) -> CrawlResponse:
    docs = crawl_urls(req.urls)
    case_ids = []
    for doc in docs:
        case = extract_case(doc)
        if case and store.upsert_case(case):
            case_ids.append(case.case_id)
    return CrawlResponse(fetched=len(docs), ingested=len(case_ids), case_ids=case_ids)


@app.get("/cases/{case_id}", response_model=FraudCase, summary="查询单条案例")
def get_case(case_id: str) -> FraudCase:
    case = store.get(case_id)
    if case is None:
        raise HTTPException(404, "案例不存在")
    return case


@app.get("/stats", summary="案例库统计")
def stats() -> dict:
    cases = store.all_cases()
    by_type: dict[str, int] = {}
    for c in cases:
        by_type[c.fraud_type] = by_type.get(c.fraud_type, 0) + 1
    return {"total": len(cases), "by_fraud_type": by_type}
