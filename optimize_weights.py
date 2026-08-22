from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import List, Optional, Sequence

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from optimizer.fitness import Evaluation, build_constraints
from optimizer.scenarios import generate_scenarios
from optimizer.search import Candidate, grid_search, random_search
from services.risk_parameters import save_parameters

DEFAULT_SAVE_PATH = ROOT / "config" / "optimized_phase1.json"
REPRESENTATIVE_FAMILIES = (
    "isolated",
    "extension",
    "chain",
    "convergence",
    "return",
    "cycle",
    "multiloop",
    "duplicate",
    "expired_cycle",
)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Offline ranking optimizer for Ghost Chains Phase 1 weights."
    )
    parser.add_argument("--method", choices=("grid", "random"), default="grid")
    parser.add_argument("--iterations", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--step", type=float, default=0.05)
    parser.add_argument("--variants", type=int, default=4)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument(
        "--weights-only",
        action="store_true",
        help="Random search: only vary the three mixture weights.",
    )
    parser.add_argument(
        "--save-best",
        action="store_true",
        help="Write the winning parameters to config/optimized_phase1.json.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_SAVE_PATH)
    parser.add_argument("--csv", type=Path, default=None)
    return parser.parse_args(argv)


def format_table(candidates: Sequence[Candidate]) -> str:
    header = (
        f"{'Rank':<6}{'TrainFit':<12}{'ValFit':<12}{'TrainAcc':<12}"
        f"{'ValAcc':<12}{'Cycle':<10}{'Conv':<10}{'Growth':<10}"
    )
    lines = [header, "-" * len(header)]
    for index, candidate in enumerate(candidates, start=1):
        val_fit = candidate.validation.fitness if candidate.validation else float("nan")
        val_acc = (
            candidate.validation.ranking_accuracy if candidate.validation else float("nan")
        )
        params = candidate.params
        lines.append(
            f"{index:<6}{candidate.train.fitness:<12.4f}{val_fit:<12.4f}"
            f"{candidate.train.ranking_accuracy:<12.4f}{val_acc:<12.4f}"
            f"{params.cycle_weight:<10.4f}{params.convergence_weight:<10.4f}"
            f"{params.growth_weight:<10.4f}"
        )
    return "\n".join(lines)


def print_evaluation(title: str, evaluation: Evaluation, failed_limit: int = 12) -> None:
    scores = evaluation.scores_by_family()
    print(title)
    print(f"  ranking accuracy         {evaluation.ranking_accuracy:.4f}")
    print(f"  average ranking margin   {evaluation.average_positive_margin:.4f}")
    print(f"  false-positive penalty   {evaluation.false_positive_penalty:.4f}")
    print(f"  overall fitness          {evaluation.fitness:.4f}")
    print("  representative scores:")
    for family in REPRESENTATIVE_FAMILIES:
        if family in scores:
            print(f"    {family:<16} {scores[family]:.6f}")

    failed = evaluation.failed_outcomes()
    if not failed:
        print("  no ranking constraints failed")
        return

    print(f"  FAILED ({len(failed)}):")
    for outcome in failed[:failed_limit]:
        print(
            f"    {outcome.constraint.higher.name} = {outcome.higher_score:.4f}"
        )
        print(
            f"    {outcome.constraint.lower.name} = {outcome.lower_score:.4f}"
        )
        print(
            f"    expected {outcome.constraint.higher.family} > {outcome.constraint.lower.family}"
        )
        print()
    remaining = len(failed) - failed_limit
    if remaining > 0:
        print(f"    ... {remaining} more")


def write_csv(path: Path, evaluation: Evaluation) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["scenario_name", "scenario_type", "split", "risk_score"])
        for result in evaluation.results:
            writer.writerow(
                [
                    result.scenario.name,
                    result.scenario.family,
                    result.scenario.split,
                    f"{result.score:.6f}",
                ]
            )


def run(argv: Optional[Sequence[str]] = None) -> List[Candidate]:
    args = parse_args(argv)
    train_scenarios = generate_scenarios("train", variants=args.variants)
    val_scenarios = generate_scenarios("val", variants=args.variants)
    train_constraints = build_constraints(train_scenarios)
    val_constraints = build_constraints(val_scenarios)

    if args.method == "grid":
        candidates = grid_search(
            train_scenarios,
            val_scenarios,
            train_constraints,
            val_constraints,
            step=args.step,
            top_k=args.top,
        )
    else:
        candidates = random_search(
            train_scenarios,
            val_scenarios,
            train_constraints,
            val_constraints,
            iterations=args.iterations,
            seed=args.seed,
            extra=not args.weights_only,
            top_k=args.top,
        )

    print(format_table(candidates))
    print()
    best = candidates[0]
    print("Best parameters")
    for key, value in best.params.to_dict().items():
        print(f"  {key}: {value:.6f}")
    print()
    print_evaluation("Training", best.train)
    print()
    if best.validation is not None:
        print_evaluation("Validation", best.validation)

    if args.csv:
        write_csv(args.csv, best.train)
        print(f"\nWrote scenario scores to {args.csv}")

    if args.save_best:
        extra = {
            "fitness": best.train.fitness,
            "training_ranking_accuracy": best.train.ranking_accuracy,
            "validation_ranking_accuracy": (
                best.validation.ranking_accuracy if best.validation else None
            ),
        }
        save_parameters(best.params, args.output, extra=extra)
        print(f"\nWrote {args.output}")

    return candidates


if __name__ == "__main__":
    run()
