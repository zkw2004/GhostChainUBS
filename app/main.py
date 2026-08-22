from __future__ import annotations

import logging
import os

from typing import Optional

from fastapi import FastAPI

from app.engine import RiskEngine
from app.schemas import ResetRequest, ResetResponse, TransactionsRequest, TransactionsResponse

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Ghost Chains")
engine = RiskEngine()


@app.get("/")
def root() -> str:
    return "Ghost Chains"


@app.get("/health")
@app.get("/ghost-chains/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ghost-chains/reset")
def reset(body: Optional[ResetRequest] = None) -> ResetResponse:
    payload = body or ResetRequest()
    if payload.clearTransactions:
        engine.reset()
    return ResetResponse(clearTransactions=payload.clearTransactions)


@app.post("/ghost-chains/transactions")
def transactions(body: TransactionsRequest) -> TransactionsResponse:
    scored = engine.score_batch(body.transactions)
    return TransactionsResponse(transactions=scored)


def create_app() -> FastAPI:
    return app


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, workers=1)
