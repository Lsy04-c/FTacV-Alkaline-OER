"""Contracts for the development effective-dimension smoke runner."""

import hashlib
import json

import numpy as np
import pytest

from scripts.run_effective_dimension_smoke import (
    block_balanced_noise_proxy,
    decompose_training_reports,
    estimate_anchor_stability_scales,
    evaluate_holdout_inactive_probes,
    feature_block_scales,
    feature_vector_from_current,
    load_noise_evidence,
    parse_args,
    structurally_observed_feature_names,
)


def _report(a: float, b: float) -> dict:
    return {
        "metadata": {"param_order": ["a", "b"]},
        "parameter_importance": [{"name": "a"}, {"name": "b"}],
        "signed_feature_sensitivity_matrix": [
            {"feature": "Complex H1 real", "changes": {"a": a, "b": b}}
        ],
    }


def test_decomposition_uses_training_anchors_only():
    schema = {
        "parameters": {
            "a": {"transform": "linear", "bounds": [0.0, 1.0]},
            "b": {"transform": "linear", "bounds": [0.0, 1.0]},
        }
    }
    records = [
        {"anchor_id": "train-00", "split": "train", "report": _report(1.0, 0.0)},
        {
            "anchor_id": "selection-00",
            "split": "selection",
            "report": _report(0.0, 100.0),
        },
        {
            "anchor_id": "holdout-00",
            "split": "holdout",
            "report": _report(0.0, 100.0),
        },
    ]

    payload = decompose_training_reports(records, schema)

    assert payload["training_anchor_ids"] == ["train-00"]
    assert payload["selection_anchor_ids"] == ["selection-00"]
    np.testing.assert_allclose(payload["gramian"], [[1.0, 0.0], [0.0, 0.0]])
    np.testing.assert_allclose(payload["eigenvalues"], [1.0, 0.0])
    assert payload["dimension_selection_status"] == "not_run"
    assert payload["selection_residuals"][0]["dimension"] == 1
    assert payload["selection_residuals"][0][
        "worst_relative_frobenius"
    ] == 1.0
    assert payload["selection_residuals"][1][
        "worst_relative_frobenius"
    ] == 0.0
    assert payload["subspace_alignment"]["training"]["rows"][0][
        "worst_maximum_principal_angle_degrees"
    ] == pytest.approx(0.0)
    assert payload["subspace_alignment"]["selection"]["rows"][0][
        "worst_maximum_principal_angle_degrees"
    ] == pytest.approx(90.0)
    selection_local = payload["subspace_alignment"]["selection"]["per_anchor"][0]
    assert selection_local["local_singular_values"][0] == pytest.approx(100.0)
    np.testing.assert_allclose(
        np.abs(np.asarray(selection_local["local_directions"])[:, 0]),
        [0.0, 1.0],
    )


def test_decomposition_rejects_failed_training_anchor():
    schema = {
        "parameters": {
            "a": {"transform": "linear", "bounds": [0.0, 1.0]},
        }
    }
    records = [
        {
            "anchor_id": "train-00",
            "split": "train",
            "report": {"success": False, "error": "ODE failed"},
        }
    ]

    with np.testing.assert_raises_regex(ValueError, "train-00"):
        decompose_training_reports(records, schema)


def test_decomposition_excludes_nonsmooth_optional_features_before_contract_check():
    schema = {
        "parameters": {
            "a": {"transform": "linear", "bounds": [0.0, 1.0]},
        }
    }
    base = {
        "metadata": {"param_order": ["a"]},
        "parameter_importance": [{"name": "a"}],
    }
    records = [
        {
            "anchor_id": "train-00",
            "split": "train",
            "report": {
                **base,
                "signed_feature_sensitivity_matrix": [
                    {"feature": "Complex H1 real", "changes": {"a": 1.0}}
                ],
            },
        },
        {
            "anchor_id": "train-01",
            "split": "train",
            "report": {
                **base,
                "signed_feature_sensitivity_matrix": [
                    {"feature": "Complex H1 real", "changes": {"a": 1.0}},
                    {"feature": "onset", "changes": {"a": 100.0}},
                ],
            },
        },
    ]

    payload = decompose_training_reports(records, schema)

    assert payload["feature_count"] == 1
    assert payload["excluded_nonsmooth_features"] == ["Tafel", "onset"]
    np.testing.assert_allclose(payload["gramian"], [[1.0]])


def test_noise_proxy_balances_total_weight_per_feature_block():
    proxy = block_balanced_noise_proxy(
        ["DC shape[0]", "DC shape[1]", "Complex H1 real"]
    )

    np.testing.assert_allclose(proxy, [np.sqrt(2.0), np.sqrt(2.0), 1.0])


