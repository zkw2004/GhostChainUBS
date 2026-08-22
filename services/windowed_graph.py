from __future__ import annotations

import heapq
from collections import deque
from typing import Dict, Iterable, List, Optional, Set, Tuple

from services.graph_models import EdgeState, NodeState, StoredTx


class WindowedGraph:
    """Mutable windowed digraph. The only module allowed to change graph state."""

    def __init__(self) -> None:
        self.clear()

    def clear(self) -> None:
        self._index: Dict[str, int] = {}
        self._label: List[Optional[str]] = []
        self._free: List[int] = []
        self.adj_out: Dict[int, Dict[int, EdgeState]] = {}
        self.adj_in: Dict[int, Set[int]] = {}
        self.nodes: Dict[int, NodeState] = {}
        self.ip_to_nodes: Dict[str, Set[int]] = {}
        self.device_to_nodes: Dict[str, Set[int]] = {}
        self.expiry_heap: List[Tuple[float, str]] = []
        self.tx_by_id: Dict[str, StoredTx] = {}

    def intern(self, entity: str) -> int:
        existing = self._index.get(entity)
        if existing is not None:
            return existing
        if self._free:
            idx = self._free.pop()
            self._label[idx] = entity
        else:
            idx = len(self._label)
            self._label.append(entity)
        self._index[entity] = idx
        self.nodes.setdefault(idx, NodeState())
        self.adj_out.setdefault(idx, {})
        self.adj_in.setdefault(idx, set())
        return idx

    def index_of(self, entity: str) -> Optional[int]:
        return self._index.get(entity)

    def label_of(self, idx: int) -> Optional[str]:
        if 0 <= idx < len(self._label):
            return self._label[idx]
        return None

    def capacity(self) -> int:
        return len(self._label)

    def live_indices(self) -> List[int]:
        return sorted(idx for idx, label in enumerate(self._label) if label is not None)

    def live_node_count(self) -> int:
        return len(self._index)

    def live_edge_count(self) -> int:
        return sum(len(dests) for dests in self.adj_out.values())

    def has_edge(self, src: int | str, dest: int | str) -> bool:
        if isinstance(src, str) or isinstance(dest, str):
            src_idx = self._index.get(str(src))
            dest_idx = self._index.get(str(dest))
            if src_idx is None or dest_idx is None:
                return False
            src, dest = src_idx, dest_idx
        return dest in self.adj_out.get(src, ())

    def successors(self, src: int) -> Iterable[int]:
        return self.adj_out.get(src, {}).keys()

    def predecessors(self, dest: int) -> Iterable[int]:
        return self.adj_in.get(dest, ())

    def in_degree(self, idx: int) -> int:
        return len(self.adj_in.get(idx, ()))

    def out_degree(self, idx: int) -> int:
        return len(self.adj_out.get(idx, ()))

    def add_transaction(self, tx: StoredTx) -> Tuple[int, int]:
        src = self.intern(tx.from_id)
        dest = self.intern(tx.to_id)
        self.tx_by_id[tx.tx_id] = tx
        heapq.heappush(self.expiry_heap, (tx.created_at, tx.tx_id))
        edge = self.adj_out.setdefault(src, {}).get(dest)
        if edge is None:
            edge = EdgeState()
            self.adj_out[src][dest] = edge
            self.adj_in.setdefault(dest, set()).add(src)
        edge.tx_times.append(tx.created_at)
        edge.tx_times.sort()
        edge.total_amount += tx.amount
        self._record_identity(src, dest, tx, edge, increment=True)
        return src, dest

    def expire(self, cutoff: float) -> int:
        removed = 0
        while self.expiry_heap:
            created_at, tx_id = self.expiry_heap[0]
            if created_at > cutoff:
                break
            heapq.heappop(self.expiry_heap)
            stored = self.tx_by_id.get(tx_id)
            if stored is None or stored.created_at != created_at:
                continue
            self._remove_stored(stored)
            removed += 1
        if not self._index:
            self._label.clear()
            self._free.clear()
            self.adj_out.clear()
            self.adj_in.clear()
            self.nodes.clear()
        return removed

    def release_if_isolated(self, idx: int) -> None:
        if idx not in self.nodes:
            return
        if self.out_degree(idx) or self.in_degree(idx):
            return
        self._free_index(idx)

    def shortest_path_len(self, start: int, target: int) -> Optional[int]:
        """BFS edge distance. None if unreachable. start == target returns 0."""
        if start == target:
            return 0
        queue = deque([start])
        dist = {start: 0}
        while queue:
            node = queue.popleft()
            for nbr in self.successors(node):
                if nbr in dist:
                    continue
                dist[nbr] = dist[node] + 1
                if nbr == target:
                    return dist[nbr]
                queue.append(nbr)
        return None

    def undirected_component(self, node: int) -> Set[int]:
        seen = {node}
        queue = deque([node])
        while queue:
            current = queue.popleft()
            neighbours = set(self.successors(current))
            neighbours.update(self.predecessors(current))
            for neighbour in neighbours:
                if neighbour not in seen:
                    seen.add(neighbour)
                    queue.append(neighbour)
        return seen

    def identities_on_nodes(self, nodes: Set[int], kind: str) -> Set[str]:
        values: Set[str] = set()
        for idx in nodes:
            state = self.nodes.get(idx)
            if state is None:
                continue
            values.update(state.ips if kind == "ip" else state.devices)
        return values

    def oldest_edge_time_in_nodes(self, members: Iterable[int]) -> Optional[float]:
        member_set = set(members)
        oldest: Optional[float] = None
        for src in member_set:
            for dest, edge in self.adj_out.get(src, {}).items():
                if dest not in member_set or not edge.tx_times:
                    continue
                candidate = edge.tx_times[0]
                if oldest is None or candidate < oldest:
                    oldest = candidate
        return oldest

    def _remove_stored(self, tx: StoredTx) -> None:
        self.tx_by_id.pop(tx.tx_id, None)
        src = self._index.get(tx.from_id)
        dest = self._index.get(tx.to_id)
        if src is None or dest is None:
            return
        edge = self.adj_out.get(src, {}).get(dest)
        if edge is None:
            return
        try:
            edge.tx_times.remove(tx.created_at)
        except ValueError:
            pass
        edge.total_amount -= tx.amount
        self._record_identity(src, dest, tx, edge, increment=False)
        if not edge.tx_times:
            self.adj_out[src].pop(dest, None)
            incoming = self.adj_in.get(dest)
            if incoming is not None:
                incoming.discard(src)
            if not self.adj_out[src]:
                self.adj_out.pop(src, None)
            if incoming is not None and not incoming:
                self.adj_in.pop(dest, None)
            self.release_if_isolated(src)
            if src != dest:
                self.release_if_isolated(dest)

    def _free_index(self, idx: int) -> None:
        label = self._label[idx] if idx < len(self._label) else None
        if label is not None:
            self._index.pop(label, None)
        if idx < len(self._label):
            self._label[idx] = None
        self.nodes.pop(idx, None)
        self.adj_out.pop(idx, None)
        self.adj_in.pop(idx, None)
        self._free.append(idx)

    def _record_identity(
        self,
        src: int,
        dest: int,
        tx: StoredTx,
        edge: EdgeState,
        increment: bool,
    ) -> None:
        delta = 1 if increment else -1
        src_state = self.nodes.setdefault(src, NodeState())
        dest_state = self.nodes.setdefault(dest, NodeState())
        src_state.total_out += tx.amount * delta
        dest_state.total_in += tx.amount * delta
        if tx.ip_address:
            if increment:
                edge.ip_seen.add(tx.ip_address)
                src_state.ips[tx.ip_address] = src_state.ips.get(tx.ip_address, 0) + 1
                self.ip_to_nodes.setdefault(tx.ip_address, set()).add(src)
            else:
                count = src_state.ips.get(tx.ip_address, 0) + delta
                if count <= 0:
                    src_state.ips.pop(tx.ip_address, None)
                    holders = self.ip_to_nodes.get(tx.ip_address)
                    if holders is not None:
                        holders.discard(src)
                        if not holders:
                            self.ip_to_nodes.pop(tx.ip_address, None)
                else:
                    src_state.ips[tx.ip_address] = count
        else:
            edge.ip_absent_count = max(0, edge.ip_absent_count + delta)
            src_state.tx_missing_ip = max(0, src_state.tx_missing_ip + delta)
        if tx.device_id:
            if increment:
                edge.device_seen.add(tx.device_id)
                src_state.devices[tx.device_id] = src_state.devices.get(tx.device_id, 0) + 1
                self.device_to_nodes.setdefault(tx.device_id, set()).add(src)
            else:
                count = src_state.devices.get(tx.device_id, 0) + delta
                if count <= 0:
                    src_state.devices.pop(tx.device_id, None)
                    holders = self.device_to_nodes.get(tx.device_id)
                    if holders is not None:
                        holders.discard(src)
                        if not holders:
                            self.device_to_nodes.pop(tx.device_id, None)
                else:
                    src_state.devices[tx.device_id] = count
        else:
            edge.device_absent_count = max(0, edge.device_absent_count + delta)
            src_state.tx_missing_device = max(0, src_state.tx_missing_device + delta)
