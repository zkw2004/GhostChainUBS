from __future__ import annotations

import heapq
from collections import deque
from datetime import datetime, timedelta
from typing import Dict, Optional, Set, Tuple

from models.transaction import Transaction

# A transaction stays active iff created_at >= incoming_created_at - 24 hours.
# Exactly 24 hours old is still active; older than 24 hours is expired.
LOOKBACK = timedelta(hours=24)

Edge = Tuple[str, str]


class GraphState:
    """Directed transaction graph for the active 24-hour window.

    Edges are reference-counted. Two transfers A→B produce edge_counts[(A, B)] == 2.
    Expiring one supporting transaction decrements the count; the adjacency edge is
    removed only when the count reaches zero.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        # node -> successors (an edge exists while its count is > 0)
        self.adjacency: Dict[str, Set[str]] = {}
        # node -> predecessors, used for ancestor BFS
        self.reverse_adjacency: Dict[str, Set[str]] = {}
        # (from, to) -> number of active transactions on that pair
        self.edge_counts: Dict[Edge, int] = {}
        # txId -> transaction currently contributing to the graph
        self.active_by_id: Dict[str, Transaction] = {}
        # min-heap of (created_at, txId) for incremental expiry
        self._expiry_heap: list[tuple[datetime, str]] = []
        # txId -> (fingerprint, original riskScore); survives expiry
        self.idempotency: Dict[str, tuple[tuple, float]] = {}
        # Phase 2 identity indexes. Counts honour the same 24-hour window as edges.
        self.node_ips: Dict[str, Dict[str, int]] = {}
        self.node_devices: Dict[str, Dict[str, int]] = {}
        self.node_ip_absent: Dict[str, int] = {}
        self.node_device_absent: Dict[str, int] = {}
        self.ip_to_entities: Dict[str, Set[str]] = {}
        self.device_to_entities: Dict[str, Set[str]] = {}

    def expire_old_transactions(self, now: datetime) -> None:
        """Drop transactions older than the 24-hour lookback relative to `now`."""
        cutoff = now - LOOKBACK
        while self._expiry_heap:
            created_at, tx_id = self._expiry_heap[0]
            if created_at >= cutoff:
                break
            heapq.heappop(self._expiry_heap)
            active = self.active_by_id.get(tx_id)
            if active is None or active.created_at != created_at:
                continue
            self._remove_active(active)

    def add_transaction(self, tx: Transaction) -> None:
        self.active_by_id[tx.tx_id] = tx
        heapq.heappush(self._expiry_heap, (tx.created_at, tx.tx_id))
        self._increment_edge(tx.from_user_id, tx.to_user_id)
        self._apply_identity(tx, increment=True)

    def remember_score(self, tx: Transaction, risk_score: float) -> None:
        self.idempotency[tx.tx_id] = (tx.fingerprint(), risk_score)

    def lookup_idempotency(self, tx_id: str) -> Optional[tuple[tuple, float]]:
        return self.idempotency.get(tx_id)

    def shortest_path_length(self, start: str, target: str) -> Optional[int]:
        """BFS edge-distance from start to target. 0 if start == target. None if unreachable."""
        if start == target:
            return 0
        distances = self._bfs(start, self.adjacency)
        if target not in distances:
            return None
        return distances[target]

    def get_ancestors(self, node: str) -> Set[str]:
        """Nodes that can already reach `node` (reverse BFS). Does not include `node`."""
        distances = self._bfs(node, self.reverse_adjacency)
        distances.pop(node, None)
        return set(distances)

    def get_descendants(self, node: str) -> Set[str]:
        """Nodes already reachable from `node` (forward BFS). Does not include `node`."""
        distances = self._bfs(node, self.adjacency)
        distances.pop(node, None)
        return set(distances)

    def has_edge(self, source: str, dest: str) -> bool:
        return self.edge_counts.get((source, dest), 0) > 0

    def get_undirected_component(self, node: str) -> Set[str]:
        """Entities in the same weakly connected component as `node`."""
        if node not in self.adjacency and node not in self.reverse_adjacency:
            return {node}
        seen = {node}
        queue = deque([node])
        while queue:
            current = queue.popleft()
            neighbours = set(self.adjacency.get(current, ()))
            neighbours.update(self.reverse_adjacency.get(current, ()))
            for neighbour in neighbours:
                if neighbour not in seen:
                    seen.add(neighbour)
                    queue.append(neighbour)
        return seen

    def identities_on_nodes(self, nodes: Set[str], kind: str) -> Set[str]:
        store = self.node_ips if kind == "ip" else self.node_devices
        values: Set[str] = set()
        for entity in nodes:
            values.update(store.get(entity, ()))
        return values

    def edge_count(self, source: str, dest: str) -> int:
        return self.edge_counts.get((source, dest), 0)

    def _bfs(self, start: str, adjacency: Dict[str, Set[str]]) -> Dict[str, int]:
        distances = {start: 0}
        queue = deque([start])
        while queue:
            node = queue.popleft()
            for neighbour in adjacency.get(node, ()):
                if neighbour not in distances:
                    distances[neighbour] = distances[node] + 1
                    queue.append(neighbour)
        return distances

    def _increment_edge(self, source: str, dest: str) -> None:
        edge = (source, dest)
        self.edge_counts[edge] = self.edge_counts.get(edge, 0) + 1
        self.adjacency.setdefault(source, set()).add(dest)
        self.reverse_adjacency.setdefault(dest, set()).add(source)

    def _decrement_edge(self, source: str, dest: str) -> None:
        edge = (source, dest)
        remaining = self.edge_counts.get(edge, 0) - 1
        if remaining > 0:
            self.edge_counts[edge] = remaining
            return
        self.edge_counts.pop(edge, None)
        successors = self.adjacency.get(source)
        if successors is not None:
            successors.discard(dest)
            if not successors:
                del self.adjacency[source]
        predecessors = self.reverse_adjacency.get(dest)
        if predecessors is not None:
            predecessors.discard(source)
            if not predecessors:
                del self.reverse_adjacency[dest]

    def _remove_active(self, tx: Transaction) -> None:
        self.active_by_id.pop(tx.tx_id, None)
        self._decrement_edge(tx.from_user_id, tx.to_user_id)
        self._apply_identity(tx, increment=False)

    def _apply_identity(self, tx: Transaction, increment: bool) -> None:
        # ipAddress / deviceId describe who initiated the transfer.
        # Tag both endpoints so shared identity can link counterparties
        # that never transact with each other.
        delta = 1 if increment else -1
        endpoints = (tx.from_user_id, tx.to_user_id)
        sender = tx.from_user_id
        if tx.ip_address:
            for entity in endpoints:
                self._touch_value(
                    entity, tx.ip_address, self.node_ips, self.ip_to_entities, delta
                )
        else:
            self.node_ip_absent[sender] = self.node_ip_absent.get(sender, 0) + delta
            if self.node_ip_absent[sender] <= 0:
                self.node_ip_absent.pop(sender, None)
        if tx.device_id:
            for entity in endpoints:
                self._touch_value(
                    entity,
                    tx.device_id,
                    self.node_devices,
                    self.device_to_entities,
                    delta,
                )
        else:
            self.node_device_absent[sender] = self.node_device_absent.get(sender, 0) + delta
            if self.node_device_absent[sender] <= 0:
                self.node_device_absent.pop(sender, None)

    def _touch_value(
        self,
        entity: str,
        value: str,
        node_map: Dict[str, Dict[str, int]],
        reverse_index: Dict[str, Set[str]],
        delta: int,
    ) -> None:
        counts = node_map.setdefault(entity, {})
        counts[value] = counts.get(value, 0) + delta
        if counts[value] <= 0:
            counts.pop(value, None)
            holders = reverse_index.get(value)
            if holders is not None:
                holders.discard(entity)
                if not holders:
                    reverse_index.pop(value, None)
            if not counts:
                node_map.pop(entity, None)
            return
        reverse_index.setdefault(value, set()).add(entity)
