"""Truth-agnostic optimizers with an auditable objective-call budget."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np


UnitObjective = Callable[[np.ndarray], float]


@dataclass(frozen=True)
class EvaluationRecord:
    """One attempted optimization-objective call."""

    index: int
    unit: tuple[float, ...]
    loss: float | None
    error: str | None


@dataclass(frozen=True)
class OptimizerResult:
    """Common result returned by every fixed-budget optimizer."""

    optimizer: str
    best_unit: tuple[float, ...]
    best_loss: float
    optimization_calls: int
    evaluations: tuple[EvaluationRecord, ...]
    termination_reason: str


class BudgetedObjective:
    """Validate unit coordinates and enforce an exact upper call budget."""

    def __init__(
        self,
        objective: UnitObjective,
        *,
        dimension: int,
        budget: int,
    ) -> None:
        if isinstance(dimension, bool) or int(dimension) != dimension or dimension < 1:
            raise ValueError("dimension must be a positive integer")
        if isinstance(budget, bool) or int(budget) != budget or budget < 1:
            raise ValueError("budget must be a positive integer")
        self.objective = objective
        self.dimension = int(dimension)
        self.budget = int(budget)
        self.calls = 0
        self._evaluations: list[EvaluationRecord] = []

    @property
    def evaluations(self) -> tuple[EvaluationRecord, ...]:
        return tuple(self._evaluations)

    def __call__(self, unit: Sequence[float]) -> float:
        if self.calls >= self.budget:
            raise RuntimeError("objective budget exhausted")
        point = np.asarray(unit, dtype=float).reshape(-1)
        if point.size != self.dimension:
            raise ValueError("unit coordinate dimension mismatch")
        if (
            not np.all(np.isfinite(point))
            or np.any(point < 0.0)
            or np.any(point > 1.0)
        ):
            raise ValueError("unit coordinates must be finite and in [0,1]")

        self.calls += 1
        coordinates = tuple(map(float, point))
        try:
            loss = float(self.objective(point.copy()))
            if not np.isfinite(loss):
                raise FloatingPointError("non-finite objective")
        except Exception as exc:
            self._evaluations.append(
                EvaluationRecord(
                    index=self.calls,
                    unit=coordinates,
                    loss=None,
                    error=str(exc),
                )
            )
            raise

        self._evaluations.append(
            EvaluationRecord(
                index=self.calls,
                unit=coordinates,
                loss=loss,
                error=None,
            )
        )
        return loss


def _result_from_records(
    optimizer: str,
    objective: BudgetedObjective,
) -> OptimizerResult:
    successful = [row for row in objective.evaluations if row.loss is not None]
    if not successful:
        raise RuntimeError(f"{optimizer} produced no finite objective values")
    best = min(successful, key=lambda row: (float(row.loss), row.index))
    return OptimizerResult(
        optimizer=optimizer,
        best_unit=best.unit,
        best_loss=float(best.loss),
        optimization_calls=objective.calls,
        evaluations=objective.evaluations,
        termination_reason="budget_exhausted",
    )


def _run_tpe(
    objective: BudgetedObjective,
    *,
    dimension: int,
    budget: int,
    seed: int,
) -> OptimizerResult:
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    sampler = optuna.samplers.TPESampler(
        seed=int(seed),
        n_startup_trials=min(10, budget),
    )
    study = optuna.create_study(direction="minimize", sampler=sampler)

    def optuna_objective(trial) -> float:
        unit = [
            trial.suggest_float(f"z_{index}", 0.0, 1.0)
            for index in range(dimension)
        ]
        return objective(unit)

    study.optimize(optuna_objective, n_trials=budget)
    if objective.calls != budget:
        raise RuntimeError(
            f"tpe call-count mismatch: {objective.calls} != {budget}"
        )
    return _result_from_records("tpe", objective)


def run_optimizer(
    name: str,
    objective: UnitObjective,
    *,
    dimension: int,
    budget: int,
    seed: int,
) -> OptimizerResult:
    """Run one named optimizer without exposing target or truth metadata."""

    wrapped = BudgetedObjective(
        objective,
        dimension=dimension,
        budget=budget,
    )
    if name == "tpe":
        return _run_tpe(
            wrapped,
            dimension=wrapped.dimension,
            budget=wrapped.budget,
            seed=int(seed),
        )
    raise ValueError(f"unknown optimizer: {name}")
