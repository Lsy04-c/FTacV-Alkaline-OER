"""Tests for deterministic V3 candidate selection and residual contracts."""

from __future__ import annotations

import numpy as np
import pytest

from oer_aem.residual_attribution import (
    classify_sign_consistency,
    segment_masks,
    select_representative_candidates,
    signed_feature_residuals,
    summarize_candidate_residuals,
    summarize_ensemble,
)


def _success_rows(count: int) -> list[dict[str, object]]:
    rows = []
    for candidate_id in range(count):
        rows.append(
            {
                "candidate_id": candidate_id,
                "score": float(candidate_id + 1),
                "success": True,
                "unit_params": [
                    ((candidate_id * prime) % count) / count
                    for prime in (1, 3, 5, 7, 11)
                ],
            }
        )
    return rows


def test_select_representative_candidates_keeps_best_and_is_deterministic():
    rows = _success_rows(80)

    first = select_representative_candidates(
        rows,
        pool_size=64,
        ensemble_size=12,
    )
    second = select_representative_candidates(
        list(reversed(rows)),
        pool_size=64,
        ensemble_size=12,
    )

    assert first == second
    assert first[0]["candidate_id"] == 0
    assert len(first) == 12
    assert len({int(row["candidate_id"]) for row in first}) == 12


def test_select_representative_candidates_rejects_small_success_pool():
    rows = _success_rows(64)
    rows[-1]["success"] = False

    with pytest.raises(ValueError, match="at least 64 successful"):
        select_representative_candidates(
            rows,
            pool_size=64,
            ensemble_size=12,
        )


def test_select_representative_candidates_records_non_decreasing_steps():
    selected = select_representative_candidates(
        _success_rows(80),
        pool_size=64,
        ensemble_size=12,
    )

    assert selected[0]["selection_min_distance"] is None
    assert all(
        np.isfinite(float(row["selection_min_distance"]))
        and float(row["selection_min_distance"]) >= 0.0
        for row in selected[1:]
    )


def _features(
    *,
    dc: list[float],
    global_amplitude: list[float],
    global_phase: list[float],
    lockin_amplitude: list[list[float]],
    lockin_phase: list[list[float]],
    valid_mask: list[bool] | None = None,
) -> dict[str, object]:
    return {
        "dc": dc,
        "complex_harmonics": {
            "amplitude": global_amplitude,
            "phase": global_phase,
        },
        "lockin": {
            "amplitude": lockin_amplitude,
            "phase": lockin_phase,
            "valid_mask": valid_mask or [True] * len(dc),
        },
    }


def test_signed_residuals_use_experiment_minus_simulation_and_wrapped_phase():
    target = _features(
        dc=[2.0, 4.0],
        global_amplitude=[2.0],
        global_phase=[3.1],
        lockin_amplitude=[[2.0, 4.0]],
        lockin_phase=[[3.1, -3.1]],
    )
    simulated = _features(
        dc=[1.0, 6.0],
        global_amplitude=[1.0],
        global_phase=[-3.1],
        lockin_amplitude=[[1.0, 6.0]],
        lockin_phase=[[-3.1, 3.1]],
    )

    result = signed_feature_residuals(
        target,
        simulated,
        harmonics=(1,),
    )

    np.testing.assert_allclose(result["dc"], [0.25, -0.5])
    np.testing.assert_allclose(result["global_amplitude_h1"], [0.5])
    assert np.all(np.abs(result["global_phase_h1"]) <= np.pi)
    np.testing.assert_allclose(result["lockin_amplitude_h1"], [0.25, -0.5])
    assert np.all(np.abs(result["lockin_phase_h1"]) <= np.pi)


def test_segment_masks_are_26_76_26_for_128_points():
    masks = segment_masks(128)

    assert [int(masks[name].sum()) for name in ("low", "mid", "high")] == [
        26,
        76,
        26,
    ]
    assert np.all(sum(masks.values()) == 1)


