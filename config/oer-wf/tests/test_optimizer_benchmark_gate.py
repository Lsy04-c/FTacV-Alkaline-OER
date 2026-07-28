"""Independent verification tests for the A6 optimizer benchmark."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import oer_wf.config as workflow_config
from oer_wf.commands.verify import run_verify
from oer_wf.validators import optimizer_benchmark_gate


GATE_CONFIG = {
    "gate_version": 1,
    "phase": "development",
    "optimizers": ["tpe", "sobol_pattern", "de_fixed"],
    "parameter_pairs": [
        ["k0_2", "k0_3"],
        ["k0_2", "G_O"],
        ["k0_3", "G_O"],
    ],
    "truth_id": "center",
    "noise_fraction": 0.0,
    "seed": 7,
    "optimization_budget": 100,
    "max_parameter_error": 0.05,
    "require_zero_ode_failures": True,
    "require_zero_boundary_hits": True,
}


def _write_archive(
    path: Path,
    *,
    sobol_errors=(0.01, 0.02, 0.03),
    de_errors=(0.02, 0.03, 0.04),
) -> None:
    path.mkdir(parents=True)
    pairs = [tuple(pair) for pair in GATE_CONFIG["parameter_pairs"]]
    errors = {
        "tpe": (0.10, 0.10, 0.10),
        "sobol_pattern": sobol_errors,
        "de_fixed": de_errors,
    }
    rows = []
    evaluations = []
    for pair_index, pair in enumerate(pairs):
        for optimizer in GATE_CONFIG["optimizers"]:
            job_id = f"{'-'.join(pair)}__{optimizer}"
            error = errors[optimizer][pair_index]
            metrics = {
                name: {
                    "normalized_bound_error": error,
                    "boundary_hit": False,
                }
                for name in pair
            }
            metrics["boundary_hits"] = []
            metrics["max_normalized_bound_error"] = error
            rows.append(
                {
                    "job_id": job_id,
                    "optimizer": optimizer,
                    "free_parameters": list(pair),
                    "truth_id": "center",
                    "noise_fraction": 0.0,
                    "seed": 7,
                    "budget": 100,
                    "success": True,
                    "optimization_calls": 100,
                    "diagnostic_truth_calls": 1,
                    "truth_diagnostic_sequence": 101,
                    "n_ode_fail": 0,
                    "best_objective": 0.01 + error,
                    "truth_objective": 0.01,
                    "parameter_metrics": metrics,
                }
            )
            evaluations.extend(
                {
                    "job_id": job_id,
                    "sequence": index,
                    "kind": "optimization",
                    "index": index,
                    "unit": [0.5, 0.5],
                    "loss": 0.01,
                    "error": None,
                }
                for index in range(1, 101)
            )
    selection = optimizer_benchmark_gate.recompute_selection(
        rows,
        GATE_CONFIG,
    )
    summary = {
        "execution_passed": True,
        "scientific_gate_passed": selection[
            "scientific_gate_passed"
        ],
        "job_count": 9,
        "completed_jobs": 9,
        "optimization_calls": 900,
        "diagnostic_truth_calls": 9,
        "n_ode_fail": 0,
        "is_smoke": False,
    }
    (path / "results.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows)
    )
    (path / "evaluations.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in evaluations)
    )
    (path / "summary.json").write_text(json.dumps(summary))
    (path / "selection.json").write_text(json.dumps(selection))


def _failed_names(checks):
    return [check.name for check in checks if not check.passed]


def test_gate_passes_one_eligible_replacement(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    _write_archive(
        archive,
        de_errors=(0.01, 0.02, 0.051),
    )

    checks = optimizer_benchmark_gate.run(
        archive,
        validator_config=GATE_CONFIG,
    )

    assert _failed_names(checks) == []
    assert any(
        check.name == "scientific:optimizer_benchmark_gate"
        and check.passed
        for check in checks
    )


def test_gate_fails_when_both_replacements_miss_one_pair(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "archive"
    _write_archive(
        archive,
        sobol_errors=(0.051, 0.02, 0.03),
        de_errors=(0.01, 0.051, 0.03),
    )

    checks = optimizer_benchmark_gate.run(
        archive,
        validator_config=GATE_CONFIG,
    )

    assert _failed_names(checks) == [
        "scientific:optimizer_benchmark_gate"
    ]


@pytest.mark.parametrize("count", [99, 101])
def test_gate_rejects_99_or_101_calls_as_structure_failure(
    tmp_path: Path,
    count: int,
) -> None:
    archive = tmp_path / "archive"
    _write_archive(archive)
    rows = [
        json.loads(line)
        for line in (archive / "results.jsonl").read_text().splitlines()
    ]
    rows[0]["optimization_calls"] = count
    (archive / "results.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows)
    )

    checks = optimizer_benchmark_gate.run(
        archive,
        validator_config=GATE_CONFIG,
    )

    assert "structure:optimizer_benchmark_gate" in _failed_names(checks)


def test_gate_rejects_truth_diagnostic_before_last_optimization_call(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "archive"
    _write_archive(archive)
    rows = [
        json.loads(line)
        for line in (archive / "results.jsonl").read_text().splitlines()
    ]
    rows[0]["truth_diagnostic_sequence"] = 99
    (archive / "results.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows)
    )

    checks = optimizer_benchmark_gate.run(
        archive,
        validator_config=GATE_CONFIG,
    )

    assert "structure:optimizer_benchmark_gate" in _failed_names(checks)


def test_gate_rejects_threshold_drift(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    _write_archive(archive)
    drifted = {**GATE_CONFIG, "max_parameter_error": 0.051}

    checks = optimizer_benchmark_gate.run(
        archive,
        validator_config=drifted,
    )

    assert _failed_names(checks) == [
        "structure:optimizer_benchmark_gate_config"
    ]


def test_verify_classifies_selection_failure_as_scientific(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "archive"
    monkeypatch.setattr(workflow_config, "MAC_ARCHIVE_ROOT", root)
    archive = (
        root
        / "results"
        / "abcdef1"
        / "a6_optimizer_development_cn"
        / "ts1"
    )
    _write_archive(
        archive,
        sobol_errors=(0.051, 0.02, 0.03),
        de_errors=(0.01, 0.051, 0.03),
    )
    (archive / "STATUS.json").write_text('{"status":"SUCCESS"}')
    snapshot = {
        "task_name": "a6_optimizer_development_cn",
        "commit": "abcdef1234567890",
        "script": "code/python/scripts/run_optimizer_benchmark.py",
        "output_dir": "results/a6_optimizer_development_cn",
        "expected_files": [
            "summary.json",
            "results.jsonl",
            "evaluations.jsonl",
            "selection.json",
            "STATUS.json",
        ],
        "validators": ["optimizer_benchmark_gate"],
        "validator_config": {
            "optimizer_benchmark_gate": GATE_CONFIG,
        },
    }
    (archive / "task_spec.snapshot.yaml").write_text(
        yaml.safe_dump(snapshot)
    )

    response = run_verify("abcdef1/a6_optimizer_development_cn")

    assert response.fail_type.value == "scientific"
