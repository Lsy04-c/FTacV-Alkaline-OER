"""Tests for the V3 residual-attribution workflow gate."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from oer_wf.models import TaskSpec
from oer_wf.validators import v3_residual_attribution_gate


def _archive(tmp_path: Path, mode: str) -> Path:
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "v3_task_spec.json").write_text(
        json.dumps({"run_mode": mode}),
        encoding="utf-8",
    )
    return archive


def test_v3_gate_requires_four_formal_reruns(tmp_path, monkeypatch):
    root = tmp_path / "project"
    task_spec = root / "config" / "residual" / "v3.json"
    task_spec.parent.mkdir(parents=True)
    task_spec.write_text("{}", encoding="utf-8")
    script = (
        root
        / "code"
        / "python"
        / "scripts"
        / "validate_v3_residual_attribution.py"
    )
    script.parent.mkdir(parents=True)
    script.write_text("# fixture\n", encoding="utf-8")
    archive = _archive(tmp_path, "formal")
    calls = []

    def fake_loader(path):
        assert path == script

        def validate(root_arg, spec_arg, archive_arg, *, rerun_nearest):
            calls.append((root_arg, spec_arg, archive_arg, rerun_nearest))
            return {
                "gate": "PASS",
                "errors": [],
                "rerun_evidence": [{}, {}, {}, {}],
            }

        return validate

    monkeypatch.setattr(
        v3_residual_attribution_gate,
        "_load_validate_archive",
        fake_loader,
    )
    checks = v3_residual_attribution_gate.run(
        archive,
        validator_config={
            "project_root": str(root),
            "task_spec": "config/residual/v3.json",
            "rerun_nearest_smoke": False,
            "rerun_nearest_formal": True,
        },
    )

    assert all(check.passed for check in checks)
    assert calls == [
        (root.resolve(), task_spec.resolve(), archive.resolve(), True)
    ]


def test_v3_gate_rejects_path_escape(tmp_path):
    checks = v3_residual_attribution_gate.run(
        _archive(tmp_path, "smoke"),
        validator_config={
            "project_root": str(tmp_path),
            "task_spec": "../outside.json",
        },
    )

    assert checks[0].passed is False
    assert "relative path" in checks[0].detail


def test_v3_workflow_example_freezes_runtime_contract():
    path = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "v3_residual_attribution_lsoda.yaml"
    )
    model = TaskSpec.model_validate(
        yaml.safe_load(path.read_text(encoding="utf-8"))
    )

    assert model.commit == "UNFROZEN"
    assert model.workers == 8
    assert model.supports_resume is True
    assert model.smoke.args == ["--smoke"]
    assert model.env["OPENBLAS_NUM_THREADS"] == "1"
    assert model.validators[-1] == "v3_residual_attribution_gate"
