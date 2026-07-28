"""Tests for the Gate A6 recovery runner configuration."""

import hashlib
import json
import math

import pytest
import yaml

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
    validate_backend,
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


def test_parse_args_defaults_to_lsoda_backend(tmp_path):
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

    assert args.backend == "lsoda"


def test_explicit_cn_backend_is_preserved_in_config_and_jobs(tmp_path):
    args = parse_args(
        [
            "--phase",
            "pilot",
            "--noise-fraction",
            "0.0015",
            "--output",
            str(tmp_path / "pilot"),
            "--backend",
            "cn",
        ]
    )

    config = build_config(args, feature_mode="hybrid", seed=17)
    jobs = build_jobs(args)

    assert config.solver_backend == "cn"
    assert {job["backend"] for job in jobs} == {"cn"}


def test_validate_backend_rejects_cn_when_cpp_bridge_unavailable(monkeypatch):
    from oer_aem import cpp_bridge

    monkeypatch.setattr(cpp_bridge, "is_available", lambda: False)

    with pytest.raises(
        RuntimeError,
        match="CN backend requested but unavailable; fallback is forbidden",
    ):
        validate_backend("cn")


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


def test_parse_args_accepts_explicit_resume(tmp_path):
    args = parse_args(
        [
            "--phase",
            "pilot",
            "--noise-fraction",
            "0.0015",
            "--output",
            str(tmp_path),
            "--resume",
        ]
    )

    assert args.resume is True


def test_resume_directory_rejects_results_without_plan(tmp_path):
    (tmp_path / "results.jsonl").write_text("{}\n")

    with pytest.raises(ValueError, match="job_plan"):
        prepare_output_directory(tmp_path, resume=True)


def test_resume_directory_allows_new_or_planned_output(tmp_path):
    new_output = tmp_path / "new"
    prepare_output_directory(new_output, resume=True)
    assert new_output.is_dir()

    planned = tmp_path / "planned"
    planned.mkdir()
    (planned / "job_plan.json").write_text("{}\n")
    (planned / "results.jsonl").write_text("")
    prepare_output_directory(planned, resume=True)


def _checkpoint_row(job, job_hash):
    return {
        **job,
        "job_input_hash": job_hash,
        "success": True,
        "best_value": 0.25,
        "best_params": {"k0_1": 1.0},
        "parameter_metrics": {"k0_1": {"relative_error": 0.0}},
        "n_trials": job["trials"],
        "n_forward": job["trials"],
        "n_ode_fail": 0,
        "n_tafel_fail": 0,
        "runtime_seconds": 0.1,
        "configuration": {
            "n_points": 256,
            "points_per_cycle": 32,
            "feature_grid_size": 128,
            "solver_backend": "lsoda",
        },
    }


def test_checkpoint_loader_rejects_missing_hash_duplicate_and_nonfinite(tmp_path):
    jobs = [{"job_id": "a"}, {"job_id": "b"}]
    expected = {"a": "ha", "b": "hb"}
    path = tmp_path / "results.jsonl"

    path.write_text('{"job_id":"a"}\n')
    with pytest.raises(ValueError, match="job_input_hash"):
        recovery_runner.load_checkpoint_rows(path, expected)

    row = {"job_id": "a", "job_input_hash": "ha", "best_value": 1.0}
    path.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="duplicate"):
        recovery_runner.load_checkpoint_rows(path, expected)

    row["best_value"] = math.inf
    path.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="non-finite"):
        recovery_runner.load_checkpoint_rows(path, expected)


def test_atomic_checkpoint_preserves_planned_order(tmp_path):
    path = tmp_path / "results.jsonl"
    rows = {
        "b": {"job_id": "b", "job_input_hash": "hb"},
        "a": {"job_id": "a", "job_input_hash": "ha"},
    }

    recovery_runner.atomic_write_checkpoint(path, rows, ["a", "b"])

    loaded = [json.loads(line) for line in path.read_text().splitlines()]
    assert [row["job_id"] for row in loaded] == ["a", "b"]


def test_iter_job_results_accepts_empty_job_list():
    assert list(recovery_runner.iter_job_results([], workers=8, smoke=True)) == []


