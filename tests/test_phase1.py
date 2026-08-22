from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from models.transaction import IdempotencyConflict, Transaction
from services.risk_engine import RiskEngine


T0 = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)


def tx(tx_id, source, dest, minutes=0, amount=100.0, **extra):
    created = T0 + timedelta(minutes=minutes)
    payload = {
        "txId": tx_id,
        "fromUserId": source,
        "toUserId": dest,
        "amount": amount,
        "createdAt": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    payload.update(extra)
    return Transaction.from_dict(payload)


def last_score(engine, transactions):
    scores = [engine.process_one(item) for item in transactions]
    return scores[-1]


class Phase1ScoringTests(unittest.TestCase):
    def setUp(self):
        self.engine = RiskEngine()

    def test_isolated_is_very_low(self):
        score = last_score(self.engine, [tx("i1", "A", "B")])
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)
        self.assertLess(score, 0.05)

    def test_simple_extension_above_isolated_but_low(self):
        isolated = last_score(RiskEngine(), [tx("i1", "A", "B")])
        extension = last_score(
            self.engine,
            [tx("e1", "A", "B"), tx("e2", "B", "C", minutes=1)],
        )
        self.assertGreater(extension, isolated)
        self.assertLess(extension, 0.20)

    def test_convergence_higher_than_extension(self):
        extension = last_score(
            RiskEngine(),
            [tx("e1", "A", "B"), tx("e2", "B", "C", minutes=1)],
        )
        convergence = last_score(
            self.engine,
            [
                tx("c1", "A", "B"),
                tx("c2", "A", "C", minutes=1),
                tx("c3", "B", "D", minutes=2),
                tx("c4", "C", "D", minutes=3),
            ],
        )
        self.assertGreater(convergence, extension)

    def test_return_higher_than_extension(self):
        extension = last_score(
            RiskEngine(),
            [tx("e1", "A", "B"), tx("e2", "B", "C", minutes=1)],
        )
        returning = last_score(
            self.engine,
            [
                tx("r1", "A", "B"),
                tx("r2", "B", "C", minutes=1),
                tx("r3", "C", "D", minutes=2),
                tx("r4", "D", "B", minutes=3),
            ],
        )
        self.assertGreater(returning, extension + 0.15)

    def test_basic_cycle_triggers_cycle_signal(self):
        cycle = last_score(
            self.engine,
            [
                tx("k1", "A", "B"),
                tx("k2", "B", "C", minutes=1),
                tx("k3", "C", "A", minutes=2),
            ],
        )
        self.assertGreater(self.engine.calculate_cycle_signal("C", "A"), 0.0)
        # Graph already contains C→A; rebuild to inspect the pre-insert signal.
        fresh = RiskEngine()
        fresh.process_one(tx("k1", "A", "B"))
        fresh.process_one(tx("k2", "B", "C", minutes=1))
        self.assertGreater(fresh.calculate_cycle_signal("C", "A"), 0.5)
        self.assertGreater(cycle, 0.35)

    def test_multiple_return_routes_higher_than_first_cycle(self):
        first_cycle = last_score(
            RiskEngine(),
            [
                tx("k1", "A", "B"),
                tx("k2", "B", "C", minutes=1),
                tx("k3", "C", "A", minutes=2),
            ],
        )
        multi = last_score(
            self.engine,
            [
                tx("m1", "A", "B"),
                tx("m2", "B", "C", minutes=1),
                tx("m3", "C", "A", minutes=2),
                tx("m4", "B", "D", minutes=3),
                tx("m5", "D", "A", minutes=4),
            ],
        )
        self.assertGreater(multi, first_cycle)

    def test_qualitative_ordering_of_briefing_examples(self):
        isolated = last_score(RiskEngine(), [tx("ex1", "A", "B")])
        extension = last_score(
            RiskEngine(),
            [tx("ex2a", "A", "B"), tx("ex2b", "B", "C", minutes=1)],
        )
        convergence = last_score(
            RiskEngine(),
            [
                tx("ex3a", "A", "B"),
                tx("ex3b", "A", "C", minutes=1),
                tx("ex3c", "B", "D", minutes=2),
                tx("ex3d", "C", "D", minutes=3),
            ],
        )
        returning = last_score(
            RiskEngine(),
            [
                tx("ex4a", "A", "B"),
                tx("ex4b", "B", "C", minutes=1),
                tx("ex4c", "C", "D", minutes=2),
                tx("ex4d", "D", "B", minutes=3),
            ],
        )
        multi = last_score(
            RiskEngine(),
            [
                tx("ex5a", "A", "B"),
                tx("ex5b", "B", "C", minutes=1),
                tx("ex5c", "C", "A", minutes=2),
                tx("ex5d", "B", "D", minutes=3),
                tx("ex5e", "D", "A", minutes=4),
            ],
        )
        self.assertLess(isolated, extension)
        self.assertLess(extension, convergence)
        self.assertLess(convergence, returning)
        self.assertLess(returning, multi)

    def test_24h_expiry_drops_cycle_context(self):
        self.engine.process_one(tx("t1", "A", "B", minutes=0))
        self.engine.process_one(tx("t2", "B", "C", minutes=1))
        late = tx("t3", "C", "A", minutes=24 * 60 + 2)
        score = self.engine.process_one(late)
        self.assertFalse(self.engine.graph.has_edge("A", "B"))
        self.assertFalse(self.engine.graph.has_edge("B", "C"))
        self.assertLess(score, 0.05)

    def test_duplicate_transaction_returns_same_score_without_mutation(self):
        first = tx("dup", "A", "B")
        score1 = self.engine.process_one(first)
        score2 = self.engine.process_one(first)
        self.assertEqual(score1, score2)
        self.assertEqual(self.engine.graph.edge_count("A", "B"), 1)

    def test_duplicate_tx_id_different_payload_is_an_error(self):
        self.engine.process_one(tx("dup", "A", "B"))
        with self.assertRaises(IdempotencyConflict):
            self.engine.process_one(tx("dup", "A", "C"))

    def test_duplicate_graph_edges_survive_partial_expiry(self):
        self.engine.process_one(tx("e1", "A", "B", minutes=0))
        self.engine.process_one(tx("e2", "A", "B", minutes=60))
        self.assertEqual(self.engine.graph.edge_count("A", "B"), 2)

        # 24h + 1 minute after the first edge: first expires, second remains.
        self.engine.process_one(tx("probe1", "X", "Y", minutes=24 * 60 + 1))
        self.assertTrue(self.engine.graph.has_edge("A", "B"))
        self.assertEqual(self.engine.graph.edge_count("A", "B"), 1)

        # 24h + 1 minute after the second edge: both gone.
        self.engine.process_one(tx("probe2", "P", "Q", minutes=25 * 60 + 1))
        self.assertFalse(self.engine.graph.has_edge("A", "B"))

    def test_missing_optional_fields_are_allowed(self):
        payload = {
            "txId": "opt",
            "fromUserId": "A",
            "toUserId": "B",
            "amount": 50,
            "createdAt": "2026-06-08T12:00:00Z",
        }
        parsed = Transaction.from_dict(payload)
        self.assertIsNone(parsed.ip_address)
        self.assertIsNone(parsed.device_id)
        score = self.engine.process_one(parsed)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_unknown_fields_are_ignored(self):
        payload = {
            "txId": "unk",
            "fromUserId": "A",
            "toUserId": "B",
            "amount": 10,
            "createdAt": "2026-06-08T12:00:00Z",
            "phase2OnlyField": "ignore-me",
            "nested": {"also": "ignored"},
        }
        parsed = Transaction.from_dict(payload)
        score = self.engine.process_one(parsed)
        self.assertEqual(parsed.tx_id, "unk")
        self.assertLess(score, 0.05)

    def test_reset_clears_graph_and_idempotency(self):
        self.engine.process_one(tx("a", "A", "B"))
        self.engine.process_one(tx("b", "B", "C", minutes=1))
        self.engine.reset()
        self.assertEqual(self.engine.graph.edge_count("A", "B"), 0)
        self.assertIsNone(self.engine.graph.lookup_idempotency("a"))
        isolated = self.engine.process_one(tx("a", "A", "B"))
        self.assertLess(isolated, 0.05)


