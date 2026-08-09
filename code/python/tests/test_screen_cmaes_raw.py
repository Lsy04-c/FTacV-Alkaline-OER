"""Contract tests for the raw-CMA scientific entry point."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from oer_aem.inversion import DEFAULT_PARAM_SPECS, InversionConfig, decode_vector


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "screen_cmaes_raw.py"


def _load_screen_module(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    fake_cmaes = types.ModuleType("cmaes")
    monkeypatch.setitem(sys.modules, "cmaes", fake_cmaes)
    module_name = "screen_cmaes_raw_test_module"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_fixed_override_updates_target_truth_and_metrics(monkeypatch):
    module = _load_screen_module(monkeypatch)
    midpoint = decode_vector(
        [(low + high) / 2 for _, _, low, high in DEFAULT_PARAM_SPECS]
    )
    original_k0_1 = midpoint["k0_1"]
    captured = {}
    free_specs = (DEFAULT_PARAM_SPECS[1],)

    monkeypatch.setattr(
        module,
        "truth_library",
        lambda specs: [{"truth_id": "mixed_b", "parameters": dict(midpoint)}],
    )

    def fake_build_problem(job, *, smoke):
        captured["job_truth"] = dict(job["truth_params"])
        captured["job_selection"] = job["parameter_selection"]
        captured["job_selection_hash"] = job["parameter_selection_sha256"]
        return InversionConfig(n_points=8), free_specs

    monkeypatch.setattr(module, "build_recovery_problem", fake_build_problem)

    def fake_target(params, *, config, noise_fraction, seed):
        captured["target_truth"] = dict(params)
        return {"dummy": np.asarray([0.0])}

    monkeypatch.setattr(module, "make_synthetic_target", fake_target)

    class FakeObjective:
        n_forward = 1
        n_ode_fail = 0
        n_feature_fail = 0
        n_tafel_fail = 0

        def __init__(self, target, config, specs):
            captured["fixed_params"] = dict(config.fixed_params)

        def __call__(self, vector):
            return 0.0

    monkeypatch.setattr(module, "InversionObjective", FakeObjective)

    class FakeCMA:
        def __init__(self, **kwargs):
            self._mean = np.asarray(kwargs["mean"], dtype=float)

        def ask(self):
            return self._mean.copy()

        def tell(self, values):
            return None

        def should_stop(self):
            return False

    sys.modules["cmaes"].CMA = FakeCMA

    def fake_metrics(*, truth, estimate, specs):
        captured["metric_truth"] = dict(truth)
        return {name: {"normalized_bound_error": 0.0} for name, *_ in specs}

    monkeypatch.setattr(module, "recovery_metrics", fake_metrics)

    result = module.run_raw_cmaes(
        "legacy",
        seed=7,
        trials=1,
        smoke=True,
        free_names=("k0_2",),
        fixed_override={"k0_1": 10000.0},
        diagnostic=True,
    )

    for values in (
        captured["job_truth"],
        captured["target_truth"],
        captured["fixed_params"],
        captured["metric_truth"],
    ):
        if "k0_1" in values:
            assert values["k0_1"] == pytest.approx(10000.0)
    assert result["original_truth"]["k0_1"] == pytest.approx(original_k0_1)
    assert result["effective_truth"]["k0_1"] == pytest.approx(10000.0)
    assert result["truth"]["k0_1"] == pytest.approx(10000.0)
    evidence = result["search_policy"]["parameter_selection"]
    assert set(evidence["role_groups"]) == {"free", "fixed", "diagnostic"}
    assert set(evidence["free_parameters"]) == {"k0_2"}
    assert evidence["diagnostic_parameters"] == []
    assert evidence["role_override"] is False
    assert len(result["search_policy"]["selection_evidence_sha256"]) == 64
    assert result["provenance"]["parameter_selection"] == evidence
    assert result["provenance"]["parameter_selection_sha256"] == result[
        "search_policy"
    ]["selection_evidence_sha256"]
    assert captured["job_selection"] == evidence
    assert captured["job_selection_hash"] == result["search_policy"][
        "selection_evidence_sha256"
    ]


def test_missing_cmaes_dependency_reports_auditable_error(monkeypatch):
    module = _load_screen_module(monkeypatch)
    monkeypatch.setitem(sys.modules, "cmaes", None)
    with pytest.raises(RuntimeError, match="cmaes.*install"):
        module._load_cmaes()


def test_formal_run_rejects_unhashed_numeric_profile_width(monkeypatch):
    module = _load_screen_module(monkeypatch)
    with pytest.raises(ValueError, match="hashed profile summary"):
        module.run_raw_cmaes(
            "hybrid",
            seed=7,
            trials=1,
            free_names=("k0_2",),
            profile_half_width=0.05,
            diagnostic=False,
        )
