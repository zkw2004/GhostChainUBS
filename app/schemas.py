from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class TransactionIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    txId: str
    fromUserId: str
    toUserId: str
    amount: float
    createdAt: str
    ipAddress: Optional[str] = None
    deviceId: Optional[str] = None


class TransactionsRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    transactions: List[Any] = Field(default_factory=list)


class ScoreOut(BaseModel):
    txId: str
    riskScore: float


class TransactionsResponse(BaseModel):
    transactions: List[ScoreOut]


class ResetRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    clearTransactions: bool = True


class ResetResponse(BaseModel):
    clearTransactions: bool
