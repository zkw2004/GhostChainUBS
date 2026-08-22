from __future__ import annotations

import unittest

from services.config import CFG
from services.risk_engine import RiskEngine
from services.scoring import combine
try:
    from tests.helpers import run, tx
except ImportError:
    from helpers import run, tx

EX1 = [("t1", "M", "A")]
EX2 = [("t1", "M", "A"), ("t2", "A", "C")]
EX3 = [("t1", "M", "A"), ("t2", "M", "H"), ("t3", "A", "S"), ("t4", "H", "S")]
EX4 = [("t1", "M", "A"), ("t2", "A", "C"), ("t3", "C", "O"), ("t4", "O", "A")]
EX5 = [
    ("t1", "M", "A"),
    ("t2", "A", "C"),
    ("t3", "C", "M"),
    ("t4", "A", "N"),
    ("t5", "N", "M"),
]

EXPECTED_SIGNALS = {
    "EX1": dict(n_new=1, n_red=0, cycle_len=None, ret_mult=0, scc_size=1),
    "EX2": dict(n_new=2, n_red=0, cycle_len=None, ret_mult=0, scc_size=1),
    "EX3": dict(n_new=1, n_red=1, cycle_len=None, ret_mult=0, scc_size=1),
    "EX4": dict(n_new=6, n_red=6, cycle_len=3, ret_mult=1, scc_size=3),
    "EX5": dict(n_new=4, n_red=12, cycle_len=3, ret_mult=2, scc_size=4),
}

EXPECTED_SCORES = {
    "EX1": 0.043,
    "EX2": 0.068,
    "EX3": 0.182,
    "EX4": 0.726,
    "EX5": 0.835,
}


def _edges_to_tx(edges):
    return [tx(tid, frm, to, minutes=index) for index, (tid, frm, to) in enumerate(edges)]


def last_score(engine, edges):
    engine.reset()
    return run(engine, *_edges_to_tx(edges))[-1]


def last_signals(engine, edges):
    engine.reset()
    items = _edges_to_tx(edges)
    if len(items) > 1:
        run(engine, *items[:-1])
    last = items[-1]
    return engine.peek_signals(last["fromUserId"], last["toUserId"])


