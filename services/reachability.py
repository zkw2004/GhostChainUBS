from __future__ import annotations

from collections import deque
from typing import Iterable, List, Optional, Set

from services.config import CFG
from services.windowed_graph import WindowedGraph


def bit(index: int) -> int:
    return 1 << index


def iter_bits(mask: int) -> Iterable[int]:
    while mask:
        isolated = mask & -mask
        yield isolated.bit_length() - 1
        mask ^= isolated


def popcount(mask: int) -> int:
    if hasattr(mask, "bit_count"):
        return mask.bit_count()
    return bin(mask).count("1")


class NaiveReachability:
    """Obviously-correct BFS oracle. Production never calls this."""

    def __init__(self, graph: WindowedGraph) -> None:
        self.graph = graph

    def descendants(self, node: int) -> Set[int]:
        seen: Set[int] = set()
        queue = deque(self.graph.successors(node))
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            queue.extend(self.graph.successors(current))
        return seen

    def ancestors(self, node: int) -> Set[int]:
        seen: Set[int] = set()
        queue = deque(self.graph.predecessors(node))
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            queue.extend(self.graph.predecessors(current))
        return seen

    def reaches(self, src: int, dest: int) -> bool:
        if src == dest:
            return src in self.descendants(src)
        return dest in self.descendants(src)

    def shortest_path_len(self, src: int, dest: int) -> Optional[int]:
        return self.graph.shortest_path_len(src, dest)

    def descendant_mask(self, node: int) -> int:
        mask = 0
        for item in self.descendants(node):
            mask |= bit(item)
        return mask

    def ancestor_mask(self, node: int) -> int:
        mask = 0
        for item in self.ancestors(node):
            mask |= bit(item)
        return mask


class BitsetReachability:
    """Incremental insert, full rebuild on expiry. Falls back to BFS above MAX_BITSET_NODES."""

    def __init__(self, graph: WindowedGraph) -> None:
        self.graph = graph
        self.desc: List[int] = []
        self.anc: List[int] = []
        self._dirty = False

    def clear(self) -> None:
        self.desc = []
        self.anc = []
        self._dirty = False

    def mark_dirty(self) -> None:
        self._dirty = True

    def ensure_fresh(self) -> None:
        if self._dirty:
            self.rebuild()

    def _use_naive(self) -> bool:
        return self.graph.live_node_count() > CFG.MAX_BITSET_NODES

    def _grow(self, size: int) -> None:
        while len(self.desc) < size:
            self.desc.append(0)
            self.anc.append(0)

    def rebuild(self) -> None:
        naive = NaiveReachability(self.graph)
        size = self.graph.capacity()
        self.desc = [0] * size
        self.anc = [0] * size
        for node in self.graph.live_indices():
            self.desc[node] = naive.descendant_mask(node)
            self.anc[node] = naive.ancestor_mask(node)
        self._dirty = False

    def insert_edge(self, src: int, dest: int, already_existed: bool) -> None:
        if self._dirty:
            return
        if self._use_naive():
            self.mark_dirty()
            return
        self._grow(max(src, dest) + 1)
        dest_cone = self.desc[dest] | bit(dest)
        newly = dest_cone & ~self.desc[src]
        if newly == 0 and already_existed:
            return
        src_cone = self.anc[src] | bit(src)
        for walker in iter_bits(src_cone):
            self._grow(walker + 1)
            self.desc[walker] |= dest_cone
        for reached in iter_bits(dest_cone):
            self._grow(reached + 1)
            self.anc[reached] |= src_cone

    def descendant_mask(self, node: int) -> int:
        if self._use_naive():
            return NaiveReachability(self.graph).descendant_mask(node)
        self.ensure_fresh()
        if node >= len(self.desc):
            return 0
        return self.desc[node]

    def ancestor_mask(self, node: int) -> int:
        if self._use_naive():
            return NaiveReachability(self.graph).ancestor_mask(node)
        self.ensure_fresh()
        if node >= len(self.anc):
            return 0
        return self.anc[node]

    def reaches(self, src: int, dest: int) -> bool:
        if src == dest:
            return bool(self.descendant_mask(src) & bit(src))
        return bool(self.descendant_mask(src) & bit(dest))

    def shortest_path_len(self, src: int, dest: int) -> Optional[int]:
        return self.graph.shortest_path_len(src, dest)
