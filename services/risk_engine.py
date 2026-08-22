from __future__ import annotations

import hashlib
import json
import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

from models.transaction import Transaction
from services.config import CFG, ScoringConfig
from services.graph_models import StoredTx
from services.reachability import BitsetReachability
from services.scoring import combine, extract_identity, extract_signals
from services.timeutil import parse_iso, watermark_from_config
from services.windowed_graph import WindowedGraph

logger = logging.getLogger(__name__)


class RiskEngine:
    """Orchestrates idempotency, event-time expiry, scoring, and insertion."""

    def __init__(self, cfg: Optional[Any] = None) -> None:
        if cfg is not None and not isinstance(cfg, ScoringConfig):
            cfg = None
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

    def process_batch(self, raw_transactions: List[Any]) -> List[Dict[str, Any]]:
        return self.score_batch(raw_transactions)

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

    def process_one(self, tx: Transaction) -> float:
        raw = {
            "txId": tx.tx_id,
            "fromUserId": tx.from_user_id,
            "toUserId": tx.to_user_id,
            "amount": tx.amount,
            "createdAt": tx.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ipAddress": tx.ip_address,
            "deviceId": tx.device_id,
        }
        with self._lock:
            return self._score_one_unlocked(raw)

    def score_transaction(self, tx: Transaction) -> float:
        """Compatibility hook for older tests. Scores and inserts."""
        return self.process_one(tx)

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
        identity = extract_identity(
            self.graph, self.reach, src, dest, ip_address, device_id, self.cfg
        )

        temporal_span = None
        if self.cfg.ENABLE_TEMPORAL_MULTIPLIER and signals.cycle_closed:
            oldest = self.graph.oldest_edge_time_in_nodes([src, dest])
            if oldest is not None and self.watermark.value is not None:
                temporal_span = self.watermark.value - oldest

        breakdown = combine(
            signals, self.cfg, temporal_span=temporal_span, identity=identity
        )
        logger.info(
            "tx %s %s->%s score=%.6f n_new=%s n_red=%s cycle=%s len=%s "
            "fan=%s scc=%s ret=%s shift=%.3f drop=%.3f share=%.3f ip=%s dev=%s t=%.0f",
            tx_id,
            from_id,
            to_id,
            breakdown.score,
            signals.n_new,
            signals.n_red,
            int(signals.cycle_closed),
            signals.cycle_len,
            breakdown.s_fan,
            signals.scc_size,
            signals.ret_mult,
            breakdown.s_id_shift,
            breakdown.s_id_drop,
            breakdown.s_id_share,
            ip_address,
            device_id,
            created_at,
        )

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
            self.reach.insert_edge(src, dest, already_existed=existed)

        self._scores[tx_id] = (payload_hash, breakdown.score)
        return breakdown.score

    def peek_signals(self, from_id: str, to_id: str) -> Any:
        with self._lock:
            src = self.graph.intern(from_id)
            dest = self.graph.intern(to_id)
            self.reach.ensure_fresh()
            return extract_signals(self.graph, self.reach, src, dest)

    def calculate_cycle_signal(self, source: str, dest: str) -> float:
        signals = self.peek_signals(source, dest)
        return combine(signals, self.cfg).s_cycle

    def calculate_identity_signal(self, tx: Transaction) -> float:
        with self._lock:
            src = self.graph.intern(tx.from_user_id)
            dest = self.graph.intern(tx.to_user_id)
            self.reach.ensure_fresh()
            identity = extract_identity(
                self.graph,
                self.reach,
                src,
                dest,
                tx.ip_address,
                tx.device_id,
                self.cfg,
            )
            return max(identity.shift, identity.drop, identity.share)

    def lookup_idempotency(self, tx_id: str) -> Optional[Tuple[str, float]]:
        return self._scores.get(tx_id)

    def edge_count(self, source: str, dest: str) -> int:
        src = self.graph.index_of(source)
        dst = self.graph.index_of(dest)
        if src is None or dst is None:
            return 0
        edge = self.graph.adj_out.get(src, {}).get(dst)
        if edge is None:
            return 0
        return edge.multiplicity

    def has_named_edge(self, source: str, dest: str) -> bool:
        src = self.graph.index_of(source)
        dst = self.graph.index_of(dest)
        if src is None or dst is None:
            return False
        return self.graph.has_edge(src, dst)


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


engine = RiskEngine()
