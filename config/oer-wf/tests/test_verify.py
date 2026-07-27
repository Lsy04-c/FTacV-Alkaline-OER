"""Unit tests for wf verify."""

from __future__ import annotations

import json
from pathlib import Path

from oer_wf.commands.verify import run_verify
from oer_wf.models import StatusEnum
import oer_wf.config as cfg


def test_verify_missing_archive(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cfg, "MAC_ARCHIVE_ROOT", tmp_path / "archive")
    resp = run_verify("3f9aad1/solver_equiv_01")
    assert resp.status == StatusEnum.FAIL
    assert "sync" in resp.next_action


def test_verify_pass(tmp_path: Path, monkeypatch) -> None:
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

    resp = run_verify("3f9aad1/solver_equiv_01")
    assert resp.status == StatusEnum.PASS
    assert any(c.name.startswith("file:") and c.passed for c in resp.checks)


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

    resp = run_verify("3f9aad1/solver_equiv_01")
    assert resp.status == StatusEnum.FAIL
    assert resp.fail_type.value == "numerical"
