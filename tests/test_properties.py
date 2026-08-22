from __future__ import annotations

import ast
import pathlib
import random

from app.engine import RiskEngine
from tests.helpers import run, tx


def test_no_magic_numbers():
    source = pathlib.Path("app/scoring.py").read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            raise AssertionError(f"float literal {node.value!r} in scoring.py")


def test_score_always_in_range():
    rng = random.Random(3)
    engine = RiskEngine()
    for i in range(80):
        score = engine.score_batch(
            [tx(f"t{i}", f"A{rng.randint(0, 8)}", f"B{rng.randint(0, 8)}", minutes=i)]
        )[0]["riskScore"]
        assert 0.0 <= score <= 1.0


def test_deterministic_after_reset():
    seq = [tx(f"t{i}", f"N{i % 5}", f"N{(i + 1) % 5}", minutes=i) for i in range(20)]
    engine = RiskEngine()
    first = run(engine, *seq)
    engine.reset()
    second = run(engine, *seq)
    assert first == second


def test_disjoint_components_independent():
    engine = RiskEngine()
    seq_a = [tx(f"a{i}", "A", "B" if i == 0 else "A", minutes=i) for i in range(3)]
    seq_a = [
        tx("a0", "A0", "A1"),
        tx("a1", "A1", "A2", minutes=1),
        tx("a2", "A2", "A0", minutes=2),
    ]
    only_a = run(engine, *seq_a)
    engine.reset()
    mixed = []
    mixed_payloads = [
        seq_a[0],
        tx("b0", "Z0", "Z1", minutes=0),
        seq_a[1],
        tx("b1", "Z1", "Z2", minutes=1),
        seq_a[2],
    ]
    scores = run(engine, *mixed_payloads)
    mixed_a = [scores[0], scores[2], scores[4]]
    assert mixed_a == only_a
