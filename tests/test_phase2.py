from __future__ import annotations

import unittest

from services.risk_engine import RiskEngine

try:
    from tests.test_phase1 import last_score, tx
except ImportError:
    from test_phase1 import last_score, tx


IOS = "dev_ios_7f3a91"
ANDROID = "dev_android_c2e4b8"
IP = "10.0.0.1"


class Phase2IdentityTests(unittest.TestCase):
    def setUp(self):
        self.engine = RiskEngine()

    def test_phase1_scores_unchanged_without_identity(self):
        first = tx("a", "A", "B")
        self.engine.process_one(first)
        self.assertEqual(self.engine.calculate_identity_signal(tx("b", "B", "C")), 0.0)

    def test_consistent_identity_is_not_an_anomaly(self):
        plain = last_score(
            RiskEngine(),
            [
                tx("t1", "M", "A"),
                tx("t2", "A", "C", minutes=1),
                tx("t3", "C", "H", minutes=2),
            ],
        )
        consistent = last_score(
            self.engine,
            [
                tx("t1", "M", "A", deviceId=IOS),
                tx("t2", "A", "C", minutes=1, deviceId=IOS),
                tx("t3", "C", "H", minutes=2, deviceId=IOS),
            ],
        )
        self.assertAlmostEqual(consistent, plain)

    def test_branch_divergence_scores_above_consistent(self):
        consistent = last_score(
            RiskEngine(),
            [
                tx("t1", "M", "A", deviceId=IOS),
                tx("t2", "A", "C", minutes=1, deviceId=IOS),
                tx("t3", "A", "S", minutes=2, deviceId=IOS),
                tx("t4", "C", "O", minutes=3, deviceId=IOS),
            ],
        )
        diverged = last_score(
            self.engine,
            [
                tx("t1", "M", "A", deviceId=IOS),
                tx("t2", "A", "C", minutes=1, deviceId=IOS),
                tx("t3", "A", "S", minutes=2, deviceId=IOS),
                tx("t4", "C", "O", minutes=3, deviceId=ANDROID),
            ],
        )
        self.assertGreater(diverged, consistent)

    def test_mid_flow_shift_scores_above_consistent(self):
        consistent = last_score(
            RiskEngine(),
            [
                tx("t1", "M", "A", deviceId=IOS),
                tx("t2", "A", "C", minutes=1, deviceId=IOS),
                tx("t3", "C", "H", minutes=2, deviceId=IOS),
                tx("t4", "H", "N", minutes=3, deviceId=IOS),
            ],
        )
        shifted = last_score(
            self.engine,
            [
                tx("t1", "M", "A", deviceId=IOS),
                tx("t2", "A", "C", minutes=1, deviceId=IOS),
                tx("t3", "C", "H", minutes=2, deviceId=ANDROID),
                tx("t4", "H", "N", minutes=3, deviceId=ANDROID),
            ],
        )
        self.assertGreater(shifted, consistent)

    def test_shared_ip_across_disconnected_components(self):
        isolated = last_score(RiskEngine(), [tx("t1", "M", "A")])
        shared_last = last_score(
            self.engine,
            [
                tx("t1", "M", "A", ipAddress=IP),
                tx("t2", "C", "H", minutes=1, ipAddress=IP),
                tx("t3", "O", "S", minutes=2, ipAddress=IP),
            ],
        )
        self.assertGreater(shared_last, isolated)
        cycle = last_score(
            RiskEngine(),
            [
                tx("c1", "A", "B"),
                tx("c2", "B", "C", minutes=1),
                tx("c3", "C", "A", minutes=2),
            ],
        )
        self.assertLess(shared_last, cycle)

    def test_missing_identity_on_isolated_is_not_suspicious(self):
        missing = last_score(self.engine, [tx("t1", "A", "B")])
        self.assertLess(missing, 0.05)

    def test_identity_drop_on_connected_flow(self):
        consistent = last_score(
            RiskEngine(),
            [
                tx("t1", "M", "A", deviceId=IOS),
                tx("t2", "A", "C", minutes=1, deviceId=IOS),
                tx("t3", "C", "H", minutes=2, deviceId=IOS),
            ],
        )
        dropped = last_score(
            self.engine,
            [
                tx("t1", "M", "A", deviceId=IOS),
                tx("t2", "A", "C", minutes=1, deviceId=IOS),
                tx("t3", "C", "H", minutes=2),
            ],
        )
        self.assertGreater(dropped, consistent)

    def test_ip_and_device_are_independent(self):
        device_only = last_score(
            RiskEngine(),
            [
                tx("t1", "M", "A", deviceId=IOS),
                tx("t2", "A", "C", minutes=1, deviceId=ANDROID),
            ],
        )
        both = last_score(
            self.engine,
            [
                tx("t1", "M", "A", deviceId=IOS, ipAddress=IP),
                tx("t2", "A", "C", minutes=1, deviceId=ANDROID, ipAddress="10.0.0.9"),
            ],
        )
        self.assertGreater(both, device_only)

    def test_identity_expires_with_window(self):
        self.engine.process_one(tx("t1", "M", "A", minutes=0, ipAddress=IP))
        late = tx("t2", "C", "H", minutes=24 * 60 + 2, ipAddress=IP)
        score = self.engine.process_one(late)
        self.assertLess(score, 0.05)
        holders = {
            self.engine.graph.label_of(idx)
            for idx in self.engine.graph.ip_to_nodes.get(IP, set())
        }
        self.assertNotIn("M", holders)
        self.assertNotIn("A", holders)
        self.assertEqual(holders, {"C"})

    def test_reset_clears_identity_indexes(self):
        self.engine.process_one(tx("t1", "M", "A", deviceId=IOS, ipAddress=IP))
        self.engine.reset()
        self.assertEqual(self.engine.graph.device_to_nodes, {})
        self.assertEqual(self.engine.graph.ip_to_nodes, {})


class Phase2ApiTests(unittest.TestCase):
    def setUp(self):
        from routes import app
        from services.risk_engine import engine

        engine.reset()
        self.client = app.test_client()

    def test_device_and_ip_are_accepted(self):
        response = self.client.post(
            "/ghost-chains/transactions",
            json={
                "transactions": [
                    {
                        "txId": "p2",
                        "fromUserId": "meridian_holdings",
                        "toUserId": "apex_logistics",
                        "amount": 370.0,
                        "createdAt": "2026-06-08T12:00:00Z",
                        "ipAddress": "10.0.0.1",
                        "deviceId": "dev_ios_7f3a91",
                    }
                ]
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()["transactions"][0]
        self.assertEqual(body["txId"], "p2")
        self.assertGreaterEqual(body["riskScore"], 0.0)
        self.assertLessEqual(body["riskScore"], 1.0)


if __name__ == "__main__":
    unittest.main()
