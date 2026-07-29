import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[3]
SPEC = ROOT / "config" / "reachability" / "v2-conditional-reachability.json"
sys.path.insert(0, str(ROOT / "code" / "python" / "scripts"))


def test_v2_task_spec_freezes_science_inputs():
    spec = json.loads(SPEC.read_text(encoding="utf-8"))

    assert spec["candidate_count"] == 512
    assert spec["sobol_seed"] == 29
    assert spec["solver_backend"] == "lsoda"
    assert spec["points_per_cycle"] == 128
    assert spec["feature_grid_size"] == 128
    assert spec["fit_harmonics"] == [1, 2, 3]
    assert len(spec["diagnostic_parameter_specs"]) == 5
    assert len(spec["fixed_baseline"]) == 8
    assert len(spec["fixed_stress_scenarios"]) == 16
    assert {row["dataset_id"] for row in spec["datasets"]} == {
        "FT2",
        "FT3",
        "FT4",
        "FT8",
    }
    assert all(len(row["sha256"]) == 64 for row in spec["datasets"])
    assert spec["metadata_conditions"]["instrument_preprocessing"] == (
        "unresolved"
    )


def test_smoke_job_plan_contains_all_four_datasets_and_no_stress():
    from run_conditional_reachability import build_job_plan, load_spec

    plan = build_job_plan(load_spec(SPEC), smoke=True)

    assert len(plan["base_jobs"]) == 32
    assert plan["stress_jobs"] == []
    assert {row["dataset_id"] for row in plan["base_jobs"]} == {
        "FT2",
        "FT3",
        "FT4",
        "FT8",
    }
    assert len({row["job_id"] for row in plan["base_jobs"]}) == 32
    assert all(len(row["job_input_hash"]) == 64 for row in plan["base_jobs"])


def test_resume_rejects_job_hash_conflict(tmp_path):
    from run_conditional_reachability import (
        build_job_plan,
        load_resume_state,
        load_spec,
    )

    jobs = build_job_plan(load_spec(SPEC), smoke=True)["base_jobs"]
    row = {
        "job_id": jobs[0]["job_id"],
        "job_input_hash": "0" * 64,
        "success": False,
        "failure_kind": "ODE",
    }
    (tmp_path / "base_results.jsonl").write_text(
        json.dumps(row) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="job hash"):
        load_resume_state(tmp_path, jobs)


def test_resume_rejects_partial_json_and_unknown_files(tmp_path):
    from run_conditional_reachability import (
        build_job_plan,
        load_resume_state,
        load_spec,
    )

    jobs = build_job_plan(load_spec(SPEC), smoke=True)["base_jobs"]
    (tmp_path / "base_results.jsonl").write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="incomplete"):
        load_resume_state(tmp_path, jobs)

    (tmp_path / "base_results.jsonl").unlink()
    (tmp_path / "unexpected.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown output"):
        load_resume_state(tmp_path, jobs)


