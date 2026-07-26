"""Tests for the Gate A6 recovery runner configuration."""

import pytest

from scripts.run_synthetic_recovery import (
    build_config,
    build_jobs,
    parse_args,
    run_job,
    main,
    validate_noise_evidence,
)


def test_formal_runner_matches_frozen_a5_grid(tmp_path):
    args = parse_args(
        [
            "--phase",
            "pilot",
            "--noise-fraction",
            "0.0015",
            "--output",
            str(tmp_path / "pilot"),
        ]
    )
    config = build_config(args, feature_mode="hybrid", seed=17)

    assert config.n_points == 8192
    assert config.points_per_cycle == 32
    assert config.feature_grid_size == 128
    assert config.solver_backend == "lsoda"
    assert config.feature_mode == "hybrid"


def test_smoke_runner_uses_small_simulation_grid(tmp_path):
    args = parse_args(
        [
            "--phase",
            "pilot",
            "--noise-fraction",
            "0.0015",
            "--output",
            str(tmp_path / "smoke"),
            "--smoke",
        ]
    )
    config = build_config(args, feature_mode="legacy", seed=7)

    assert config.n_points == 256
    assert config.points_per_cycle == 32
    assert config.feature_grid_size == 128


def test_pilot_builds_36_budget_jobs(tmp_path):
    args = parse_args(
        [
            "--phase",
            "pilot",
            "--noise-fraction",
            "0.0015",
            "--output",
            str(tmp_path / "pilot"),
        ]
    )

    jobs = build_jobs(args)

    assert len(jobs) == 36
    assert {job["trials"] for job in jobs} == {20, 50, 100}


def test_formal_builds_72_jobs_at_selected_budget(tmp_path):
    args = parse_args(
        [
            "--phase",
            "formal",
            "--noise-fraction",
            "0.0015",
            "--trials",
            "50",
            "--output",
            str(tmp_path / "formal"),
        ]
    )

    jobs = build_jobs(args)

    assert len(jobs) == 72
    assert {job["trials"] for job in jobs} == {50}


def test_formal_requires_selected_trial_budget(tmp_path):
    args = parse_args(
        [
            "--phase",
            "formal",
            "--noise-fraction",
            "0.0015",
            "--output",
            str(tmp_path / "formal"),
        ]
    )

    with pytest.raises(ValueError, match="--trials"):
        build_jobs(args)


def test_smoke_job_runs_without_truth_initialization(tmp_path):
    args = parse_args(
        [
            "--phase",
            "formal",
            "--noise-fraction",
            "0.0015",
            "--trials",
            "2",
            "--output",
            str(tmp_path / "formal"),
            "--smoke",
        ]
    )
    job = build_jobs(args)[0]

    row = run_job(job, smoke=True)

    assert row["success"] is True
    assert row["n_trials"] == 2
    assert row["job_id"] == job["job_id"]
    assert set(row["parameter_metrics"]) == {
        "k0_1",
        "k0_2",
        "k0_3",
        "k0_4",
        "G_OH",
        "G_O",
        "scaling_OOH_OH",
        "gamma",
        "boundary_hits",
        "max_normalized_bound_error",
    }


def test_dry_run_writes_job_plan_without_computation(tmp_path):
    output = tmp_path / "pilot"

    main(
        [
            "--phase",
            "pilot",
            "--noise-fraction",
            "0.0015",
            "--output",
            str(output),
            "--dry-run",
        ]
    )

    assert (output / "job_plan.json").is_file()
    assert not (output / "results.jsonl").exists()


def test_smoke_main_checkpoints_one_completed_job(tmp_path):
    output = tmp_path / "smoke"

    main(
        [
            "--phase",
            "formal",
            "--noise-fraction",
            "0.0015",
            "--trials",
            "1",
            "--output",
            str(output),
            "--workers",
            "1",
            "--smoke",
            "--max-jobs",
            "1",
        ]
    )

    assert len((output / "results.jsonl").read_text().splitlines()) == 1
    assert (output / "summary.json").is_file()


def test_formal_noise_must_match_evidence_file(tmp_path):
    evidence = tmp_path / "noise.json"
    evidence.write_text('{"selected_noise_fraction": 0.0015}')

    validate_noise_evidence(0.0015, evidence)

    with pytest.raises(ValueError, match="does not match"):
        validate_noise_evidence(0.002, evidence)
