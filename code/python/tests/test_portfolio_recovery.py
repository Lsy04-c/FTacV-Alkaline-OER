from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from oer_aem import portfolio_recovery
from oer_aem.inversion import DEFAULT_PARAM_SPECS
from oer_aem.recovery import recovery_metrics, truth_library


ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = ROOT / "config" / "recovery" / "pre-experiment-a6-v2.json"


def test_pre_experiment_recovery_contract_exists() -> None:
    assert SPEC_PATH.is_file()
    assert importlib.util.find_spec("oer_aem.portfolio_recovery") is not None


def test_portfolio_recovery_exposes_frozen_spec_loader() -> None:
    assert hasattr(portfolio_recovery, "load_pre_experiment_spec")


def test_frozen_spec_has_exact_scientific_matrix() -> None:
    spec = portfolio_recovery.load_pre_experiment_spec(SPEC_PATH)
    assert tuple(spec.portfolios) == ("P0", "P1", "P2")
    assert spec.portfolios["P0"] == ("baseline_5hz_amp_016",)
    assert spec.portfolios["P1"] == (
        "baseline_5hz_amp_016",
        "candidate_5hz_amp_008",
    )
    assert spec.portfolios["P2"] == (
        "baseline_5hz_amp_016",
        "candidate_5hz_amp_008",
        "candidate_10hz_matched_scan",
    )
    assert spec.parameter_pairs == (
        ("k0_2", "k0_3"),
        ("k0_3", "G_O"),
        ("G_OH", "G_O"),
    )
    assert spec.truth_ids == ("center", "mixed_a", "mixed_b")
    assert spec.optimizer_seeds == (7, 17, 27)
    assert spec.trials == 100
    assert spec.fit_harmonics == (1, 2, 3)
    assert spec.feature_mode == "hybrid"
    assert spec.feature_grid_size == 128
    assert spec.formal_backend == "lsoda"
    assert spec.noise_fractions == {
        "S1": 0.0,
        "S2": 0.001495726085983469,
    }


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("trials",), 99),
        (("formal_backend",), "cn"),
        (("feature_mode",), "legacy"),
        (("fit_harmonics",), [1, 2, 3, 4]),
        (("feature_grid_size",), 64),
        (("thresholds", "max_normalized_bound_error"), 0.051),
        (("portfolios", "P1"), ["candidate_5hz_amp_008"]),
    ],
)
def test_loader_rejects_changes_to_frozen_contract(
    tmp_path: Path,
    path: tuple[str, ...],
    value: object,
) -> None:
    payload = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    candidate = tmp_path / "spec.json"
    candidate.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        portfolio_recovery.load_pre_experiment_spec(candidate)


class StubObjective:
    def __init__(self, value: float) -> None:
        self.value = value
        self.n_calls = 0
        self.n_forward = 0
        self.n_ode_fail = 0
        self.n_feature_fail = 0
        self.n_tafel_fail = 0
        self.best_value = float("inf")
        self.best_x = None
        self.last_components = {"stub": value}
        self.best_components = {}

    def __call__(self, x) -> float:
        self.n_calls += 1
        self.n_forward += 1
        if self.value < self.best_value:
            self.best_value = self.value
            self.best_x = np.asarray(x, dtype=float)
            self.best_components = dict(self.last_components)
        return self.value


def test_target_identity_is_independent_of_portfolio() -> None:
    identity = portfolio_recovery.target_identity(
        "mixed_a", 0.001495726085983469, "baseline_5hz_amp_016"
    )
    repeated = portfolio_recovery.target_identity(
        "mixed_a", 0.001495726085983469, "baseline_5hz_amp_016"
    )
    assert identity == repeated
    assert set(identity) == {"target_key", "target_seed"}
    assert "P0" not in identity["target_key"]


def test_target_hash_covers_hybrid_inputs_and_channel_contract() -> None:
    target = {
        "current": np.array([1.0, 2.0]),
        "dc": np.array([0.1, 0.2]),
        "harm": [np.array([float(i), float(i + 1)]) for i in range(1, 4)],
        "complex_harmonics": {
            "amplitude": np.array([1.0, 2.0, 3.0]),
            "phase": np.array([0.1, 0.2, 0.3]),
        },
        "lockin": {
            "amplitude": [np.array([1.0, 2.0])] * 3,
            "phase": [np.array([0.1, 0.2])] * 3,
            "valid_mask": np.array([True, False]),
        },
    }
    original = portfolio_recovery.target_sha256(target, "contract-a")
    changed = dict(target)
    changed["lockin"] = dict(target["lockin"])
    changed["lockin"]["phase"] = list(target["lockin"]["phase"])
    changed["lockin"]["phase"][2] = np.array([0.1, 0.25])
    assert portfolio_recovery.target_sha256(changed, "contract-a") != original
    assert portfolio_recovery.target_sha256(target, "contract-b") != original


def test_portfolio_objective_is_equal_mean_after_condition_normalization() -> None:
    left = StubObjective(2.0)
    right = StubObjective(8.0)
    objective = portfolio_recovery.PortfolioObjective(
        (("left", left), ("right", right)),
        failure_penalty=1e9,
    )
    assert objective([0.5, 0.5]) == 5.0
    assert left.n_calls == 1 and right.n_calls == 1
    assert objective.n_forward == 2
    assert objective.last_condition_losses == {"left": 2.0, "right": 8.0}


