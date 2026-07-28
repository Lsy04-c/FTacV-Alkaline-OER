"""Unit tests for wf verify."""

from __future__ import annotations

import json
from pathlib import Path

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
