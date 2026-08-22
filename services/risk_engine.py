from __future__ import annotations

import threading
from typing import Any, Dict, List

from models.transaction import IdempotencyConflict, Transaction
from services.graph_state import GraphState

# Relative weights. Tune these if evaluator diagnostics report STRUCTURAL_DEVIATION.
CYCLE_WEIGHT = 0.55
CONVERGENCE_WEIGHT = 0.30
REACHABILITY_WEIGHT = 0.15

# Phase 2: added on top of structure so Phase 1 scores stay unchanged
# when ipAddress / deviceId are absent and no upstream identity exists.
IDENTITY_WEIGHT = 0.28
IDENTITY_FLOW_MIX = 0.75
# Shared identity across disconnected components is a hint, not proof.
IDENTITY_SHARE_MIX = 0.22

# Shorter return paths score closer to 1.0; longer ones decay gently.
CYCLE_DISTANCE_DECAY = 0.20
# Mix shortest-cycle strength vs. how many return routes already touch this edge.
CYCLE_LENGTH_MIX = 0.65


def diminishing(count: int) -> float:
    """Map 0, 1, 2, ... onto [0, 1) with diminishing returns."""
    if count <= 0:
        return 0.0
    return 1.0 - (0.5 ** count)


class RiskEngine:
    """Score each transaction against the graph as it currently stands, then insert it."""

    def __init__(self) -> None:
        self.graph = GraphState()
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self.graph.reset()

    def process_batch(self, raw_transactions: List[Any]) -> List[Dict[str, Any]]:
        """Process transactions in order. Later items see earlier items' graph updates."""
        with self._lock:
            results = []
            for raw in raw_transactions:
                tx = Transaction.from_dict(raw)
                results.append(
                    {
                        "txId": tx.tx_id,
                        "riskScore": self._process_one(tx),
                    }
                )
            return results

    def process_one(self, tx: Transaction) -> float:
        with self._lock:
            return self._process_one(tx)

    def _process_one(self, tx: Transaction) -> float:
        existing = self.graph.lookup_idempotency(tx.tx_id)
        if existing is not None:
            fingerprint, original_score = existing
            if fingerprint != tx.fingerprint():
                raise IdempotencyConflict(tx.tx_id)
            # Replay of an identical payload: original score, no graph mutation.
            return original_score

        self.graph.expire_old_transactions(tx.created_at)

        # Score against the graph *before* inserting this edge. Otherwise every
        # transaction would trivially create its own path / cycle.
        risk = self.score_transaction(tx)
        self.graph.add_transaction(tx)
        self.graph.remember_score(tx, risk)
        return risk

    def score_transaction(self, tx: Transaction) -> float:
        source = tx.from_user_id
        dest = tx.to_user_id
        cycle = self.calculate_cycle_signal(source, dest)
        convergence = self.calculate_convergence_signal(source, dest)
        reachability = self.calculate_reachability_signal(source, dest)
        structural = (
            CYCLE_WEIGHT * cycle
            + CONVERGENCE_WEIGHT * convergence
            + REACHABILITY_WEIGHT * reachability
        )
        identity = self.calculate_identity_signal(tx)
        risk = structural + IDENTITY_WEIGHT * identity
        return round(max(0.0, min(1.0, risk)), 6)

    def calculate_identity_signal(self, tx: Transaction) -> float:
        """Identity anomaly in [0, 1]. Zero when there is no identity evidence.

        IP and device are independent. Shared identity across disconnected
        components is a weaker hint than a shift or drop on a connected flow.
        """
        source = tx.from_user_id
        dest = tx.to_user_id
        upstream = self.graph.get_ancestors(source) | {source}
        local = self.graph.get_undirected_component(source) | self.graph.get_undirected_component(
            dest
        )

        shift_ip, drop_ip = self._flow_identity_anomaly(upstream, tx.ip_address, "ip")
        shift_dev, drop_dev = self._flow_identity_anomaly(upstream, tx.device_id, "device")
        shared_ip = self._shared_disconnected(local, tx.ip_address, "ip")
        shared_dev = self._shared_disconnected(local, tx.device_id, "device")

        flow = 1.0 - (
            (1.0 - shift_ip)
            * (1.0 - shift_dev)
            * (1.0 - drop_ip)
            * (1.0 - drop_dev)
        )
        shared = 1.0 - (1.0 - shared_ip) * (1.0 - shared_dev)
        return min(1.0, IDENTITY_FLOW_MIX * flow + IDENTITY_SHARE_MIX * shared)

    def _flow_identity_anomaly(
        self, upstream: set, current: str | None, kind: str
    ) -> tuple[float, float]:
        observed = self.graph.identities_on_nodes(upstream, kind)
        if current:
            if not observed:
                return 0.0, 0.0
            extra = 0 if current in observed else 1
            distinct = len(observed) + extra
            return diminishing(distinct - 1), 0.0
        if observed:
            return 0.0, diminishing(len(observed))
        return 0.0, 0.0

    def _shared_disconnected(
        self, local: set, value: str | None, kind: str
    ) -> float:
        if not value:
            return 0.0
        holders = (
            self.graph.ip_to_entities.get(value, set())
            if kind == "ip"
            else self.graph.device_to_entities.get(value, set())
        )
        foreign = set(holders) - local
        if not foreign:
            return 0.0
        components = 0
        remaining = set(foreign)
        while remaining:
            seed = remaining.pop()
            remaining -= self.graph.get_undirected_component(seed)
            components += 1
        return diminishing(components)

    def calculate_cycle_signal(self, source: str, dest: str) -> float:
        """Return-flow / cycle strength for a prospective edge source → dest.

        BFS from dest toward source: if dest can already reach source, then
        adding source → dest closes a directed cycle (money looping back).
        """
        if source == dest:
            return 1.0

        distance = self.graph.shortest_path_length(dest, source)
        if distance is None:
            return 0.0

        # Nodes already on some dest ⇝ source walk. Direct edges have no
        # intermediate nodes, so they still count as one return route.
        route_nodes = self.graph.get_descendants(dest) & self.graph.get_ancestors(source)
        n_routes = max(1, len(route_nodes))
        base = 1.0 / (1.0 + CYCLE_DISTANCE_DECAY * (distance - 1))
        routes = diminishing(n_routes)
        return min(1.0, CYCLE_LENGTH_MIX * base + (1.0 - CYCLE_LENGTH_MIX) * routes)

    def calculate_convergence_signal(self, source: str, dest: str) -> float:
        """Alternative-route strength for a prospective edge source → dest.

        If an ancestor of source can already reach dest, this edge adds a second
        structural route from that ancestor to dest (diamond / fan-in).
        Direct duplicate edges (distance 1) are not treated as a new route.
        """
        common = self.graph.get_ancestors(source) & self.graph.get_ancestors(dest)
        count = len(common)
        existing = self.graph.shortest_path_length(source, dest)
        if existing is not None and existing >= 2:
            count += 1
        return diminishing(count)

    def calculate_reachability_signal(self, source: str, dest: str) -> float:
        """Smaller signal: how much existing structure this edge would join.

        Distinguishes an isolated first edge from an extension of a chain,
        without making ordinary commercial chains look like cycles.
        """
        upstream = len(self.graph.get_ancestors(source)) + 1
        downstream = len(self.graph.get_descendants(dest)) + 1
        extra = upstream + downstream - 2
        return diminishing(extra)


engine = RiskEngine()