class GoldenOrderingTests(unittest.TestCase):
    def setUp(self):
        self.engine = RiskEngine()

    def test_signal_values_match_spec(self):
        for name, edges in [
            ("EX1", EX1),
            ("EX2", EX2),
            ("EX3", EX3),
            ("EX4", EX4),
            ("EX5", EX5),
        ]:
            signals = last_signals(self.engine, edges)
            expected = EXPECTED_SIGNALS[name]
            self.assertEqual(signals.n_new, expected["n_new"], name)
            self.assertEqual(signals.n_red, expected["n_red"], name)
            self.assertEqual(signals.cycle_len, expected["cycle_len"], name)
            self.assertEqual(signals.ret_mult, expected["ret_mult"], name)
            self.assertEqual(signals.scc_size, expected["scc_size"], name)

    def test_five_example_scores(self):
        for name, edges in [
            ("EX1", EX1),
            ("EX2", EX2),
            ("EX3", EX3),
            ("EX4", EX4),
            ("EX5", EX5),
        ]:
            score = last_score(self.engine, edges)
            self.assertAlmostEqual(score, EXPECTED_SCORES[name], delta=0.01, msg=name)

    def test_required_inequalities(self):
        s1 = last_score(self.engine, EX1)
        s2 = last_score(self.engine, EX2)
        s3 = last_score(self.engine, EX3)
        s4 = last_score(self.engine, EX4)
        s5 = last_score(self.engine, EX5)
        scores = [s1, s2, s3, s4, s5]
        self.assertEqual(s1, min(scores))
        self.assertGreater(s2, s1 + 0.01)
        self.assertGreater(s3, s2 + 0.05)
        self.assertGreater(s4, s3 + 0.05)
        self.assertGreater(s4 - s2, 0.30)
        self.assertGreater(s5 - s4, 0.05)

    def test_batch_matches_streaming(self):
        items = _edges_to_tx(EX5)
        streamed = run(self.engine, *items)
        self.engine.reset()
        batched = [row["riskScore"] for row in self.engine.score_batch(items)]
        self.assertEqual(streamed, batched)

    def test_coherence_disjoint_components_identical(self):
        a = last_score(self.engine, [("t1", "M", "A")])
        b = last_score(self.engine, [("t1", "X", "Y")])
        self.assertAlmostEqual(a, b)

    def test_coherence_locality(self):
        empty = last_score(self.engine, [("t1", "M", "A")])
        self.engine.reset()
        filler = [tx(f"n{i}", f"X{i}", f"Y{i}", minutes=i) for i in range(8)]
        run(self.engine, *filler)
        dense = self.engine.score_batch([tx("t1", "M", "A", minutes=20)])[0]["riskScore"]
        self.assertAlmostEqual(empty, dense)

    def test_coherence_shorter_cycle_higher(self):
        short_edges = [("t1", "A", "B"), ("t2", "B", "C"), ("t3", "C", "A")]
        long_edges = [
            ("t1", "A", "B"),
            ("t2", "B", "C"),
            ("t3", "C", "D"),
            ("t4", "D", "E"),
            ("t5", "E", "F"),
            ("t6", "F", "A"),
        ]
        short_sig = last_signals(self.engine, short_edges)
        long_sig = last_signals(self.engine, long_edges)
        self.assertIsNotNone(short_sig.cycle_len)
        self.assertIsNotNone(long_sig.cycle_len)
        self.assertLess(short_sig.cycle_len, long_sig.cycle_len)
        self.assertGreater(
            combine(short_sig, CFG).s_cycle, combine(long_sig, CFG).s_cycle + 0.01
        )

    def test_coherence_more_return_paths_higher(self):
        two = last_score(
            self.engine,
            [
                ("t1", "A", "B"),
                ("t2", "B", "C"),
                ("t3", "C", "A"),
                ("t4", "B", "D"),
                ("t5", "D", "A"),
            ],
        )
        three = last_score(
            self.engine,
            [
                ("t1", "A", "B"),
                ("t2", "B", "C"),
                ("t3", "C", "A"),
                ("t4", "B", "D"),
                ("t5", "D", "A"),
                ("t6", "B", "E"),
                ("t7", "E", "A"),
            ],
        )
        self.assertGreater(three, two + 0.01)

    def test_coherence_fan_in(self):
        fan2 = last_score(self.engine, [("t1", "A", "Z"), ("t2", "B", "Z")])
        fan5 = last_score(
            self.engine,
            [
                ("t1", "A", "Z"),
                ("t2", "B", "Z"),
                ("t3", "C", "Z"),
                ("t4", "D", "Z"),
                ("t5", "E", "Z"),
            ],
        )
        self.assertGreater(fan5, fan2 + 0.01)

    def test_coherence_chain_monotonic(self):
        edges = [("t1", "A", "B"), ("t2", "B", "C"), ("t3", "C", "D"), ("t4", "D", "E")]
        self.engine.reset()
        scores = run(self.engine, *_edges_to_tx(edges))
        for left, right in zip(scores, scores[1:]):
            self.assertGreater(right, left)

    def test_coherence_repeat_ordinary_lower(self):
        self.engine.reset()
        first = self.engine.score_batch([tx("a", "M", "A")])[0]["riskScore"]
        second = self.engine.score_batch([tx("b", "M", "A", minutes=1)])[0]["riskScore"]
        self.assertLess(second, first)

    def test_coherence_self_loop_between_isolated_and_cycle(self):
        isolated = last_score(self.engine, [("t1", "M", "A")])
        self_loop = last_score(self.engine, [("t1", "X", "X")])
        cycle = last_score(
            self.engine,
            [("t1", "A", "B"), ("t2", "B", "C"), ("t3", "C", "A")],
        )
        self.assertLess(isolated, self_loop)
        self.assertLess(self_loop, cycle)

    def test_coherence_expired_cycle_drops(self):
        closing = last_score(
            self.engine,
            [("t1", "A", "B"), ("t2", "B", "C"), ("t3", "C", "A")],
        )
        self.engine.reset()
        run(
            self.engine,
            tx("t1", "A", "B", minutes=0),
            tx("t2", "B", "C", minutes=1),
            tx("t3", "C", "A", minutes=2),
        )
        late = self.engine.score_batch(
            [tx("t4", "C", "A", minutes=24 * 60 + 5)]
        )[0]["riskScore"]
        self.assertLess(late + 0.2, closing)

    def test_attach_to_existing_ring_stays_below_cycle(self):
        """Joining a node that already sits on a cycle is not itself a cycle close."""
        cycle = last_score(
            self.engine,
            [("t1", "A", "B"), ("t2", "B", "C"), ("t3", "C", "A")],
        )
        self.engine.reset()
        run(
            self.engine,
            tx("t1", "A", "B"),
            tx("t2", "B", "C", minutes=1),
            tx("t3", "C", "A", minutes=2),
        )
        attach = self.engine.score_batch([tx("t4", "X", "A", minutes=3)])[0]["riskScore"]
        self.assertLess(attach + 0.15, cycle)

    def test_fat_dag_redundancy_stays_below_cycle(self):
        """A high-n_red bridge that does not close a cycle stays in the convergence band."""
        cycle = last_score(
            self.engine,
            [("t1", "A", "B"), ("t2", "B", "C"), ("t3", "C", "A")],
        )
        diamond = last_score(
            self.engine,
            [("t1", "M", "A"), ("t2", "M", "H"), ("t3", "A", "S"), ("t4", "H", "S")],
        )
        self.assertGreater(cycle, diamond + 0.30)
        self.assertLess(diamond, 0.30)

    def test_self_loop_below_mutual_cycle(self):
        isolated = last_score(self.engine, [("t1", "M", "A")])
        self_loop = last_score(self.engine, [("t1", "E1", "E1")])
        mutual = last_score(
            self.engine,
            [("t1", "E2", "E3"), ("t2", "E3", "E2")],
        )
        self.assertLess(isolated, self_loop)
        self.assertLess(self_loop + 0.10, mutual)

    def test_coherence_diamond_beats_tree(self):
        diamond = last_score(
            self.engine,
            [("t1", "M", "A"), ("t2", "M", "H"), ("t3", "A", "S"), ("t4", "H", "S")],
        )
        tree = last_score(
            self.engine,
            [("t1", "M", "A"), ("t2", "M", "H"), ("t3", "A", "S"), ("t4", "H", "T")],
        )
        self.assertGreater(diamond, tree + 0.01)


if __name__ == "__main__":
    unittest.main()
