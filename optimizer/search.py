from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

from optimizer.fitness import Evaluation, RankingConstraint, evaluate_parameters
from optimizer.scenarios import Scenario
from services.risk_parameters import DEFAULT_PARAMETERS, RiskParameters

CYCLE_WEIGHT_RANGE = (0.30, 0.80)
CONVERGENCE_WEIGHT_RANGE = (0.10, 0.50)
GRID_STEP = 0.05
DECAY_RANGE = (0.05, 0.45)
MIX_RANGE = (0.40, 0.90)
SATURATION_RANGE = (0.35, 0.70)


@dataclass
class Candidate:
    params: RiskParameters
    train: Evaluation
    validation: Optional[Evaluation] = None

    @property
    def fitness(self) -> float:
        return self.train.fitness


def _frange(start: float, stop: float, step: float) -> List[float]:
    values = []
    current = start
    while current <= stop + 1e-9:
        values.append(round(current, 10))
        current += step
    return values


def iter_grid_weights(step: float = GRID_STEP) -> Iterable[RiskParameters]:
    """Two free weights; growth is 1 - cycle - convergence. Skip invalid rows."""
    yield DEFAULT_PARAMETERS
    seen = {id_key(DEFAULT_PARAMETERS)}
    for cycle in _frange(CYCLE_WEIGHT_RANGE[0], CYCLE_WEIGHT_RANGE[1], step):
        for convergence in _frange(
            CONVERGENCE_WEIGHT_RANGE[0], CONVERGENCE_WEIGHT_RANGE[1], step
        ):
            growth = round(1.0 - cycle - convergence, 10)
            if growth < 0:
                continue
            params = RiskParameters.from_weights(cycle, convergence, growth)
            key = id_key(params)
            if key in seen:
                continue
            seen.add(key)
            yield params


def sample_parameters(rng: random.Random, extra: bool = True) -> RiskParameters:
    raw = [rng.random() + 0.05 for _ in range(3)]
    total = sum(raw)
    cycle, convergence, growth = (value / total for value in raw)
    kwargs = {}
    if extra:
        kwargs["cycle_distance_decay"] = rng.uniform(*DECAY_RANGE)
        kwargs["cycle_length_mix"] = rng.uniform(*MIX_RANGE)
        kwargs["saturation_base"] = rng.uniform(*SATURATION_RANGE)
    params = RiskParameters.from_weights(cycle, convergence, growth, **kwargs)
    return params


def id_key(params: RiskParameters) -> tuple:
    return tuple(round(value, 6) for value in params.to_dict().values())


def _evaluate_many(
    candidates: Iterable[RiskParameters],
    train_scenarios: Sequence[Scenario],
    train_constraints: Sequence[RankingConstraint],
) -> List[Candidate]:
    ranked: List[Candidate] = []
    for params in candidates:
        train = evaluate_parameters(params, train_scenarios, train_constraints)
        ranked.append(Candidate(params=train.params, train=train))
    ranked.sort(key=lambda item: item.fitness, reverse=True)
    return ranked


def attach_validation(
    candidates: Sequence[Candidate],
    val_scenarios: Sequence[Scenario],
    val_constraints: Sequence[RankingConstraint],
    limit: int,
) -> List[Candidate]:
    """Keep the best training candidates, then rank the shortlist by validation."""
    shortlist = list(candidates[: max(limit * 3, limit)])
    attached = []
    for candidate in shortlist:
        validation = evaluate_parameters(
            candidate.params, val_scenarios, val_constraints
        )
        attached.append(
            Candidate(params=candidate.params, train=candidate.train, validation=validation)
        )
    attached.sort(
        key=lambda item: (
            item.validation.fitness if item.validation is not None else float("-inf"),
            item.train.fitness,
        ),
        reverse=True,
    )
    return attached[:limit]


def grid_search(
    train_scenarios: Sequence[Scenario],
    val_scenarios: Sequence[Scenario],
    train_constraints: Sequence[RankingConstraint],
    val_constraints: Sequence[RankingConstraint],
    step: float = GRID_STEP,
    top_k: int = 10,
) -> List[Candidate]:
    ranked = _evaluate_many(
        iter_grid_weights(step), train_scenarios, train_constraints
    )
    return attach_validation(ranked, val_scenarios, val_constraints, top_k)


def random_search(
    train_scenarios: Sequence[Scenario],
    val_scenarios: Sequence[Scenario],
    train_constraints: Sequence[RankingConstraint],
    val_constraints: Sequence[RankingConstraint],
    iterations: int = 5000,
    seed: int = 42,
    extra: bool = True,
    top_k: int = 10,
) -> List[Candidate]:
    rng = random.Random(seed)
    samples = [DEFAULT_PARAMETERS]
    for _ in range(iterations):
        samples.append(sample_parameters(rng, extra=extra))
    ranked = _evaluate_many(samples, train_scenarios, train_constraints)
    return attach_validation(ranked, val_scenarios, val_constraints, top_k)
