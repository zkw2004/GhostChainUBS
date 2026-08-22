from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from optimizer.fitness import (
    RankingConstraint,
    average_positive_margin,
    evaluate_parameters,
    false_positive_penalty,
    ranking_accuracy,
)
from optimizer.fitness import PairOutcome
from optimizer.scenarios import (
    ScenarioResult,
    expired_cycle_scenario,
    generate_scenarios,
    isolated_scenario,
    run_scenario,
)
from optimizer.search import id_key, iter_grid_weights, random_search, sample_parameters
from services.risk_engine import RiskEngine, engine as production_engine
from services.risk_parameters import (
    DEFAULT_PARAMETERS,
    RiskParameters,
    load_parameters,
    save_parameters,
)


class WeightValidityTests(unittest.TestCase):
    def test_sampled_weights_are_non_negative_and_sum_to_one(self):
        import random

        rng = random.Random(7)
        for _ in range(50):
            params = sample_parameters(rng, extra=True)
            self.assertGreaterEqual(params.cycle_weight, 0.0)
            self.assertGreaterEqual(params.convergence_weight, 0.0)
            self.assertGreaterEqual(params.growth_weight, 0.0)
            self.assertAlmostEqual(params.weight_sum, 1.0, places=9)

    def test_grid_weights_are_non_negative_and_sum_to_one(self):
        count = 0
        for params in iter_grid_weights(0.05):
            count += 1
            self.assertGreaterEqual(params.cycle_weight, 0.0)
            self.assertGreaterEqual(params.convergence_weight, 0.0)
            self.assertGreaterEqual(params.growth_weight, 0.0)
            self.assertAlmostEqual(params.weight_sum, 1.0, places=9)
        self.assertGreater(count, 10)

    def test_negative_weight_is_rejected(self):
        with self.assertRaises(ValueError):
            RiskParameters.from_weights(-0.1, 0.6, 0.5)


class RankingMetricTests(unittest.TestCase):
    def _pair(self, higher, lower, weight=1.0):
        high = isolated_scenario("train", "hi")
        low = isolated_scenario("train", "lo")
        constraint = RankingConstraint(higher=high, lower=low, weight=weight)
        return PairOutcome(constraint=constraint, higher_score=higher, lower_score=lower)

    def test_ranking_accuracy(self):
        outcomes = [self._pair(0.4, 0.1), self._pair(0.2, 0.3), self._pair(0.9, 0.1, weight=2)]
        # correct weights: 1 + 0 + 2 = 3 / 4
        self.assertAlmostEqual(ranking_accuracy(outcomes), 0.75)

    def test_margin_calculation(self):
        outcomes = [self._pair(0.50, 0.20), self._pair(0.10, 0.40)]
        # first margin capped at 0.25, second negative -> 0; mean = 0.125
        self.assertAlmostEqual(average_positive_margin(outcomes, cap=0.25), 0.125)

    def test_degenerate_high_scores_receive_penalty(self):
        isolated = isolated_scenario("train", "pen")
        engine = RiskEngine()
        high = ScenarioResult(scenario=isolated, score=0.85, engine=engine)
        self.assertGreater(false_positive_penalty([high]), 0.5)


class ScenarioIsolationTests(unittest.TestCase):
    def test_scenarios_do_not_share_graph_state(self):
        production_engine.reset()
        production_engine.process_one(
            isolated_scenario("train", "warm").transactions[0]
        )
        # A leftover global graph must not leak into optimizer runs.
        isolated = isolated_scenario("train", "fresh")
        result = run_scenario(isolated, DEFAULT_PARAMETERS)
        self.assertLess(result.score, 0.05)
        self.assertIsNot(result.engine, production_engine)

        again = run_scenario(isolated, DEFAULT_PARAMETERS)
        self.assertEqual(result.score, again.score)

    def test_expired_edges_do_not_form_a_cycle(self):
        scenario = expired_cycle_scenario("train", "exp")
        result = run_scenario(scenario, DEFAULT_PARAMETERS)
        graph = result.engine.graph
        self.assertFalse(graph.has_edge(scenario.transactions[0].from_user_id, scenario.transactions[0].to_user_id))
        self.assertFalse(graph.has_edge(scenario.transactions[1].from_user_id, scenario.transactions[1].to_user_id))
        self.assertLess(result.score, 0.05)

    def test_optimizer_uses_real_risk_engine(self):
        scenario = isolated_scenario("train", "real")
        result = run_scenario(scenario, DEFAULT_PARAMETERS)
        self.assertIs(type(result.engine), RiskEngine)
        self.assertEqual(
            result.engine.score_transaction.__func__,
            RiskEngine.score_transaction,
        )


class ConfigRoundTripTests(unittest.TestCase):
    def test_save_and_load_preserve_numeric_values(self):
        params = RiskParameters.from_weights(0.62, 0.23, 0.15)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "optimized_phase1.json"
            save_parameters(params, path, extra={"fitness": 0.94})
            loaded = load_parameters(path)
            payload = json.loads(path.read_text())
        self.assertAlmostEqual(loaded.cycle_weight, params.cycle_weight)
        self.assertAlmostEqual(loaded.convergence_weight, params.convergence_weight)
        self.assertAlmostEqual(loaded.growth_weight, params.growth_weight)
        self.assertAlmostEqual(payload["fitness"], 0.94)


class RandomSearchDeterminismTests(unittest.TestCase):
    def test_identical_seed_produces_identical_results(self):
        import random

        rng_a = random.Random(42)
        rng_b = random.Random(42)
        rng_c = random.Random(99)
        first_samples = [id_key(sample_parameters(rng_a, extra=True)) for _ in range(12)]
        second_samples = [id_key(sample_parameters(rng_b, extra=True)) for _ in range(12)]
        other_samples = [id_key(sample_parameters(rng_c, extra=True)) for _ in range(12)]
        self.assertEqual(first_samples, second_samples)
        self.assertNotEqual(first_samples, other_samples)

        train = generate_scenarios("train", variants=1)
        val = generate_scenarios("val", variants=1)
        from optimizer.fitness import build_constraints

        train_c = build_constraints(train)
        val_c = build_constraints(val)
        first = random_search(
            train, val, train_c, val_c, iterations=8, seed=42, extra=True, top_k=3
        )
        second = random_search(
            train, val, train_c, val_c, iterations=8, seed=42, extra=True, top_k=3
        )
        self.assertEqual(
            [id_key(item.params) for item in first],
            [id_key(item.params) for item in second],
        )


class DefaultEngineRegressionTests(unittest.TestCase):
    def test_production_defaults_still_rank_core_examples(self):
        evaluation = evaluate_parameters(
            DEFAULT_PARAMETERS,
            generate_scenarios("train", variants=2),
        )
        scores = evaluation.scores_by_family()
        self.assertLess(scores["isolated"], scores["extension"])
        self.assertLess(scores["extension"], scores["convergence"])
        self.assertLess(scores["convergence"], scores["return"])
        self.assertLess(scores["cycle"], scores["multiloop"])
        self.assertGreater(evaluation.ranking_accuracy, 0.85)


if __name__ == "__main__":
    unittest.main()