def test_resume_after_interruption_runs_only_missing_jobs(
    monkeypatch, tmp_path
):
    output = tmp_path / "resume"
    provenance = {
        "source_commit": "deadbeef",
        "dirty": False,
        "dirty_paths": [],
        "ignored_workflow_paths": [],
    }
    monkeypatch.setattr(recovery_runner, "git_state_full", lambda: provenance)
    monkeypatch.setattr(recovery_runner, "summarize_recovery", lambda *a, **k: {})
    monkeypatch.setattr(recovery_runner, "select_trial_budget", lambda rows: {})

    calls = []
    fail_once = {"value": True}

    def interrupted(jobs, **kwargs):
        for index, job in enumerate(jobs):
            calls.append(job["job_id"])
            if index == 1 and fail_once["value"]:
                fail_once["value"] = False
                raise RuntimeError("simulated interruption")
            yield _checkpoint_row(job, job["job_input_hash"])

    monkeypatch.setattr(recovery_runner, "iter_job_results", interrupted)
    common = [
        "--phase",
        "pilot",
        "--noise-fraction",
        "0.0015",
        "--output",
        str(output),
        "--workers",
        "1",
        "--smoke",
        "--max-jobs",
        "3",
    ]

    with pytest.raises(RuntimeError, match="simulated"):
        main(common)

    first_rows = [
        json.loads(line) for line in (output / "results.jsonl").read_text().splitlines()
    ]
    assert len(first_rows) == 1
    first_job_id = first_rows[0]["job_id"]

    calls.clear()
    main([*common, "--resume"])

    assert first_job_id not in calls
    assert len(calls) == 2
    summary = json.loads((output / "summary.json").read_text())
    assert summary["completed_jobs"] == 3
    assert summary["reused_jobs"] == 1
    assert summary["executed_jobs"] == 2
    assert summary["resumed"] is True

    calls.clear()
    main([*common, "--resume"])
    assert calls == []


def test_resume_rejects_changed_scientific_configuration(monkeypatch, tmp_path):
    output = tmp_path / "resume"
    provenance = {
        "source_commit": "deadbeef",
        "dirty": False,
        "dirty_paths": [],
        "ignored_workflow_paths": [],
    }
    monkeypatch.setattr(recovery_runner, "git_state_full", lambda: provenance)
    monkeypatch.setattr(recovery_runner, "summarize_recovery", lambda *a, **k: {})
    monkeypatch.setattr(recovery_runner, "select_trial_budget", lambda rows: {})
    monkeypatch.setattr(
        recovery_runner,
        "iter_job_results",
        lambda jobs, **kwargs: iter(
            [_checkpoint_row(job, job["job_input_hash"]) for job in jobs]
        ),
    )
    common = [
        "--phase",
        "pilot",
        "--noise-fraction",
        "0.0015",
        "--output",
        str(output),
        "--smoke",
        "--max-jobs",
        "1",
    ]
    main(common)

    with pytest.raises(ValueError, match="fingerprint"):
        main(
            [
                "--phase",
                "pilot",
                "--noise-fraction",
                "0.002",
                "--output",
                str(output),
                "--smoke",
                "--max-jobs",
                "1",
                "--resume",
            ]
        )


def test_resume_rejects_legacy_v1_plan_before_fingerprint(monkeypatch, tmp_path):
    output = tmp_path / "resume"
    output.mkdir()
    (output / "job_plan.json").write_text(
        json.dumps(
            {
                "resume_schema_version": 1,
                "resume_fingerprint": "legacy",
                "jobs": [],
            }
        )
        + "\n"
    )
    provenance = {
        "source_commit": "deadbeef",
        "dirty": False,
        "dirty_paths": [],
        "ignored_workflow_paths": [],
    }
    monkeypatch.setattr(recovery_runner, "git_state_full", lambda: provenance)
    monkeypatch.setattr(recovery_runner, "summarize_recovery", lambda *a, **k: {})
    monkeypatch.setattr(recovery_runner, "select_trial_budget", lambda rows: {})

    with pytest.raises(ValueError, match="resume schema version mismatch"):
        main(
            [
                "--phase",
                "pilot",
                "--noise-fraction",
                "0.0015",
                "--output",
                str(output),
                "--smoke",
                "--max-jobs",
                "1",
                "--resume",
            ]
        )


