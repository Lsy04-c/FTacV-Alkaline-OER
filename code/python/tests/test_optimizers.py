"""Tests for truth-agnostic, fixed-budget optimizer adapters."""

from __future__ import annotations

import numpy as np
import pytest

from oer_aem.optimizers import BudgetedObjective, run_optimizer


def sphere(unit) -> float:
    values = np.asarray(unit, dtype=float)
    return float(np.sum((values - 0.25) ** 2))


def test_tpe_uses_exact_budget_and_is_deterministic() -> None:
    first = run_optimizer(
        "tpe",
        sphere,
        dimension=2,
        budget=100,
        seed=7,
    )
    second = run_optimizer(
        "tpe",
        sphere,
        dimension=2,
        budget=100,
        seed=7,
    )

    assert first.optimization_calls == 100
    assert len(first.evaluations) == 100
    assert first.evaluations == second.evaluations
    assert np.allclose(first.best_unit, second.best_unit)


def test_budgeted_objective_rejects_call_101() -> None:
    wrapped = BudgetedObjective(sphere, dimension=2, budget=100)

    for _ in range(100):
        wrapped([0.5, 0.5])

    with pytest.raises(RuntimeError, match="objective budget exhausted"):
        wrapped([0.5, 0.5])


def test_nonfinite_call_is_counted_then_fails() -> None:
    wrapped = BudgetedObjective(
        lambda unit: float("nan"),
        dimension=2,
        budget=100,
    )

    with pytest.raises(FloatingPointError, match="non-finite objective"):
        wrapped([0.5, 0.5])

    assert wrapped.calls == 1
    assert wrapped.evaluations[0].error == "non-finite objective"


@pytest.mark.parametrize(
    "unit",
    (
        [0.5],
        [0.5, 0.5, 0.5],
        [-0.1, 0.5],
        [0.5, 1.1],
        [float("nan"), 0.5],
    ),
)
def test_budgeted_objective_rejects_invalid_unit_coordinates(unit) -> None:
    wrapped = BudgetedObjective(sphere, dimension=2, budget=100)

    with pytest.raises(ValueError):
        wrapped(unit)

    assert wrapped.calls == 0
    assert wrapped.evaluations == ()