class Phase1ApiTests(unittest.TestCase):
    def setUp(self):
        from routes import app
        from services.risk_engine import engine

        engine.reset()
        self.client = app.test_client()

    def test_health(self):
        response = self.client.get("/ghost-chains/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})

    def test_reset(self):
        response = self.client.post(
            "/ghost-chains/reset",
            json={"clearTransactions": True},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"clearTransactions": True})

    def test_batch_is_processed_sequentially(self):
        response = self.client.post(
            "/ghost-chains/transactions",
            json={
                "transactions": [
                    {
                        "txId": "b1",
                        "fromUserId": "A",
                        "toUserId": "B",
                        "amount": 100,
                        "createdAt": "2026-06-08T12:00:00Z",
                    },
                    {
                        "txId": "b2",
                        "fromUserId": "B",
                        "toUserId": "C",
                        "amount": 100,
                        "createdAt": "2026-06-08T12:01:00Z",
                    },
                    {
                        "txId": "b3",
                        "fromUserId": "C",
                        "toUserId": "A",
                        "amount": 100,
                        "createdAt": "2026-06-08T12:02:00Z",
                    },
                ]
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()["transactions"]
        self.assertEqual([item["txId"] for item in body], ["b1", "b2", "b3"])
        self.assertLess(body[0]["riskScore"], body[1]["riskScore"])
        self.assertGreater(body[2]["riskScore"], body[1]["riskScore"] + 0.15)

    def test_api_duplicate_and_unknown_fields(self):
        payload = {
            "transactions": [
                {
                    "txId": "api1",
                    "fromUserId": "meridian_holdings",
                    "toUserId": "apex_logistics",
                    "amount": 370.0,
                    "createdAt": "2026-06-08T12:00:00Z",
                    "futureField": True,
                }
            ]
        }
        first = self.client.post("/ghost-chains/transactions", json=payload)
        second = self.client.post("/ghost-chains/transactions", json=payload)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.get_json(), second.get_json())


if __name__ == "__main__":
    unittest.main()
