from __future__ import annotations

import random
import time

import pytest

from app.engine import RiskEngine
from tests.helpers import tx


@pytest.mark.slow
def test_throughput():
    rng = random.Random(11)
    engine = RiskEngine()
    latencies = []
    entities = [f"e{i}" for i in range(200)]
    for i in range(3000):
        src = rng.choice(entities)
        dest = rng.choice(entities)
        minutes = int((i / 3000) * 48 * 60)
        start = time.perf_counter()
        engine.score_batch([tx(f"t{i}", src, dest, minutes=minutes)])
        latencies.append(time.perf_counter() - start)
    latencies.sort()
    p95 = latencies[int(0.95 * len(latencies))]
    assert p95 < 0.025


@pytest.mark.slow
def test_memory_bounded_by_window():
    rng = random.Random(12)
    engine = RiskEngine()
    samples = []
    entities = [f"e{i}" for i in range(400)]
    for i in range(4000):
        minutes = int((i / 4000) * 48 * 60)
        engine.score_batch(
            [tx(f"t{i}", rng.choice(entities), rng.choice(entities), minutes=minutes)]
        )
        if i % 1000 == 999:
            samples.append(engine.graph.live_node_count())
    later = samples[-3:]
    peak = max(later) or 1
    assert max(later) - min(later) < 0.10 * peak
