"""Tests for deterministic one-parameter objective profiles."""

import importlib
import importlib.util

import pytest


def _profiling():
    assert importlib.util.find_spec("oer_aem.profiling") is not None
    return importlib.import_module("oer_aem.profiling")


def test_profile_grid_includes_bounds_and_off_grid_truth_once():
    profiling = _profiling()

    grid = profiling.profile_grid(0.37, grid_points=5)

    assert grid.tolist() == pytest.approx([0.0, 0.25, 0.37, 0.5, 0.75, 1.0])
    assert sum(value == pytest.approx(0.37) for value in grid) == 1


def test_profile_grid_rejects_invalid_inputs():
    profiling = _profiling()

    with pytest.raises(ValueError, match="truth coordinate"):
        profiling.profile_grid(-0.1)
    with pytest.raises(ValueError, match="grid_points"):
        profiling.profile_grid(0.5, grid_points=2)


def test_summarize_profile_reports_discrete_geometry_and_failures():
    profiling = _profiling()
    rows = [
        {
            "normalized_coordinate": coordinate,
            "total_loss": 16.0 * (coordinate - 0.5) ** 2,
            "ode_success": True,
            "tafel_failed": coordinate == 0.75,
        }
        for coordinate in (0.0, 0.25, 0.5, 0.75, 1.0)
    ]

    summary = profiling.summarize_profile(rows, truth_coordinate=0.5)

    assert summary["truth_is_global_minimum"] is True
    assert summary["minimum_coordinate"] == pytest.approx(0.5)
    assert summary["minimum_truth_distance"] == pytest.approx(0.0)
    assert summary["local_curvature"] == pytest.approx(32.0)
    assert summary["delta_1_width"] == pytest.approx(0.5)
    assert summary["delta_10_width"] == pytest.approx(1.0)
    assert summary["finite_fraction"] == pytest.approx(1.0)
    assert summary["ode_failures"] == 0
    assert summary["tafel_failures"] == 1
    assert summary["interval_semantics"] == "objective diagnostic, not confidence interval"