def test_output_guards_allow_only_oer_wf_owned_files(tmp_path):
    from run_conditional_reachability import _prepare_output, load_resume_state

    (tmp_path / "STATUS.json").write_text("{}", encoding="utf-8")
    (tmp_path / "task_spec.snapshot.yaml").write_text(
        "task_name: fixture\n",
        encoding="utf-8",
    )

    _prepare_output(tmp_path, resume=False)
    assert load_resume_state(tmp_path, []) == {}

    (tmp_path / "unexpected.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="output directory is not empty"):
        _prepare_output(tmp_path, resume=False)
    with pytest.raises(ValueError, match="unknown output"):
        load_resume_state(tmp_path, [])


def test_feature_match_uses_wrapped_phase_and_valid_intersection():
    from run_conditional_reachability import compute_feature_match

    target = {
        "dc": np.array([0.0, 1.0]),
        "complex_harmonics": {
            "amplitude": np.array([2.0]),
            "phase": np.array([np.pi - 0.05]),
        },
        "lockin": {
            "amplitude": [np.array([1.0, 2.0])],
            "phase": [np.array([np.pi - 0.05, 0.0])],
            "valid_mask": np.array([True, True]),
        },
        "e_grid": np.array([1.0, 1.1]),
    }
    candidate = {
        "dc": np.array([0.0, 1.0]),
        "complex_harmonics": {
            "amplitude": np.array([2.0]),
            "phase": np.array([-np.pi + 0.05]),
        },
        "lockin": {
            "amplitude": [np.array([1.0, 2.0])],
            "phase": [np.array([-np.pi + 0.05, 9.0])],
            "valid_mask": np.array([True, False]),
        },
        "e_grid": np.array([1.0, 1.1]),
    }
    thresholds = {
        "dc_nrmse": 0.1,
        "global_amplitude_relative_error": 0.1,
        "global_phase_error_rad": 0.1,
        "lockin_amplitude_nrmse": 0.1,
        "lockin_phase_rmse_rad": 0.1,
        "lockin_peak_shift_v": 0.025,
        "lockin_valid_fraction_min": 0.5,
    }

    result = compute_feature_match(
        target,
        candidate,
        active_harmonics=(1,),
        thresholds=thresholds,
    )

    assert result["metrics"]["global_phase_h1"] == pytest.approx(0.1)
    assert result["metrics"]["lockin_phase_h1"] == pytest.approx(0.1)
    assert result["metrics"]["lockin_valid_fraction"] == pytest.approx(0.5)
    assert result["passed"] is True


def test_git_provenance_decodes_nul_status_bytes(monkeypatch):
    import run_conditional_reachability as runner

    responses = iter(
        [
            SimpleNamespace(stdout="abc123\n"),
            SimpleNamespace(
                stdout=(
                    b" M code/a.py\0"
                    b"?? .wf_lock\0"
                    b"?? results/x.json\0"
                    b" M results/tracked.json\0"
                )
            ),
        ]
    )
    monkeypatch.setattr(runner.subprocess, "run", lambda *args, **kwargs: next(responses))

    result = runner._git_provenance()

    assert result["source_commit"] == "abc123"
    assert result["dirty"] is True
    assert result["dirty_paths"] == [
        "code/a.py",
        "results/tracked.json",
    ]
    assert result["ignored_workflow_paths"] == [
        ".wf_lock",
        "results/x.json",
    ]
    assert len(result["dirty_content_sha256"]) == 64


def test_target_artifact_serializes_invalid_lockin_region_as_null():
    import run_conditional_reachability as runner

    analysis = {"meta": {"f": 1.0}}
    target = {
        "e_grid": np.array([1.0, 1.1]),
        "dc": np.array([0.0, 1.0]),
        "complex_harmonics": {
            "amplitude": np.array([1.0]),
            "phase": np.array([0.0]),
            "snr": np.array([10.0]),
        },
        "lockin": {
            "amplitude": [np.array([1.0, np.nan])],
            "phase": [np.array([0.0, np.nan])],
            "valid_mask": np.array([True, False]),
            "fc_used": 1.0,
            "effective_resolution_v": 0.05,
        },
    }

    artifact = runner._target_artifact(analysis, target, (1,))
    encoded = json.dumps(runner._serialize(artifact), allow_nan=False)

    assert json.loads(encoded)["lockin"]["amplitude"][0] == [1.0, None]


def test_frozen_run_spec_binds_job_hash_to_source_state():
    from run_conditional_reachability import (
        _freeze_run_spec,
        build_job_plan,
        load_spec,
    )

    spec = load_spec(SPEC)
    first = _freeze_run_spec(
        spec,
        smoke=True,
        provenance={
            "source_commit": "a" * 40,
            "dirty": True,
            "dirty_paths": ["code/a.py"],
            "dirty_content_sha256": "1" * 64,
        },
    )
    second = _freeze_run_spec(
        spec,
        smoke=True,
        provenance={
            "source_commit": "a" * 40,
            "dirty": True,
            "dirty_paths": ["code/a.py"],
            "dirty_content_sha256": "2" * 64,
        },
    )

    first_job = build_job_plan(first, smoke=True)["base_jobs"][0]
    second_job = build_job_plan(second, smoke=True)["base_jobs"][0]
    assert first_job["job_input_hash"] != second_job["job_input_hash"]


def test_steady_state_failure_is_recorded_as_numerical_initialization():
    from run_conditional_reachability import _classify_exception

    assert _classify_exception(
        RuntimeError("steady-state RHS infinity norm is 1e-5")
    ) == "ODE_INITIALIZATION"
    assert _classify_exception(
        ValueError("target shape mismatch")
    ) == "FEATURE_OR_CONTRACT"


def test_evaluate_job_records_steady_state_provenance(monkeypatch):
    import run_conditional_reachability as runner

    config = SimpleNamespace(param_specs=())
    attempt = SimpleNamespace(
        elapsed_s=50.0,
        rhs_norm=2e-10,
        success=True,
        message="relaxed",
        nfev=21,
    )
    solution = SimpleNamespace(
        i_total=np.array([0.0, 1.0]),
        attempts=(),
        backend_used="LSODA",
        fallback_used=False,
        steady_state_elapsed_s=50.0,
        steady_state_rhs_norm=2e-10,
        steady_state_attempts=(attempt,),
    )
    monkeypatch.setattr(runner, "params_from_vector", lambda *args: {})
    monkeypatch.setattr(
        runner.OERPhysics,
        "solve_ode_system_detailed",
        lambda params: solution,
    )
    monkeypatch.setattr(runner, "extract_features", lambda *args: {"x": 1})
    monkeypatch.setattr(
        runner,
        "compute_feature_match",
        lambda *args, **kwargs: {
            "metrics": {},
            "global_score": 0.0,
            "global_passed": True,
            "lockin_score": 0.0,
            "lockin_passed": True,
            "score": 0.0,
            "passed": True,
            "limiting_metrics": [],
        },
    )
    payload = {
        "job": {
            "job_id": "base:FT2:000000",
            "encoded_params": [],
        },
        "config": config,
        "target": {},
        "active_harmonics": (1,),
        "thresholds": {},
    }

    row = runner.evaluate_job(payload)

    assert row["steady_state_elapsed_s"] == 50.0
    assert row["steady_state_rhs_norm"] == pytest.approx(2e-10)
    assert row["steady_state_attempts"] == [
        {
            "elapsed_s": 50.0,
            "rhs_norm": 2e-10,
            "success": True,
            "message": "relaxed",
            "nfev": 21,
        }
    ]
