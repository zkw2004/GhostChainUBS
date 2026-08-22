from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from optimizer.scenarios import (
    Scenario,
    ScenarioResult,
    representative_score,
    run_scenario,
)
from services.risk_parameters import RiskParameters

# Fitness mix. Accuracy dominates; margin is a tie-breaker; penalties stop
# degenerate "everything is risky" solutions.
MARGIN_WEIGHT = 0.25
MARGIN_CAP = 0.25
PENALTY_WEIGHT = 1.0
COMPRESSED_RANGE_MIN = 0.15

# Ordinary structures should stay clearly below these. Not target scores.
ISOLATED_THRESHOLD = 0.12
DUPLICATE_THRESHOLD = 0.12
EXTENSION_THRESHOLD = 0.28
CHAIN_THRESHOLD = 0.35
EXPIRED_THRESHOLD = 0.12

# (higher_family, lower_family, weight)
FAMILY_ORDER: Tuple[Tuple[str, str, float], ...] = (
    ("extension", "isolated", 1.0),
    ("extension", "duplicate", 0.8),
    ("extension", "expired_cycle", 1.2),
    ("convergence", "extension", 1.3),
    ("convergence", "chain", 1.0),
    ("cycle", "extension", 1.5),
    ("cycle", "convergence", 1.1),
    ("cycle", "chain", 1.5),
    ("return", "extension", 1.5),
    ("return", "convergence", 1.0),
    ("return", "chain", 1.5),
    ("multiloop", "cycle", 1.3),
    ("multiloop", "return", 1.1),
)


@dataclass(frozen=True)
class RankingConstraint:
    higher: Scenario
    lower: Scenario
    weight: float = 1.0

    @property
    def label(self) -> str:
        return f"{self.higher.name} > {self.lower.name}"


@dataclass
class PairOutcome:
    constraint: RankingConstraint
    higher_score: float
    lower_score: float

    @property
    def margin(self) -> float:
        return self.higher_score - self.lower_score

    @property
    def satisfied(self) -> bool:
        return self.higher_score > self.lower_score


@dataclass
class Evaluation:
    params: RiskParameters
    results: List[ScenarioResult]
    outcomes: List[PairOutcome]
    ranking_accuracy: float
    average_positive_margin: float
    false_positive_penalty: float
    fitness: float

    def failed_outcomes(self) -> List[PairOutcome]:
        return [item for item in self.outcomes if not item.satisfied]

    def scores_by_family(self) -> Dict[str, float]:
        families = sorted({item.scenario.family for item in self.results})
        return {
            family: representative_score(self.results, family) or 0.0
            for family in families
        }


def build_constraints(scenarios: Sequence[Scenario]) -> List[RankingConstraint]:
    """Pair every instance of a higher family with every instance of a lower family."""
    by_family: Dict[str, List[Scenario]] = defaultdict(list)
    for scenario in scenarios:
        by_family[scenario.family].append(scenario)

    constraints: List[RankingConstraint] = []
    for higher_family, lower_family, weight in FAMILY_ORDER:
        for higher in by_family.get(higher_family, ()):
            for lower in by_family.get(lower_family, ()):
                constraints.append(
                    RankingConstraint(higher=higher, lower=lower, weight=weight)
                )
    return constraints


def ranking_accuracy(outcomes: Sequence[PairOutcome]) -> float:
    if not outcomes:
        return 0.0
    total_weight = sum(item.constraint.weight for item in outcomes)
    if total_weight <= 0:
        return 0.0
    correct = sum(item.constraint.weight for item in outcomes if item.satisfied)
    return correct / total_weight


def average_positive_margin(outcomes: Sequence[PairOutcome], cap: float = MARGIN_CAP) -> float:
    if not outcomes:
        return 0.0
    capped = [max(0.0, min(cap, item.margin)) for item in outcomes]
    return sum(capped) / len(capped)


def false_positive_penalty(results: Sequence[ScenarioResult]) -> float:
    """Penalize high scores on ordinary flow and compressed score ranges."""
    penalty = 0.0
    thresholds = {
        "isolated": ISOLATED_THRESHOLD,
        "duplicate": DUPLICATE_THRESHOLD,
        "extension": EXTENSION_THRESHOLD,
        "chain": CHAIN_THRESHOLD,
        "expired_cycle": EXPIRED_THRESHOLD,
    }
    for result in results:
        limit = thresholds.get(result.scenario.family)
        if limit is not None and result.score > limit:
            penalty += result.score - limit

    ordered = [
        representative_score(results, family)
        for family in ("isolated", "extension", "convergence", "cycle", "multiloop")
    ]
    present = [value for value in ordered if value is not None]
    if len(present) >= 2:
        spread = max(present) - min(present)
        if spread < COMPRESSED_RANGE_MIN:
            penalty += COMPRESSED_RANGE_MIN - spread
    return penalty


def evaluate_parameters(
    params: RiskParameters,
    scenarios: Sequence[Scenario],
    constraints: Optional[Sequence[RankingConstraint]] = None,
) -> Evaluation:
    params = params.normalized()
    results = [run_scenario(scenario, params) for scenario in scenarios]
    by_name = {item.scenario.name: item for item in results}
    active_constraints = list(constraints) if constraints is not None else build_constraints(scenarios)

    outcomes = []
    for constraint in active_constraints:
        higher = by_name[constraint.higher.name]
        lower = by_name[constraint.lower.name]
        outcomes.append(
            PairOutcome(
                constraint=constraint,
                higher_score=higher.score,
                lower_score=lower.score,
            )
        )

    accuracy = ranking_accuracy(outcomes)
    margin = average_positive_margin(outcomes)
    penalty = false_positive_penalty(results)
    fitness = accuracy + MARGIN_WEIGHT * margin - PENALTY_WEIGHT * penalty
    return Evaluation(
        params=params,
        results=results,
        outcomes=outcomes,
        ranking_accuracy=accuracy,
        average_positive_margin=margin,
        false_positive_penalty=penalty,
        fitness=fitness,
    )
