from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.risk_engine import RiskEngine

BASE = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)


def tx(txid, frm, to, minutes=0, amount=100.0, **kw):
    created = (BASE + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")
    payload = {
        "txId": txid,
        "fromUserId": frm,
        "toUserId": to,
        "amount": amount,
        "createdAt": created,
    }
    payload.update(kw)
    return payload


def run(engine: RiskEngine, *transactions):
    scores = []
    for item in transactions:
        scores.append(engine.score_batch([item])[0]["riskScore"])
    return scores