def test_decomposition_excludes_duplicate_raw_dc_blocks():
    schema = {
        "parameters": {
            "a": {"transform": "linear", "bounds": [0.0, 1.0]},
        }
    }
    report = {
        "metadata": {"param_order": ["a"]},
        "parameter_importance": [{"name": "a"}],
        "signed_feature_sensitivity_matrix": [
            {"feature": "DC shape[0]", "changes": {"a": 1.0}},
            {"feature": "DC shape_raw[0]", "changes": {"a": 100.0}},
            {"feature": "DC amplitude_raw", "changes": {"a": 100.0}},
        ],
    }

    payload = decompose_training_reports(
        [{"anchor_id": "train-00", "split": "train", "report": report}],
        schema,
    )

    assert payload["feature_names"] == ["DC shape[0]"]
    np.testing.assert_allclose(payload["gramian"], [[1.0]])


def test_decomposition_can_freeze_a_structurally_observed_row_contract():
    schema = {
        "parameters": {
            "a": {"transform": "linear", "bounds": [0.0, 1.0]},
        }
    }
    report = {
        "metadata": {"param_order": ["a"]},
        "parameter_importance": [{"name": "a"}],
        "signed_feature_sensitivity_matrix": [
            {"feature": "Lockin H1 real[0]", "changes": {"a": 0.0}},
            {"feature": "Lockin H1 real[1]", "changes": {"a": 2.0}},
        ],
    }

    payload = decompose_training_reports(
        [{"anchor_id": "train-00", "split": "train", "report": report}],
        schema,
        observed_feature_names=["Lockin H1 real[1]"],
    )

    assert payload["feature_names"] == ["Lockin H1 real[1]"]
    np.testing.assert_allclose(payload["gramian"], [[4.0]])


def test_runner_can_reanalyze_preserved_anchor_reports(tmp_path):
    reports = tmp_path / "v2" / "anchor_reports.json"
    args = parse_args(
        [
            "--output",
            str(tmp_path / "v3"),
            "--reports",
            str(reports),
        ]
    )

    assert args.reports == reports


def test_runner_accepts_traceable_noise_evidence(tmp_path):
    evidence = tmp_path / "noise_evidence.json"
    args = parse_args(
        [
            "--output",
            str(tmp_path / "v7"),
            "--reports",
            str(tmp_path / "v2" / "anchor_reports.json"),
            "--noise-evidence",
            str(evidence),
            "--noise-replicates",
            "48",
            "--anchor-seed",
            "23",
            "--train-anchors",
            "12",
            "--selection-anchors",
            "4",
            "--holdout-anchors",
            "2",
        ]
    )

    assert args.noise_evidence == evidence
    assert args.noise_replicates == 48
    assert args.anchor_seed == 23
    assert (args.train_anchors, args.selection_anchors, args.holdout_anchors) == (
        12,
        4,
        2,
    )


def test_holdout_probe_runs_all_candidate_dimensions_without_selecting_one():
    schema = {
        "parameters": {
            "a": {"transform": "linear", "bounds": [0.0, 1.0]},
            "b": {"transform": "linear", "bounds": [0.0, 1.0]},
        }
    }
    records = [
        {
            "anchor_id": "holdout-00",
            "split": "holdout",
            "unit_coordinates": [0.5, 0.5],
        }
    ]
    decomposition = {
        "parameter_names": ["a", "b"],
        "feature_names": ["Complex H1 real"],
        "directions": np.eye(2).tolist(),
    }

    def analytical_forward(params, _config):
        return {"Complex H1 real": params["a"] + 2.0 * params["b"]}

    result = evaluate_holdout_inactive_probes(
        records,
        schema,
        decomposition,
        config=None,
        forward_runner=analytical_forward,
    )

    assert result["holdout_anchor_ids"] == ["holdout-00"]
    assert result["dimension_selection_status"] == "not_selected_from_holdout"
    assert result["rows"][0]["dimension"] == 1
    assert result["rows"][0][
        "worst_normalized_feature_deviation"
    ] == pytest.approx(0.1 / 1.5)
    assert result["rows"][1]["dimension"] == 2
    assert result["rows"][1]["worst_normalized_feature_deviation"] == 0.0


def test_holdout_probe_can_report_deviation_in_frozen_stability_units():
    schema = {
        "parameters": {
            "a": {"transform": "linear", "bounds": [0.0, 1.0]},
            "b": {"transform": "linear", "bounds": [0.0, 1.0]},
        }
    }
    records = [
        {
            "anchor_id": "holdout-00",
            "split": "holdout",
            "unit_coordinates": [0.5, 0.5],
        }
    ]
    decomposition = {
        "parameter_names": ["a", "b"],
        "feature_names": ["Complex H1 real"],
        "directions": np.eye(2).tolist(),
    }

    result = evaluate_holdout_inactive_probes(
        records,
        schema,
        decomposition,
        config=None,
        forward_runner=lambda params, _config: {
            "Complex H1 real": params["a"] + 2.0 * params["b"]
        },
        stability_scales={"holdout-00": np.array([0.01])},
    )

    assert result["normalization"] == "frozen_diagonal_feature_stability"
    assert result["rows"][0]["worst_normalized_feature_deviation"] == pytest.approx(
        (0.1 / 1.5) / 0.01
    )


