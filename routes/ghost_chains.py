from __future__ import annotations

import logging

from flask import request

from models.transaction import IdempotencyConflict
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
    return {"clearTransactions": bool(clear)}


@app.route("/ghost-chains/transactions", methods=["POST"])
def transactions():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {"error": "request body must be a JSON object"}, 400

    raw_transactions = data.get("transactions")
    if not isinstance(raw_transactions, list):
        return {"error": "transactions must be an array"}, 400

    logger.info("scoring %s transaction(s)", len(raw_transactions))
    try:
        scored = engine.process_batch(raw_transactions)
    except IdempotencyConflict as exc:
        return {
            "error": "duplicate txId with a different payload",
            "txId": exc.tx_id,
        }, 400
    except ValueError as exc:
        return {"error": str(exc)}, 400

    return {"transactions": scored}
