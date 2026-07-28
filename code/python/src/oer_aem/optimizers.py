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
    phase: str
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
        self.phase = "objective"
        self._evaluations: list[EvaluationRecord] = []

    @property
    def evaluations(self) -> tuple[EvaluationRecord, ...]:
        return tuple(self._evaluations)

    def set_phase(self, phase: str) -> None:
        if not isinstance(phase, str) or not phase.strip():
            raise ValueError("evaluation phase must be a non-empty string")
        self.phase = phase.strip()

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
                    phase=self.phase,
                    unit=coordinates,
                    loss=None,
                    error=str(exc),
                )
            )
            raise

        self._evaluations.append(
            EvaluationRecord(
                index=self.calls,
                phase=self.phase,
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
    objective.set_phase("tpe")

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


def _run_sobol_pattern(
    objective: BudgetedObjective,
    *,
    dimension: int,
    budget: int,
    seed: int,
) -> OptimizerResult:
    from scipy.stats import qmc

    if budget != 100:
        raise ValueError("sobol_pattern requires frozen budget=100")

    sampler = qmc.Sobol(d=dimension, scramble=True, seed=int(seed))
    global_points = sampler.random_base2(m=6)
    cache: dict[tuple[float, ...], float] = {}
    ranked_global: list[tuple[float, int, tuple[float, ...]]] = []
    objective.set_phase("sobol_global")
    for index, point in enumerate(global_points):
        key = tuple(map(float, point))
        loss = objective(point)
        cache[key] = loss
        ranked_global.append((loss, index, key))
    ranked_global.sort()

    current = np.asarray(ranked_global[0][2], dtype=float)
    current_loss = float(ranked_global[0][0])
    restart_index = 1
    step = 1.0 / 8.0

    while objective.calls < budget:
        objective.set_phase("pattern_local")
        candidates: list[tuple[float, np.ndarray]] = []
        for coordinate in range(dimension):
            for direction in (-1.0, 1.0):
                candidate = current.copy()
                candidate[coordinate] = np.clip(
                    candidate[coordinate] + direction * step,
                    0.0,
                    1.0,
                )
                key = tuple(map(float, candidate))
                if key in cache:
                    continue
                loss = objective(candidate)
                cache[key] = loss
                candidates.append((loss, candidate))
                if objective.calls >= budget:
                    break
            if objective.calls >= budget:
                break

        if candidates:
            candidate_loss, candidate = min(
                candidates,
                key=lambda item: item[0],
            )
            if candidate_loss < current_loss:
                current = candidate
                current_loss = float(candidate_loss)
            else:
                step /= 2.0
        else:
            step /= 2.0

        if objective.calls >= budget:
            break
        if step < 1.0 / 1024.0:
            if restart_index < len(ranked_global):
                current = np.asarray(
                    ranked_global[restart_index][2],
                    dtype=float,
                )
                current_loss = float(ranked_global[restart_index][0])
                restart_index += 1
                step = 1.0 / 8.0
            else:
                objective.set_phase("sobol_fallback")
                while objective.calls < budget:
                    point = sampler.random(1)[0]
                    key = tuple(map(float, point))
                    if key in cache:
                        continue
                    cache[key] = objective(point)
                    break

    if objective.calls != budget:
        raise RuntimeError(
            "sobol_pattern call-count mismatch: "
            f"{objective.calls} != {budget}"
        )
    return _result_from_records("sobol_pattern", objective)


def _reflect_unit_cube(values: np.ndarray) -> np.ndarray:
    """Reflect arbitrary coordinates into the closed unit cube."""

    reflected = np.abs(np.asarray(values, dtype=float)) % 2.0
    return np.where(reflected > 1.0, 2.0 - reflected, reflected)


def _run_de_fixed(
    objective: BudgetedObjective,
    *,
    dimension: int,
    budget: int,
    seed: int,
) -> OptimizerResult:
    if dimension != 2:
        raise ValueError("de_fixed requires dimension=2")
    if budget != 100:
        raise ValueError("de_fixed requires frozen budget=100")

    population_size = 20
    rng = np.random.default_rng(seed)
    population = rng.random((population_size, dimension))
    losses = np.empty(population_size, dtype=float)

    objective.set_phase("de_initial")
    for index, point in enumerate(population):
        losses[index] = objective(point)

    for generation in range(1, 5):
        objective.set_phase(f"de_generation_{generation}")
        next_population = population.copy()
        next_losses = losses.copy()
        for target_index in range(population_size):
            eligible = np.delete(np.arange(population_size), target_index)
            a_index, b_index, c_index = rng.choice(
                eligible,
                size=3,
                replace=False,
            )
            mutant = population[a_index] + 0.8 * (
                population[b_index] - population[c_index]
            )
            mutant = _reflect_unit_cube(mutant)
            crossover = rng.random(dimension) < 0.7
            crossover[rng.integers(dimension)] = True
            trial = np.where(crossover, mutant, population[target_index])
            trial_loss = objective(trial)
            if trial_loss <= losses[target_index]:
                next_population[target_index] = trial
                next_losses[target_index] = trial_loss
        population = next_population
        losses = next_losses

    if objective.calls != budget:
        raise RuntimeError(
            f"de_fixed call-count mismatch: {objective.calls} != {budget}"
        )
    return _result_from_records("de_fixed", objective)


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
    if name == "sobol_pattern":
        return _run_sobol_pattern(
            wrapped,
            dimension=wrapped.dimension,
            budget=wrapped.budget,
            seed=int(seed),
        )
    if name == "de_fixed":
        return _run_de_fixed(
            wrapped,
            dimension=wrapped.dimension,
            budget=wrapped.budget,
            seed=int(seed),
        )
    raise ValueError(f"unknown optimizer: {name}")