def test_portfolio_objective_rejects_duplicate_conditions_and_nonfinite_loss() -> None:
    with pytest.raises(ValueError, match="unique"):
        portfolio_recovery.PortfolioObjective(
            (("same", StubObjective(1.0)), ("same", StubObjective(2.0))),
            failure_penalty=99.0,
        )
    objective = portfolio_recovery.PortfolioObjective(
        (("finite", StubObjective(1.0)), ("bad", StubObjective(float("nan")))),
        failure_penalty=99.0,
    )
    assert objective([0.5]) == 99.0


def test_target_manifest_rejects_hash_conflicts() -> None:
    records = [
        {"target_key": "truth|0|condition", "target_sha256": "a" * 64},
        {"target_key": "truth|0|condition", "target_sha256": "b" * 64},
    ]
    with pytest.raises(ValueError, match="conflicting"):
        portfolio_recovery.validate_target_reuse(records)


def test_condition_config_uses_protocol_grid_and_freezes_nonfree_truth() -> None:
    spec = portfolio_recovery.load_pre_experiment_spec(SPEC_PATH)
    truth = truth_library(DEFAULT_PARAM_SPECS)[1]["parameters"]
    free_specs = tuple(
        item for item in DEFAULT_PARAM_SPECS if item[0] in {"k0_2", "k0_3"}
    )
    condition = spec.conditions["baseline_5hz_amp_016"]

    config = portfolio_recovery.build_condition_config(
        spec,
        condition,
        truth=truth,
        free_specs=free_specs,
        backend="lsoda",
        seed=17,
        smoke=False,
    )

    assert config.E_start == pytest.approx(condition.E_start)
    assert config.E_end == pytest.approx(condition.E_end)
    assert config.f == 5.0
    assert config.dE == 0.16
    assert config.n_points == 256 * 128
    assert config.points_per_cycle == 128
    assert config.feature_grid_size == 128
    assert config.fit_harmonics == (1, 2, 3)
    assert config.feature_mode == "hybrid"
    assert config.solver_backend == "lsoda"
    fixed = dict(config.fixed_params)
    assert set(fixed) == set(truth) - {"k0_2", "k0_3"} | {"beta_recon"}
    assert fixed["beta_recon"] == 0.0
    assert fixed["G_O"] == truth["G_O"]


def test_condition_config_rejects_formal_cn_backend() -> None:
    spec = portfolio_recovery.load_pre_experiment_spec(SPEC_PATH)
    truth = truth_library(DEFAULT_PARAM_SPECS)[0]["parameters"]
    with pytest.raises(ValueError, match="formal backend"):
        portfolio_recovery.build_condition_config(
            spec,
            spec.conditions["baseline_5hz_amp_016"],
            truth=truth,
            free_specs=(DEFAULT_PARAM_SPECS[1], DEFAULT_PARAM_SPECS[2]),
            backend="cn",
            seed=7,
            smoke=False,
        )


@pytest.mark.parametrize(
    ("passes", "expected"),
    [
        ({"P0": True, "P1": True, "P2": True}, "BASELINE_SUFFICIENT"),
        ({"P0": False, "P1": True, "P2": True}, "AMP_008_ADDS_RECOVERY"),
        ({"P0": False, "P1": False, "P2": True}, "TEN_HZ_ADDS_RECOVERY"),
        ({"P0": False, "P1": False, "P2": False}, "DESIGN_INSUFFICIENT"),
        (
            {"P0": True, "P1": False, "P2": True},
            "NON_MONOTONIC_REQUIRES_REVIEW",
        ),
        (
            {"P0": True, "P1": True, "P2": False},
            "NON_MONOTONIC_REQUIRES_REVIEW",
        ),
    ],
)
def test_portfolio_classification_is_absolute_and_monotonic(
    passes: dict[str, bool], expected: str
) -> None:
    assert portfolio_recovery.classify_portfolio_passes(passes) == expected


def test_s1_summary_rebuilds_all_groups_and_eligible_pairs() -> None:
    spec = portfolio_recovery.load_pre_experiment_spec(SPEC_PATH)
    jobs = portfolio_recovery.build_portfolio_jobs(
        spec,
        stage="S1",
        backend="lsoda",
    )
    rows = []
    for job in jobs:
        free_specs = tuple(
            item
            for item in DEFAULT_PARAM_SPECS
            if item[0] in set(job["free_parameters"])
        )
        rows.append(
            {
                **job,
                "success": True,
                "parameter_metrics": recovery_metrics(
                    truth=job["truth_params"],
                    estimate=job["truth_params"],
                    specs=free_specs,
                ),
            }
        )

    summary = portfolio_recovery.summarize_portfolio_recovery(
        rows,
        spec=spec,
        stage="S1",
    )

    assert summary["group_count"] == 27
    assert len(summary["parameter_pair_results"]) == 3
    assert summary["eligible_parameter_pairs"] == [
        ["k0_2", "k0_3"],
        ["k0_3", "G_O"],
        ["G_OH", "G_O"],
    ]
    assert {item["classification"] for item in summary["parameter_pair_results"]} == {
        "BASELINE_SUFFICIENT"
    }
    assert summary["stage_status"] == "S1_ELIGIBLE"
    assert summary["scientific_gate_passed"] is True