def test_signed_residuals_allow_nonfinite_lockin_values_outside_valid_mask():
    target = _features(
        dc=[1.0, 1.0],
        global_amplitude=[1.0],
        global_phase=[0.0],
        lockin_amplitude=[[1.0, np.nan]],
        lockin_phase=[[0.0, np.nan]],
        valid_mask=[True, False],
    )
    simulated = _features(
        dc=[1.0, 1.0],
        global_amplitude=[1.0],
        global_phase=[0.0],
        lockin_amplitude=[[0.5, np.nan]],
        lockin_phase=[[0.1, np.nan]],
        valid_mask=[True, False],
    )

    result = signed_feature_residuals(target, simulated, harmonics=(1,))

    np.testing.assert_allclose(result["lockin_amplitude_h1"], [0.5, 0.0])
    np.testing.assert_array_equal(result["lockin_valid_mask"], [True, False])


def test_ensemble_direction_requires_nine_of_twelve_same_sign():
    assert (
        classify_sign_consistency([1.0] * 9 + [-1.0] * 3)
        == "ensemble sign-consistent"
    )
    assert (
        classify_sign_consistency([1.0] * 8 + [-1.0] * 4)
        == "candidate-dependent"
    )


def test_candidate_and_ensemble_summaries_keep_channels_separate():
    residuals = {
        "dc": np.linspace(-1.0, 1.0, 128),
        "global_amplitude_h1": np.asarray([0.25]),
        "global_phase_h1": np.asarray([-0.5]),
        "lockin_amplitude_h1": np.ones(128),
        "lockin_phase_h1": -np.ones(128),
        "lockin_valid_mask": np.ones(128, dtype=bool),
    }
    candidate_rows = []
    for candidate_id in range(12):
        candidate_rows.extend(
            summarize_candidate_residuals(
                residuals,
                dataset_id="FT2",
                candidate_id=candidate_id,
            )
        )

    ensemble = summarize_ensemble(
        candidate_rows,
        nearest_candidate_id=0,
        ensemble_size=12,
    )

    assert {row["channel"] for row in ensemble} == {
        "dc",
        "global_amplitude_h1",
        "global_phase_h1",
        "lockin_amplitude_h1",
        "lockin_phase_h1",
    }
    lockin_amplitude = next(
        row
        for row in ensemble
        if row["channel"] == "lockin_amplitude_h1"
        and row["segment"] == "low"
    )
    assert lockin_amplitude["direction_class"] == "ensemble sign-consistent"
    assert lockin_amplitude["nearest_within_iqr"] is True


def test_empty_lockin_segment_is_not_observable_instead_of_failure():
    residuals = {
        "dc": np.zeros(128),
        "global_amplitude_h1": np.asarray([0.0]),
        "global_phase_h1": np.asarray([0.0]),
        "lockin_amplitude_h1": np.zeros(128),
        "lockin_phase_h1": np.zeros(128),
        "lockin_valid_mask": np.asarray(
            [False] * 26 + [True] * 76 + [False] * 26,
            dtype=bool,
        ),
    }
    candidate_rows = []
    for candidate_id in range(12):
        candidate_rows.extend(
            summarize_candidate_residuals(
                residuals,
                dataset_id="FT2",
                candidate_id=candidate_id,
            )
        )

    low = next(
        row
        for row in candidate_rows
        if row["candidate_id"] == 0
        and row["channel"] == "lockin_amplitude_h1"
        and row["segment"] == "low"
    )
    ensemble = summarize_ensemble(
        candidate_rows,
        nearest_candidate_id=0,
        ensemble_size=12,
    )
    ensemble_low = next(
        row
        for row in ensemble
        if row["channel"] == "lockin_amplitude_h1"
        and row["segment"] == "low"
    )

    assert low["n_points"] == 0
    assert low["signed_mean"] is None
    assert ensemble_low["direction_class"] == "not-observable"
