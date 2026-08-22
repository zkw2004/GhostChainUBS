from __future__ import annotations

import random

from app.graph import WindowedGraph
from app.models import StoredTx
from app.reachability import BitsetReachability, NaiveReachability


def test_naive_basic():
    graph = WindowedGraph()
    naive = NaiveReachability(graph)
    _add(graph, "t1", "A", "B", 0)
    _add(graph, "t2", "B", "C", 1)
    a = graph.index_of("A")
    c = graph.index_of("C")
    assert naive.reaches(a, c)
    assert naive.shortest_path_len(a, c) == 2
    assert not naive.reaches(c, a)


def test_matches_naive_random():
    rng = random.Random(0)
    _compare_random(rng, sequences=200, include_expiry=False)


def test_matches_naive_with_expiry():
    rng = random.Random(1)
    _compare_random(rng, sequences=200, include_expiry=True)


def _compare_random(rng: random.Random, sequences: int, include_expiry: bool) -> None:
    nodes = [f"n{i}" for i in range(12)]
    for seq in range(sequences):
        graph = WindowedGraph()
        fast = BitsetReachability(graph)
        slow = NaiveReachability(graph)
        clock = 0.0
        for step in range(25):
            clock += 1.0
            src = rng.choice(nodes)
            dest = rng.choice(nodes)
            src_before = graph.index_of(src)
            dest_before = graph.index_of(dest)
            existed = (
                src_before is not None
                and dest_before is not None
                and graph.has_edge(src_before, dest_before)
            )
            _add(graph, f"{seq}-{step}", src, dest, clock)
            fast.insert_edge(graph.index_of(src), graph.index_of(dest), already_existed=existed)
            if include_expiry and step % 7 == 6:
                removed = graph.expire(clock - 8.0)
                if removed:
                    fast.mark_dirty()
                    fast.ensure_fresh()
            live = graph.live_indices()
            for a in live:
                for b in live:
                    assert fast.reaches(a, b) == slow.reaches(a, b)


def _add(graph: WindowedGraph, tx_id: str, src: str, dest: str, created_at: float) -> None:
    graph.add_transaction(
        StoredTx(
            tx_id=tx_id,
            from_id=src,
            to_id=dest,
            amount=1.0,
            created_at=created_at,
            ip_address=None,
            device_id=None,
            payload_hash="h",
            score=0.0,
        )
    )
