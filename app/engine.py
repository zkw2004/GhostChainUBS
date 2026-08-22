from __future__ import annotations

import hashlib
import json
import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

from app.config import CFG, ScoringConfig
from app.graph import WindowedGraph
from app.models import ScoreBreakdown, StoredTx
from app.reachability import BitsetReachability
from app.scoring import combine, extract_signals
from app.timeutil import Watermark, parse_iso, watermark_from_config

logger = logging.getLogger(__name__)


class RiskEngine:
    """Orchestrates idempotency, event-time expiry, scoring, and insertion."""

    def __init__(self, cfg: Optional[ScoringConfig] = None) -> None:
        self.cfg = cfg or CFG
        self._lock = threading.Lock()
        self.graph = WindowedGraph()
        self.reach = BitsetReachability(self.graph)
        self.watermark = watermark_from_config(self.cfg)
        self._scores: Dict[str, Tuple[str, float]] = {}

    def reset(self) -> None:
        with self._lock:
            self._reset_unlocked()

    def _reset_unlocked(self) -> None:
        self.graph.clear()
        self.reach.clear()
        self.watermark.reset()
        self._scores.clear()

    def score_batch(self, raw_transactions: List[Any]) -> List[Dict[str, Any]]:
        with self._lock:
            results: List[Dict[str, Any]] = []
            for raw in raw_transactions:
                tx_id = ""
                try:
                    if not isinstance(raw, dict):
                        results.append({"txId": "", "riskScore": 0.0})
                        continue
                    tx_id = str(raw.get("txId") or "")
                    results.append(
                        {"txId": tx_id, "riskScore": self._score_one_unlocked(raw)}
                    )
                except Exception:
                    logger.exception("failed scoring transaction %s", tx_id)
                    results.append({"txId": tx_id, "riskScore": 0.0})
            return results

    def _score_one_unlocked(self, raw: Dict[str, Any]) -> float:
        tx_id = raw.get("txId")
        from_id = raw.get("fromUserId")
        to_id = raw.get("toUserId")
        amount = raw.get("amount")
        created_at_raw = raw.get("createdAt")
        if not isinstance(tx_id, str) or not tx_id:
            return 0.0
        if not isinstance(from_id, str) or not from_id:
            return 0.0
        if not isinstance(to_id, str) or not to_id:
            return 0.0
        if amount is None or created_at_raw is None:
            return 0.0
        try:
            amount_value = float(amount)
            created_at = parse_iso(str(created_at_raw))
        except (TypeError, ValueError):
            return 0.0

        ip_address = raw.get("ipAddress")
        device_id = raw.get("deviceId")
        if ip_address is not None:
            ip_address = str(ip_address)
        if device_id is not None:
            device_id = str(device_id)

        payload_hash = _payload_hash(
            from_id, to_id, amount_value, created_at, ip_address, device_id
        )
        existing = self._scores.get(tx_id)
        if existing is not None:
            stored_hash, stored_score = existing
            if stored_hash != payload_hash:
                logger.warning(
                    "conflicting payload for txId=%s stored=%s incoming=%s",
                    tx_id,
                    stored_hash,
                    payload_hash,
                )
            return stored_score

        self.watermark.advance(created_at)
        cutoff = self.watermark.cutoff()
        if cutoff is not None:
            removed = self.graph.expire(cutoff)
            if removed:
                self.reach.mark_dirty()
                self.reach.ensure_fresh()

        already_expired = self.watermark.is_expired(created_at)
        src = self.graph.intern(from_id)
        dest = self.graph.intern(to_id)
        self.reach.ensure_fresh()
        signals = extract_signals(self.graph, self.reach, src, dest)

        temporal_span = None
        if self.cfg.ENABLE_TEMPORAL_MULTIPLIER and signals.cycle_closed:
            scc_nodes = _bits_to_nodes(src, dest, signals.scc_size)
            oldest = self.graph.oldest_edge_time_in_nodes(
                [src, dest] if not scc_nodes else scc_nodes
            )
            if oldest is not None and self.watermark.value is not None:
                temporal_span = self.watermark.value - oldest

        breakdown = combine(signals, self.cfg, temporal_span=temporal_span)
        logger.debug("score breakdown txId=%s %s", tx_id, breakdown)

        if already_expired:
            self.graph.release_if_isolated(src)
            if src != dest:
                self.graph.release_if_isolated(dest)
        else:
            stored = StoredTx(
                tx_id=tx_id,
                from_id=from_id,
                to_id=to_id,
                amount=amount_value,
                created_at=created_at,
                ip_address=ip_address,
                device_id=device_id,
                payload_hash=payload_hash,
                score=breakdown.score,
            )
            existed = self.graph.has_edge(src, dest)
            self.graph.add_transaction(stored)
            if not existed:
                self.reach.insert_edge(src, dest, already_existed=False)
            else:
                self.reach.insert_edge(src, dest, already_existed=True)

        self._scores[tx_id] = (payload_hash, breakdown.score)
        return breakdown.score

    def peek_signals(self, from_id: str, to_id: str) -> Any:
        with self._lock:
            src = self.graph.intern(from_id)
            dest = self.graph.intern(to_id)
            self.reach.ensure_fresh()
            return extract_signals(self.graph, self.reach, src, dest)


def _payload_hash(
    from_id: str,
    to_id: str,
    amount: float,
    created_at: float,
    ip_address: Optional[str],
    device_id: Optional[str],
) -> str:
    blob = json.dumps(
        {
            "fromUserId": from_id,
            "toUserId": to_id,
            "amount": amount,
            "createdAt": created_at,
            "ipAddress": ip_address,
            "deviceId": device_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _bits_to_nodes(*nodes: int) -> List[int]:
    return list(nodes)
