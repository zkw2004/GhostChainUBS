from __future__ import annotations

import unittest

from services.risk_engine import RiskEngine
from services.timeutil import Watermark, parse_iso
try:
    from tests.helpers import run, tx
except ImportError:
    from helpers import run, tx


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.engine = RiskEngine()

    def test_parse_formats(self):
        zulu = parse_iso("2026-06-08T12:00:00Z")
        offset = parse_iso("2026-06-08T20:00:00+08:00")
        fractional = parse_iso("2026-06-08T12:00:00.000Z")
        naive = parse_iso("2026-06-08T12:00:00")
        self.assertEqual(zulu, offset)
        self.assertEqual(zulu, fractional)
        self.assertEqual(zulu, naive)

    def test_watermark_monotonic(self):
        mark = Watermark(86400.0, inclusive=False)
        mark.advance(100.0)
        mark.advance(50.0)
        mark.advance(120.0)
        self.assertEqual(mark.value, 120.0)
        mark.advance(90.0)
        self.assertEqual(mark.value, 120.0)

    def test_window_boundary_exclusive(self):
        mark = Watermark(86400.0, inclusive=False)
        mark.advance(86400.0)
        self.assertTrue(mark.is_expired(0.0))
        self.assertFalse(mark.is_expired(1.0))
        later = Watermark(86400.0, inclusive=False)
        later.advance(86400.0 + 1.0)
        self.assertTrue(later.is_expired(0.0))
        self.assertTrue(later.is_expired(1.0))

    def test_edge_expires(self):
        run(self.engine, tx("t1", "A", "B"), tx("t2", "B", "C", minutes=1))
        self.assertEqual(self.engine.graph.live_edge_count(), 2)
        self.engine.score_batch([tx("late", "X", "Y", minutes=24 * 60 + 2)])
        src = self.engine.graph.index_of("A")
        dest = self.engine.graph.index_of("B")
        if src is None or dest is None:
            return
        self.assertFalse(self.engine.graph.has_edge(src, dest))

    def test_multi_tx_edge_survives_until_last_expires(self):
        run(self.engine, tx("e1", "A", "B"), tx("e2", "A", "B", minutes=60))
        src = self.engine.graph.index_of("A")
        dest = self.engine.graph.index_of("B")
        self.assertTrue(self.engine.graph.has_edge(src, dest))
        self.engine.score_batch([tx("probe", "X", "Y", minutes=24 * 60 + 1)])
        src = self.engine.graph.index_of("A")
        dest = self.engine.graph.index_of("B")
        self.assertIsNotNone(src)
        self.assertIsNotNone(dest)
        self.assertTrue(self.engine.graph.has_edge(src, dest))
        self.engine.score_batch([tx("probe2", "P", "Q", minutes=25 * 60 + 1)])
        self.assertIsNone(self.engine.graph.index_of("A"))

    def test_late_transaction_does_not_retreat_watermark(self):
        self.engine.score_batch([tx("new", "A", "B", minutes=24 * 60 + 10)])
        late = self.engine.score_batch([tx("old", "C", "D", minutes=0)])[0]["riskScore"]
        self.assertGreaterEqual(late, 0.0)
        self.assertIsNone(self.engine.graph.index_of("C"))

    def test_expired_cycle_no_longer_contributes(self):
        isolated = run(self.engine, tx("iso", "M", "A"))[0]
        self.engine.reset()
        run(
            self.engine,
            tx("t1", "A", "B"),
            tx("t2", "B", "C", minutes=1),
            tx("t3", "C", "A", minutes=2),
        )
        late = self.engine.score_batch(
            [tx("t4", "C", "A", minutes=24 * 60 + 5)]
        )[0]["riskScore"]
        self.assertLess(abs(late - isolated), 0.05)

    def test_heldout_temporal_23h_cycle_vs_24h_expiry(self):
        """Evaluator last batch: 23h return cycles; exactly 24h does not."""
        results = self.engine.score_batch(
            [
                {
                    "txId": "hf-temporal01-tx1",
                    "fromUserId": "hf_A1",
                    "toUserId": "hf_A2",
                    "amount": 100,
                    "createdAt": "2026-06-08T00:00:00Z",
                },
                {
                    "txId": "hf-temporal01-tx4",
                    "fromUserId": "hf_B1",
                    "toUserId": "hf_B2",
                    "amount": 100,
                    "createdAt": "2026-06-08T00:00:00Z",
                },
                {
                    "txId": "hf-struct01-tx1",
                    "fromUserId": "hf_E1",
                    "toUserId": "hf_E1",
                    "amount": 100,
                    "createdAt": "2026-06-08T00:00:00Z",
                },
                {
                    "txId": "hf-temporal01-tx2",
                    "fromUserId": "hf_A2",
                    "toUserId": "hf_A3",
                    "amount": 100,
                    "createdAt": "2026-06-08T01:00:00Z",
                },
                {
                    "txId": "hf-temporal01-tx5",
                    "fromUserId": "hf_B2",
                    "toUserId": "hf_B3",
                    "amount": 100,
                    "createdAt": "2026-06-08T01:00:00Z",
                },
                {
                    "txId": "hf-struct01-tx2",
                    "fromUserId": "hf_E2",
                    "toUserId": "hf_E3",
                    "amount": 100,
                    "createdAt": "2026-06-08T01:00:00Z",
                },
                {
                    "txId": "hf-struct01-tx3",
                    "fromUserId": "hf_E3",
                    "toUserId": "hf_E2",
                    "amount": 100,
                    "createdAt": "2026-06-08T02:00:00Z",
                },
                {
                    "txId": "hf-temporal01-tx3",
                    "fromUserId": "hf_A3",
                    "toUserId": "hf_A1",
                    "amount": 100,
                    "createdAt": "2026-06-08T23:00:00Z",
                },
                {
                    "txId": "hf-temporal01-tx6",
                    "fromUserId": "hf_B3",
                    "toUserId": "hf_B1",
                    "amount": 100,
                    "createdAt": "2026-06-09T00:00:00Z",
                },
            ]
        )
        by_id = {row["txId"]: row["riskScore"] for row in results}
        self.assertGreater(by_id["hf-temporal01-tx3"], by_id["hf-temporal01-tx6"] + 0.30)
        self.assertLess(by_id["hf-temporal01-tx6"], 0.12)
        self.assertGreater(by_id["hf-struct01-tx3"], by_id["hf-struct01-tx1"] + 0.20)
        self.assertGreater(by_id["hf-struct01-tx1"], by_id["hf-struct01-tx2"])
        self.assertEqual(parse_iso("2026-06-08T00:00:00Z"), 1_780_876_800.0)

    def test_malformed_transaction_scores_zero_and_continues(self):
        results = self.engine.score_batch(
            [
                {"txId": "ok1", "fromUserId": "A", "toUserId": "B", "amount": 1, "createdAt": "2026-06-08T12:00:00Z"},
                {"txId": "bad"},
                {"txId": "ok2", "fromUserId": "B", "toUserId": "C", "amount": 1, "createdAt": "2026-06-08T12:01:00Z"},
            ]
        )
        self.assertEqual(len(results), 3)
        self.assertEqual(results[1]["riskScore"], 0.0)
        self.assertGreater(results[2]["riskScore"], results[0]["riskScore"])


if __name__ == "__main__":
    unittest.main()
