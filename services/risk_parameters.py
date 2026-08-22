from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Union


@dataclass(frozen=True)
class RiskParameters:
    """Tunable Phase 1 scoring knobs. Weights should be non-negative and sum to 1."""

    cycle_weight: float = 0.55
    convergence_weight: float = 0.30
    growth_weight: float = 0.15
    cycle_distance_decay: float = 0.20
    cycle_length_mix: float = 0.65
    saturation_base: float = 0.50

    def validate(self) -> None:
        for name in (
            "cycle_weight",
            "convergence_weight",
            "growth_weight",
            "cycle_distance_decay",
            "cycle_length_mix",
            "saturation_base",
        ):
            value = getattr(self, name)
            if value < 0:
                raise ValueError(f"{name} must be non-negative, got {value}")
        if not 0.0 < self.saturation_base < 1.0:
            raise ValueError("saturation_base must be in (0, 1)")
        if self.cycle_length_mix > 1.0:
            raise ValueError("cycle_length_mix must be <= 1")

    @property
    def weight_sum(self) -> float:
        return self.cycle_weight + self.convergence_weight + self.growth_weight

    def normalized(self) -> "RiskParameters":
        total = self.weight_sum
        if total <= 0:
            raise ValueError("weights must sum to a positive number")
        return RiskParameters(
            cycle_weight=self.cycle_weight / total,
            convergence_weight=self.convergence_weight / total,
            growth_weight=self.growth_weight / total,
            cycle_distance_decay=self.cycle_distance_decay,
            cycle_length_mix=self.cycle_length_mix,
            saturation_base=self.saturation_base,
        )

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RiskParameters":
        known = {field: data[field] for field in cls.__dataclass_fields__ if field in data}
        params = cls(**known)
        params.validate()
        return params

    @classmethod
    def from_weights(
        cls,
        cycle_weight: float,
        convergence_weight: float,
        growth_weight: float,
        **kwargs: float,
    ) -> "RiskParameters":
        params = cls(
            cycle_weight=cycle_weight,
            convergence_weight=convergence_weight,
            growth_weight=growth_weight,
            **kwargs,
        )
        params.validate()
        return params.normalized()


PathLike = Union[str, Path]


def save_parameters(
    params: RiskParameters,
    path: PathLike,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    payload = params.to_dict()
    if extra:
        payload.update(extra)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def load_parameters(path: PathLike) -> RiskParameters:
    payload = json.loads(Path(path).read_text())
    return RiskParameters.from_dict(payload)


DEFAULT_PARAMETERS = RiskParameters()
DEFAULT_PARAMETERS.validate()
