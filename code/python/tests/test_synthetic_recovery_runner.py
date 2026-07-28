"""Tests for the Gate A6 recovery runner configuration."""

import hashlib

import pytest

from scripts import run_synthetic_recovery as recovery_runner
from scripts.run_synthetic_recovery import (
    WORKFLOW_OWNED_FILES,
    build_config,
    build_jobs,
    limit_jobs,
    parse_args,
    prepare_output_directory,
    run_job,
    main,
    validate_noise_evidence,
)

REDUCED_FREE_PARAMETERS = ("k0_1", "k0_2", "k0_3", "G_OH", "G_O")


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


def test_reduced_runner_fixes_complement_to_each_synthetic_truth(tmp_path):
    args = parse_args(
        [
            "--phase",
            "pilot",
            "--noise-fraction",
            "0.0015",
            "--free-parameters",
            ",".join(REDUCED_FREE_PARAMETERS),
            "--output",
            str(tmp_path / "pilot"),
        ]
    )
    job = build_jobs(args)[0]

    config, free_specs = recovery_runner.build_recovery_problem(job, smoke=True)

    assert tuple(name for name, *_ in free_specs) == REDUCED_FREE_PARAMETERS
    assert dict(config.fixed_params) == {
        name: value
        for name, value in job["truth_params"].items()
        if name not in REDUCED_FREE_PARAMETERS
    }
    assert job["free_parameters"] == list(REDUCED_FREE_PARAMETERS)


def test_reduced_runner_rejects_unknown_or_duplicate_parameters(tmp_path):
    common = [
        "--phase",
        "pilot",
        "--noise-fraction",
        "0.0015",
        "--output",
        str(tmp_path / "pilot"),
    ]

    with pytest.raises(ValueError, match="unknown free parameter"):
        build_jobs(parse_args([*common, "--free-parameters", "k0_1,unknown"]))

    with pytest.raises(ValueError, match="duplicate free parameter"):
        build_jobs(parse_args([*common, "--free-parameters", "k0_1,k0_1"]))


def test_reduced_runner_does_not_initialize_optimizer_from_truth(tmp_path):
    args = parse_args(
        [
            "--phase",
            "pilot",
            "--noise-fraction",
            "0.0015",
            "--free-parameters",
            ",".join(REDUCED_FREE_PARAMETERS),
            "--output",
            str(tmp_path / "pilot"),
        ]
    )
    job = build_jobs(args)[0]
    config, free_specs = recovery_runner.build_recovery_problem(job, smoke=True)

    inverter = recovery_runner.build_inverter(job, config, free_specs)

    assert inverter.initial_params is None


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


def test_limit_jobs_applies_positive_limit_without_mutating_input():
    jobs = [{"job_id": "a"}, {"job_id": "b"}]

    limited = limit_jobs(jobs, 1)

    assert limited == [{"job_id": "a"}]
    assert jobs == [{"job_id": "a"}, {"job_id": "b"}]


@pytest.mark.parametrize("max_jobs", [0, -1])
def test_limit_jobs_rejects_non_positive_limit(max_jobs):
    with pytest.raises(ValueError, match="positive"):
        limit_jobs([{"job_id": "a"}], max_jobs)


def test_prepare_output_directory_allows_workflow_files(tmp_path):
    output = tmp_path / "run"
    output.mkdir()
    for name in WORKFLOW_OWNED_FILES:
        (output / name).write_text("{}")
    (output / "STATUS.json.tmp.123").write_text("{}")

    prepare_output_directory(output)

    assert {path.name for path in output.iterdir()} == {
        *WORKFLOW_OWNED_FILES,
        "STATUS.json.tmp.123",
    }


def test_prepare_output_directory_rejects_existing_scientific_output(tmp_path):
    output = tmp_path / "run"
    output.mkdir()
    result = output / "results.jsonl"
    result.write_text('{"kept": true}\n')

    with pytest.raises(FileExistsError, match="scientific"):
        prepare_output_directory(output)

    assert result.read_text() == '{"kept": true}\n'


def test_formal_noise_must_match_evidence_file(tmp_path):
    evidence = tmp_path / "noise.json"
    raw = b'{"selected_noise_fraction": 0.0015, "limitation": "pilot"}'
    evidence.write_bytes(raw)

    validated = validate_noise_evidence(0.0015, evidence)

    assert validated["limitation"] == "pilot"
    assert validated["resolved_path"] == str(evidence.resolve())
    assert validated["sha256"] == hashlib.sha256(raw).hexdigest()

    with pytest.raises(ValueError, match="does not match"):
        validate_noise_evidence(0.002, evidence)


def test_formal_noise_rejects_corrupt_json(tmp_path):
    evidence = tmp_path / "noise.json"
    evidence.write_text("{not-json")

    with pytest.raises(ValueError, match="valid JSON"):
        validate_noise_evidence(0.0015, evidence)
