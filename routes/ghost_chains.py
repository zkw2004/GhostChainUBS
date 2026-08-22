from __future__ import annotations

import logging

from flask import request

from routes import app
from services.risk_engine import engine

logger = logging.getLogger(__name__)


@app.route("/ghost-chains/health", methods=["GET"])
def health():
    return {"status": "ok"}


@app.route("/ghost-chains/reset", methods=["POST"])
def reset():
    data = request.get_json(silent=True) or {}
    engine.reset()
    clear = data.get("clearTransactions", True)
    logger.info("reset clearTransactions=%s", clear)
    return {"clearTransactions": bool(clear)}


@app.route("/ghost-chains/transactions", methods=["POST"])
def transactions():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {"transactions": []}

    raw_transactions = data.get("transactions")
    if not isinstance(raw_transactions, list):
        return {"transactions": []}

    logger.info("scoring %s transaction(s)", len(raw_transactions))
    scored = engine.process_batch(raw_transactions)
    return {"transactions": scored}
