"""Unit tests for wf verify."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from oer_wf.commands.verify import run_verify
from oer_wf.lock import spec_hash
from oer_wf.models import StatusEnum, TaskSpec
import oer_wf.config as cfg


def test_verify_missing_archive(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cfg, "MAC_ARCHIVE_ROOT", tmp_path / "archive")
    resp = run_verify("3f9aad1/solver_equiv_01")
    assert resp.status == StatusEnum.FAIL
    assert "sync" in resp.next_action


def test_verify_contract_unavailable_without_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "archive"
    monkeypatch.setattr(cfg, "MAC_ARCHIVE_ROOT", root)
    arch = root / "results" / "3f9aad1" / "solver_equiv_01" / "20260727_120000"
    arch.mkdir(parents=True)
    (arch / "STATUS.json").write_text("{}")
    (arch / "summary.csv").write_text("a,b\n1,2\n")
    (arch / "manifest.json").write_text("{}")

    resp = run_verify("3f9aad1/solver_equiv_01")

    assert resp.status == StatusEnum.FAIL
    assert resp.fail_type.value == "structure"
    assert any("contract" in c.name for c in resp.checks)


def test_verify_pass_with_snapshot(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "archive"
    monkeypatch.setattr(cfg, "MAC_ARCHIVE_ROOT", root)
    arch = root / "results" / "3f9aad1" / "solver_equiv_01" / "20260727_120000"
    arch.mkdir(parents=True)
    (arch / "STATUS.json").write_text(
        json.dumps(
            {
                "status": "SUCCESS",
                "commit": "3f9aad1",
                "task_id": "3f9aad1/solver_equiv_01",
                "started_at": "2026-07-27T09:00:00Z",
                "exit_code": 0,
            }
        )
    )
    (arch / "summary.csv").write_text("a,b\n1.0,2.0\n")
    (arch / "manifest.json").write_text(json.dumps({"commit": "3f9aad1", "files": {}}))
    snapshot = {
        "task_name": "solver_equiv_01",
        "commit": "3f9aad1abcdef",
        "script": "scripts/run.py",
        "output_dir": "results/solver_equiv_01",
        "expected_files": ["summary.csv", "manifest.json", "STATUS.json"],
        "validators": ["schema_check", "finite_check", "provenance"],
    }
    (arch / "task_spec.snapshot.yaml").write_text(yaml.safe_dump(snapshot))

    resp = run_verify("3f9aad1/solver_equiv_01")
    assert resp.status == StatusEnum.PASS
    assert any(c.name.startswith("file:") and c.passed for c in resp.checks)
    assert resp.data["contract_sources"]["expected_files"] == "snapshot"


def test_verify_nan_fails(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "archive"
    monkeypatch.setattr(cfg, "MAC_ARCHIVE_ROOT", root)
    arch = root / "results" / "3f9aad1" / "solver_equiv_01" / "20260727_120000"
    arch.mkdir(parents=True)
    (arch / "STATUS.json").write_text(
        json.dumps(
            {
                "status": "SUCCESS",
                "commit": "3f9aad1",
                "task_id": "3f9aad1/solver_equiv_01",
                "started_at": "2026-07-27T09:00:00Z",
            }
        )
    )
    (arch / "summary.csv").write_text("a,b\n1.0,nan\n")
    (arch / "manifest.json").write_text("{}")
    snapshot = {
        "task_name": "solver_equiv_01",
        "commit": "3f9aad1",
        "script": "scripts/run.py",
        "output_dir": "results/solver_equiv_01",
        "expected_files": ["summary.csv", "manifest.json", "STATUS.json"],
        "validators": ["schema_check", "finite_check"],
    }
    (arch / "task_spec.snapshot.yaml").write_text(yaml.safe_dump(snapshot))

    resp = run_verify("3f9aad1/solver_equiv_01")
    assert resp.status == StatusEnum.FAIL
    assert resp.fail_type.value == "numerical"


def test_spec_hash_stable_without_validator_config() -> None:
    base = {
        "task_name": "t",
        "commit": "abcdef1",
        "script": "scripts/x.py",
        "output_dir": "results/t",
    }
    without_field = TaskSpec.model_validate(base)
    explicit_none = TaskSpec.model_validate({**base, "validator_config": None})
    assert spec_hash(without_field) == spec_hash(explicit_none)


def test_recovery_gate_scientific_failure(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "archive"
    monkeypatch.setattr(cfg, "MAC_ARCHIVE_ROOT", root)
    arch = root / "results" / "a7bc9e4" / "a6_recovery_reduced" / "ts1"
    arch.mkdir(parents=True)
    row = {"job_id": "job-1", "success": True}
    group = {
        "all_success": True,
        "parameters": {
            name: {
                "truth_covered_by_seed_range": name != "G_O",
                "boundary_hit_rate": 0.0,
            }
            for name in ("k0_2", "k0_3", "G_O")
        },
    }
    summary = {
        "job_count": 1,
        "completed_jobs": 1,
        "recovery_summary": {"group_count": 1, "groups": [group]},
    }
    (arch / "summary.json").write_text(json.dumps(summary))
    (arch / "results.jsonl").write_text(json.dumps(row) + "\n")
    (arch / "STATUS.json").write_text('{"status":"SUCCESS"}')
    snapshot = {
        "task_name": "a6_recovery_reduced",
        "commit": "a7bc9e4deadbeef",
        "script": "code/python/scripts/run_synthetic_recovery.py",
        "output_dir": "results/a6_recovery_reduced",
        "expected_files": ["summary.json", "results.jsonl", "STATUS.json"],
        "validators": ["schema_check", "recovery_gate"],
        "validator_config": {
            "recovery_gate": {
                "parameter_names": ["k0_2", "k0_3", "G_O"],
                "require_all_studies_success": True,
                "require_truth_covered_by_seed_range": True,
                "max_boundary_hit_rate": 0.0,
            }
        },
    }
    (arch / "task_spec.snapshot.yaml").write_text(yaml.safe_dump(snapshot))

    resp = run_verify("a7bc9e4/a6_recovery_reduced")

    assert resp.status == StatusEnum.FAIL
    assert resp.fail_type.value == "scientific"
    assert any(c.name == "scientific:recovery_gate" for c in resp.checks)


def _arg_value(args: list[str], flag: str) -> str:
    idx = args.index(flag)
    return args[idx + 1]


@pytest.mark.parametrize(
    ("spec_name", "task_name", "output_dir", "description", "parameter_name"),
    [
        (
            "a6_recovery_cn_k0_2.yaml",
            "a6_recovery_cn_k0_2",
            "results/a6_recovery_cn_k0_2",
            "Gate A6 synthetic recovery: k0_2 (1 free param, CN backend)",
            "k0_2",
        ),
        (
            "a6_recovery_cn_k0_3.yaml",
            "a6_recovery_cn_k0_3",
            "results/a6_recovery_cn_k0_3",
            "Gate A6 synthetic recovery: k0_3 (1 free param, CN backend)",
            "k0_3",
        ),
        (
            "a6_recovery_cn_G_O.yaml",
            "a6_recovery_cn_G_O",
            "results/a6_recovery_cn_G_O",
            "Gate A6 synthetic recovery: G_O (1 free param, CN backend)",
            "G_O",
        ),
    ],
)
def test_cn_recovery_specs(tmp_path: Path, spec_name: str, task_name: str, output_dir: str, description: str, parameter_name: str) -> None:
    spec_path = Path(__file__).resolve().parents[1] / "examples" / spec_name
    spec = yaml.safe_load(spec_path.read_text())

    assert spec["task_name"] == task_name
    assert spec["commit"] == "d0defa75017191302b95269bc5cc701d48df652c"
    assert spec["output_dir"] == output_dir
    assert spec["description"] == description
    assert spec["workers"] == 8
    assert _arg_value(spec["args"], "--phase") == "formal"
    assert _arg_value(spec["args"], "--backend") == "cn"
    assert _arg_value(spec["args"], "--trials") == "100"
    assert _arg_value(spec["args"], "--free-parameters") == parameter_name
    assert _arg_value(spec["args"], "--noise-fraction") == "0.001495726085983469"
    assert _arg_value(spec["args"], "--noise-evidence") == "results/formal/identifiability/gate-a6-d9299f8/noise_evidence.json"
    assert spec["smoke"]["overrides"] == {"trials": 5, "max_jobs": 1}
    assert spec["smoke"]["expected_files"] == [
        "summary.json",
        "job_plan.json",
        "results.jsonl",
        "STATUS.json",
    ]
    assert spec["expected_files"] == [
        "summary.json",
        "job_plan.json",
        "results.jsonl",
        "STATUS.json",
    ]
    assert spec["validators"] == ["schema_check", "finite_check", "provenance", "recovery_gate"]
    assert spec["validator_config"]["recovery_gate"]["parameter_names"] == [parameter_name]


@pytest.mark.parametrize(
    ("spec_name", "task_name", "parameters"),
    [
        (
            "a6_recovery_cn_k0_2_k0_3.yaml",
            "a6_recovery_cn_k0_2_k0_3",
            ["k0_2", "k0_3"],
        ),
        (
            "a6_recovery_cn_k0_2_G_O.yaml",
            "a6_recovery_cn_k0_2_G_O",
            ["k0_2", "G_O"],
        ),
        (
            "a6_recovery_cn_k0_3_G_O.yaml",
            "a6_recovery_cn_k0_3_G_O",
            ["k0_3", "G_O"],
        ),
    ],
)
def test_stage2_cn_recovery_specs(
    spec_name: str,
    task_name: str,
    parameters: list[str],
) -> None:
    spec_path = Path(__file__).resolve().parents[1] / "examples" / spec_name
    raw = yaml.safe_load(spec_path.read_text())
    model = TaskSpec.model_validate(raw)

    assert model.task_name == task_name
    assert model.commit == "732bf5de27a878192ab46abe76b08de66f3af29b"
    assert model.output_dir == f"results/{task_name}"
    assert model.workers == 8
    assert _arg_value(model.args, "--phase") == "formal"
    assert _arg_value(model.args, "--backend") == "cn"
    assert _arg_value(model.args, "--feature-modes") == "hybrid"
    assert _arg_value(model.args, "--free-parameters") == ",".join(parameters)
    assert _arg_value(model.args, "--trials") == "100"
    assert _arg_value(model.args, "--noise-fraction") == (
        "0.001495726085983469"
    )
    assert model.smoke.overrides == {"trials": 5, "max_jobs": 1}
    assert model.validators == [
        "schema_check",
        "finite_check",
        "provenance",
        "recovery_gate",
    ]
    gate = model.validator_config["recovery_gate"]
    assert gate == {
        "gate_version": 2,
        "parameter_names": parameters,
        "feature_modes": ["hybrid"],
        "truth_ids": ["center", "mixed_a", "mixed_b"],
        "noise_fractions": [0.0, 0.001495726085983469],
        "seeds": [7, 17, 27],
        "trials": 100,
        "require_all_studies_success": True,
        "max_boundary_hit_rate": 0.0,
        "max_median_normalized_bound_error": 0.025,
        "max_normalized_bound_error": 0.05,
        "max_seed_normalized_bound_dispersion": 0.05,
        "require_nonlegacy_mode": True,
        "legacy_mode": "legacy",
    }


def test_a6_optimizer_development_spec_is_frozen() -> None:
    spec_path = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "a6_optimizer_development_cn.yaml"
    )
    raw = yaml.safe_load(spec_path.read_text())
    model = TaskSpec.model_validate(raw)

    assert model.task_name == "a6_optimizer_development_cn"
    assert model.commit == "a5b93f55e540682cc8cddb1fabbe63a7e0e92326"
    assert model.script == "code/python/scripts/run_optimizer_benchmark.py"
    assert model.output_dir == "results/a6_optimizer_development_cn"
    assert model.workers == 8
    assert model.supports_resume is True
    assert _arg_value(model.args, "--phase") == "development"
    assert _arg_value(model.args, "--backend") == "cn"
    assert _arg_value(model.args, "--budget") == "100"
    assert _arg_value(model.args, "--noise-evidence") == (
        "results/formal/identifiability/gate-a6-d9299f8/"
        "noise_evidence.json"
    )
    assert model.smoke.args == ["--smoke"]
    assert model.smoke.overrides == {"max_jobs": 3}
    assert model.expected_files == [
        "benchmark_plan.json",
        "results.jsonl",
        "evaluations.jsonl",
        "summary.json",
        "selection.json",
        "STATUS.json",
    ]
    assert model.validators == [
        "schema_check",
        "finite_check",
        "provenance",
        "optimizer_benchmark_gate",
    ]
    assert model.validator_config["optimizer_benchmark_gate"] == {
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


def test_a6_optimizer_confirmation_spec_is_frozen() -> None:
    spec_path = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "a6_optimizer_confirmation_cn.yaml"
    )
    raw = yaml.safe_load(spec_path.read_text())
    model = TaskSpec.model_validate(raw)

    assert model.task_name == "a6_optimizer_confirmation_cn"
    assert model.commit == "e7fe80c7b96a149d1dbb929801e5e763016612e6"
    assert model.script == "code/python/scripts/run_optimizer_benchmark.py"
    assert model.output_dir == "results/a6_optimizer_confirmation_cn"
    assert model.workers == 8
    assert model.supports_resume is True
    assert _arg_value(model.args, "--phase") == "confirmation"
    assert _arg_value(model.args, "--backend") == "cn"
    assert _arg_value(model.args, "--budget") == "100"
    assert _arg_value(model.args, "--development-evidence") == (
        "results/formal/identifiability/gate-a6-optimizer-development/"
        "development_evidence.json"
    )
    assert model.smoke.args == ["--smoke"]
    assert model.smoke.overrides == {"max_jobs": 3}
    assert model.expected_files == [
        "benchmark_plan.json",
        "development_evidence.snapshot.json",
        "results.jsonl",
        "evaluations.jsonl",
        "summary.json",
        "confirmation_gate.json",
        "STATUS.json",
    ]
    assert model.validators == [
        "schema_check",
        "finite_check",
        "provenance",
        "optimizer_confirmation_gate",
    ]
    assert model.validator_config["optimizer_confirmation_gate"] == {
        "gate_version": 1,
        "recovery_gate_version": 2,
        "optimizer": "sobol_pattern",
        "parameter_pairs": [
            ["k0_2", "k0_3"],
            ["k0_2", "G_O"],
            ["k0_3", "G_O"],
        ],
        "truth_ids": ["center", "mixed_a", "mixed_b"],
        "noise_fractions": [0.0, 0.001495726085983469],
        "seeds": [7, 17, 27],
        "optimization_budget": 100,
        "development_identity": ["center", 0.0, 7],
        "development_evidence_sha256": (
            "116099242f034c133f4895d068429673f0a12be611b76ea00cc3ebf415a83b8a"
        ),
        "development_source_results_sha256": (
            "e93ccab24c4a91d9d4d9a2b8e014826b6b1a07b7d0891c6e7dd944b78e17b432"
        ),
        "max_median_normalized_bound_error": 0.025,
        "max_normalized_bound_error": 0.05,
        "max_seed_normalized_bound_dispersion": 0.05,
        "max_boundary_hit_rate": 0.0,
    }