def test_decomposition_uses_supplied_anchor_stability_and_selection_gate():
    schema = {
        "parameters": {
            "a": {"transform": "linear", "bounds": [0.0, 1.0]},
            "b": {"transform": "linear", "bounds": [0.0, 1.0]},
        }
    }
    records = [
        {"anchor_id": "train-00", "split": "train", "report": _report(2.0, 0.0)},
        {
            "anchor_id": "selection-00",
            "split": "selection",
            "report": _report(0.0, 0.5),
        },
    ]

    payload = decompose_training_reports(
        records,
        schema,
        stability_scales={
            "train-00": np.array([2.0]),
            "selection-00": np.array([1.0]),
        },
    )

    assert payload["noise_model"] == "diagonal_quantization_stability_floor"
    assert payload["dimension_selection"] == {
        "status": "candidate_selected_from_selection",
        "candidate_dimension": 1,
        "maximum_whitened_operator_norm": 1.0,
        "reduction_achieved": True,
    }


def test_feature_vector_from_current_flattens_complex_and_lockin_channels():
    class Config:
        fit_harmonics = (1,)

    def extractor(_current, _config):
        return {
            "dc": np.array([0.1, 0.2]),
            "complex_harmonics": {"complex": np.array([1.0 + 2.0j])},
            "lockin": {
                "valid_mask": np.array([True, False]),
                "complex": [np.array([3.0 + 4.0j, 5.0 + 6.0j])],
            },
        }

    vector = feature_vector_from_current(
        np.array([0.0]),
        Config(),
        [
            "DC shape[1]",
            "Complex H1 real",
            "Complex H1 imag",
            "Lockin H1 real[0]",
            "Lockin H1 imag[1]",
        ],
        feature_extractor=extractor,
    )

    np.testing.assert_allclose(vector, [0.2, 1.0, 2.0, 3.0, 0.0])


def test_feature_block_scales_use_one_frozen_maximum_per_block():
    scales = feature_block_scales(
        ["DC shape[0]", "DC shape[1]", "Complex H1 real"],
        np.array([0.25, -1.0, 0.1]),
    )

    np.testing.assert_allclose(scales, [1.0, 1.0, 0.1])


def test_structural_lockin_contract_uses_valid_mask_not_signal_values():
    class Config:
        n_points = 4

    def extractor(_current, _config):
        return {"lockin": {"valid_mask": np.array([False, True, True, False])}}

    included, excluded = structurally_observed_feature_names(
        Config(),
        [
            "DC shape[0]",
            "Lockin H1 real[0]",
            "Lockin H1 real[1]",
            "Lockin H1 imag[2]",
            "Lockin H1 imag[3]",
        ],
        feature_extractor=extractor,
    )

    assert included == [
        "DC shape[0]",
        "Lockin H1 real[1]",
        "Lockin H1 imag[2]",
    ]
    assert excluded == ["Lockin H1 real[0]", "Lockin H1 imag[3]"]


def test_anchor_stability_is_estimated_for_every_frozen_split():
    schema = {
        "parameters": {
            "a": {"transform": "linear", "bounds": [1.0, 3.0]},
        }
    }
    records = [
        {
            "anchor_id": "train-00",
            "split": "train",
            "unit_coordinates": [0.25],
        },
        {
            "anchor_id": "selection-00",
            "split": "selection",
            "unit_coordinates": [0.75],
        },
    ]

    scales, audit = estimate_anchor_stability_scales(
        records,
        schema,
        parameter_names=["a"],
        feature_names=["signal[0]", "signal[1]"],
        config=None,
        noise_fraction=0.01,
        noise_seeds=[2, 3, 5, 7],
        current_runner=lambda params, _config: np.array(
            [params["a"], -2.0 * params["a"]]
        ),
        feature_vector_runner=lambda current, _config, _names: np.asarray(current),
    )

    assert set(scales) == {"train-00", "selection-00"}
    assert all(value.shape == (2,) for value in scales.values())
    assert audit["distribution"] == "uniform_quantization_error"
    assert audit["noise_seeds"] == [2, 3, 5, 7]
    assert [row["anchor_id"] for row in audit["anchors"]] == [
        "train-00",
        "selection-00",
    ]


def test_noise_evidence_is_recomputed_and_hashed(tmp_path):
    path = tmp_path / "noise.json"
    payload = {
        "selection_rule": "maximum_dataset_noise_floor",
        "selected_noise_fraction": 0.02,
        "datasets": [
            {"noise": {"noise_fraction": 0.01}},
            {"noise": {"noise_fraction": 0.02}},
        ],
        "limitation": "quantization floor only",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = load_noise_evidence(path)

    assert result["selected_noise_fraction"] == 0.02
    assert result["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result["limitation"] == "quantization floor only"


def test_noise_evidence_rejects_unreproducible_selected_fraction(tmp_path):
    path = tmp_path / "noise.json"
    path.write_text(
        json.dumps(
            {
                "selection_rule": "maximum_dataset_noise_floor",
                "selected_noise_fraction": 0.03,
                "datasets": [{"noise": {"noise_fraction": 0.02}}],
                "limitation": "quantization floor only",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="selected noise fraction"):
        load_noise_evidence(path)
