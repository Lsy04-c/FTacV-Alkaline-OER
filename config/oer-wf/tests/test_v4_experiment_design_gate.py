"""Tests for the V4 experiment-design workflow gate."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from oer_wf.models import TaskSpec
from oer_wf.validators import v4_experiment_design_gate


COMPUTE_COMMIT = "6c2084a2acfc8ea2f52956f924a9193366fbf4e6"


def _project(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "project"
    task_spec = root / "config" / "experiment-design" / "v4.json"
    task_spec.parent.mkdir(parents=True)
    task_spec.write_text("{}", encoding="utf-8")
    script = (
        root
        / "code"
        / "python"
        / "scripts"
        / "validate_v4_experiment_design.py"
    )
    script.parent.mkdir(parents=True)
    script.write_text("# fixture\n", encoding="utf-8")
    archive = tmp_path / "archive"
    archive.mkdir()
    return root, task_spec, archive


def test_v4_gate_requires_eight_reruns_for_two_formal_recommendations(
    tmp_path,
    monkeypatch,
):
    root, task_spec, archive = _project(tmp_path)
    (archive / "v4_task_spec.json").write_text(
        json.dumps({"run_mode": "formal"}),
        encoding="utf-8",
    )
    calls = []

    def fake_loader(path):
        def validate(root_arg, spec_arg, archive_arg, *, rerun_selected):
            calls.append((root_arg, spec_arg, archive_arg, rerun_selected))
            return {
                "gate": "PASS",
                "errors": [],
                "recommendation_status": "RECOMMEND_TWO",
                "rerun_evidence": [{} for _ in range(8)],
            }

        return validate

    monkeypatch.setattr(
        v4_experiment_design_gate,
        "_load_validate_archive",
        fake_loader,
    )
    checks = v4_experiment_design_gate.run(
        archive,
        validator_config={
            "project_root": str(root),
            "task_spec": "config/experiment-design/v4.json",
            "rerun_selected_smoke": False,
            "rerun_selected_formal": True,
        },
    )

    assert all(check.passed for check in checks)
    assert calls == [
        (root.resolve(), task_spec.resolve(), archive.resolve(), True)
    ]


def test_v4_gate_accepts_zero_reruns_for_formal_no_recommendation(
    tmp_path,
    monkeypatch,
):
    root, _, archive = _project(tmp_path)
    (archive / "v4_task_spec.json").write_text(
        json.dumps({"run_mode": "formal"}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        v4_experiment_design_gate,
        "_load_validate_archive",
        lambda path: (
            lambda *args, **kwargs: {
                "gate": "PASS",
                "errors": [],
                "recommendation_status": "NO_ROBUST_RECOMMENDATION",
                "rerun_evidence": [],
            }
        ),
    )
    checks = v4_experiment_design_gate.run(
        archive,
        validator_config={
            "project_root": str(root),
            "task_spec": "config/experiment-design/v4.json",
            "rerun_selected_formal": True,
        },
    )

    assert all(check.passed for check in checks)


def test_v4_gate_rejects_path_escape(tmp_path):
    _, _, archive = _project(tmp_path)
    (archive / "v4_task_spec.json").write_text(
        json.dumps({"run_mode": "smoke"}),
        encoding="utf-8",
    )

    checks = v4_experiment_design_gate.run(
        archive,
        validator_config={
            "project_root": str(tmp_path),
            "task_spec": "../outside.json",
        },
    )

    assert checks[0].passed is False
    assert "relative path" in checks[0].detail


def test_v4_workflow_example_freezes_runtime_contract():
    path = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "v4_experiment_design_lsoda.yaml"
    )
    model = TaskSpec.model_validate(
        yaml.safe_load(path.read_text(encoding="utf-8"))
    )

    assert model.commit == COMPUTE_COMMIT
    assert model.workers == 8
    assert model.supports_resume is True
    assert model.smoke.args == ["--smoke"]
    assert model.env["OPENBLAS_NUM_THREADS"] == "1"
    assert model.validators[-1] == "v4_experiment_design_gate"
    assert "forward_results.jsonl" in model.resume_required_files