def test_main_writes_resume_schema_version_two(monkeypatch, tmp_path):
    output = tmp_path / "schema"
    provenance = {
        "source_commit": "deadbeef",
        "dirty": False,
        "dirty_paths": [],
        "ignored_workflow_paths": [],
    }
    monkeypatch.setattr(recovery_runner, "git_state_full", lambda: provenance)
    monkeypatch.setattr(recovery_runner, "summarize_recovery", lambda *a, **k: {})
    monkeypatch.setattr(recovery_runner, "select_trial_budget", lambda rows: {})
    monkeypatch.setattr(
        recovery_runner,
        "iter_job_results",
        lambda jobs, **kwargs: iter(
            [_checkpoint_row(job, job["job_input_hash"]) for job in jobs]
        ),
    )

    main(
        [
            "--phase",
            "pilot",
            "--noise-fraction",
            "0.0015",
            "--output",
            str(output),
            "--smoke",
            "--max-jobs",
            "1",
        ]
    )

    plan = json.loads((output / "job_plan.json").read_text())
    assert plan["resume_schema_version"] == 2


def test_a6_workflow_enables_resume_and_eight_workers():
    spec_path = (
        recovery_runner.ROOT
        / "config"
        / "oer-wf"
        / "examples"
        / "a6_recovery_reduced.yaml"
    )
    spec = yaml.safe_load(spec_path.read_text())

    assert spec["supports_resume"] is True
    assert spec["workers"] == 8
    assert spec["smoke"]["overrides"] == {"trials": 5, "max_jobs": 1}


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


@pytest.mark.parametrize(
    ("raw_status", "dirty", "dirty_paths", "ignored_paths"),
    [
        ("", False, [], []),
        ("?? .wf_lock\0", False, [], [".wf_lock"]),
        (
            "?? results/a6/output.json\0",
            False,
            [],
            ["results/a6/output.json"],
        ),
        (
            "?? .wf_lock\0?? results/a6/output.json\0",
            False,
            [],
            [".wf_lock", "results/a6/output.json"],
        ),
        (
            " M results/formal/evidence.json\0",
            True,
            ["results/formal/evidence.json"],
            [],
        ),
        (
            "M  results/formal/evidence.json\0",
            True,
            ["results/formal/evidence.json"],
            [],
        ),
        (
            "?? code/python/new script.py\0",
            True,
            ["code/python/new script.py"],
            [],
        ),
        ("?? .wf_lock.py\0", True, [".wf_lock.py"], []),
        ("?? results.py\0", True, ["results.py"], []),
        (
            "R  results/old.py\0code/old.py\0",
            True,
            ["code/old.py -> results/old.py"],
            [],
        ),
    ],
)
def test_classify_git_status_porcelain_z(
    raw_status, dirty, dirty_paths, ignored_paths
):
    classified = recovery_runner.classify_git_status(raw_status)

    assert classified == {
        "dirty": dirty,
        "dirty_paths": dirty_paths,
        "ignored_workflow_paths": ignored_paths,
    }


def test_main_writes_consistent_structured_provenance(monkeypatch, tmp_path):
    output = tmp_path / "smoke"
    provenance = {
        "source_commit": "deadbeef",
        "dirty": False,
        "dirty_paths": [],
        "ignored_workflow_paths": [".wf_lock", "results/a6/"],
    }
    monkeypatch.setattr(
        recovery_runner, "git_state_full", lambda: provenance, raising=False
    )
    monkeypatch.setattr(
        recovery_runner,
        "iter_job_results",
        lambda jobs, **kwargs: iter(
            [
                {
                    **jobs[0],
                    "success": True,
                    "n_ode_fail": 0,
                    "n_tafel_fail": 0,
                }
            ]
        ),
    )
    monkeypatch.setattr(
        recovery_runner,
        "summarize_recovery",
        lambda rows, parameter_names: {},
    )

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

    plan = json.loads((output / "job_plan.json").read_text())
    summary = json.loads((output / "summary.json").read_text())

    assert plan["provenance"] == summary["provenance"]
    assert summary["source_commit"] == plan["provenance"]["source_commit"]
    assert summary["dirty"] == plan["provenance"]["dirty"]
    assert summary["execution_passed"] is True
    assert summary["scientific_gate_passed"] is None
    assert summary["passed"] == summary["execution_passed"]
    assert summary["passed_semantics"] == "deprecated alias of execution_passed"
    assert plan["provenance"]["source_commit"] == "deadbeef"
    assert plan["provenance"]["ignored_workflow_paths"] == [
        ".wf_lock",
        "results/a6/",
    ]
    assert plan["provenance"]["python"]
    assert plan["provenance"]["command"]
