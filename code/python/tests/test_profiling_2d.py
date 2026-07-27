"""Unit tests for 2D objective profile functions."""
import numpy as np
import pytest

from oer_aem.profiling import (
    profile_grid_2d,
    summarize_profile_2d,
)


class TestProfileGrid2D:
    def test_grid_shape_and_truth_inclusion(self):
        grid = profile_grid_2d(0.5, 0.3, grid_points=5)
        # 0.5 is on the 5-point linspace, 0.3 is not → 5 × 6 = 30
        assert grid.shape[1] == 2
        assert grid.shape[0] >= 25
        assert np.any(np.isclose(grid[:, 0], 0.5, atol=1e-12))
        assert np.any(np.isclose(grid[:, 1], 0.3, atol=1e-12))

    def test_grid_no_duplicates(self):
        grid = profile_grid_2d(0.2, 0.8, grid_points=7)
        uniq = np.unique(grid, axis=0)
        assert len(uniq) == len(grid)

    def test_grid_boundaries(self):
        grid = profile_grid_2d(0.0, 1.0, grid_points=3)
        assert np.min(grid[:, 0]) == 0.0
        assert np.max(grid[:, 0]) == 1.0
        assert np.min(grid[:, 1]) == 0.0
        assert np.max(grid[:, 1]) == 1.0

    def test_rejects_invalid_truth(self):
        with pytest.raises(ValueError):
            profile_grid_2d(1.5, 0.5)


class TestSummarizeProfile2D:
    def _make_rows(self, xs, ys, losses, *, ode_success=True):
        return [
            {
                "x_coordinate": float(x),
                "y_coordinate": float(y),
                "total_loss": float(l),
                "ode_success": ode_success,
                "tafel_failed": False,
            }
            for x, y, l in zip(xs, ys, losses)
        ]

    def test_truth_global_min_parabolic(self):
        xs = [0.0, 0.5, 1.0, 0.0, 0.5, 1.0, 0.0, 0.5, 1.0]
        ys = [0.0, 0.0, 0.0, 0.5, 0.5, 0.5, 1.0, 1.0, 1.0]
        # Parabolic bowl with minimum at truth (0.5, 0.5)
        losses = [(x - 0.5) ** 2 + (y - 0.5) ** 2 for x, y in zip(xs, ys)]
        rows = self._make_rows(xs, ys, losses)
        s = summarize_profile_2d(rows, x_truth=0.5, y_truth=0.5,
                                 x_param="a", y_param="b")
        assert s["is_global_min_at_truth"] is True
        assert s["coupling_strength"] < 0.3  # independent axes

    def test_diagonal_valley_coupling(self):
        xs = [0.0, 0.1, 0.5, 0.9, 1.0]
        ys = [1.0, 0.9, 0.5, 0.1, 0.0]
        # Loss depends on x + y (compensating): minimum when x+y ≈ 1.0
        losses = [abs(x + y - 1.0) for x, y in zip(xs, ys)]
        rows = self._make_rows(xs, ys, losses)
        s = summarize_profile_2d(rows, x_truth=0.5, y_truth=0.5,
                                 x_param="a", y_param="b")
        assert s["coupling_strength"] > 0.5

    def test_rejects_missing_truth(self):
        rows = self._make_rows([0.0], [0.0], [1.0])
        with pytest.raises(ValueError):
            summarize_profile_2d(rows, x_truth=0.5, y_truth=0.5,
                                 x_param="a", y_param="b")

    def test_rejects_empty_rows(self):
        with pytest.raises(ValueError):
            summarize_profile_2d([], x_truth=0.5, y_truth=0.5,
                                 x_param="a", y_param="b")
