"""Tests for the V2 conditional-reachability archive gate."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from oer_wf.models import TaskSpec
from oer_wf.validators import conditional_reachability_gate


def _write_archive(tmp_path: Path, mode: str) -> Path:
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "task_spec.json").write_text(
        json.dumps({"run_mode": mode}),
        encoding="utf-8",
    )
    return archive


def test_gate_uses_archive_mode_to_require_formal_rerun(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "project"
    spec = root / "config" / "reachability" / "v2.json"
    spec.parent.mkdir(parents=True)
    spec.write_text("{}", encoding="utf-8")
    script = root / "code" / "python" / "scripts" / (
        "validate_conditional_reachability.py"
    )
    script.parent.mkdir(parents=True)
    script.write_text("# fixture\n", encoding="utf-8")
    archive = _write_archive(tmp_path, "formal")
    calls: list[dict[str, object]] = []

    def fake_loader(path: Path):
        assert path == script

        def validate_archive(
            project_root: Path,
            task_spec: Path,
            archive_dir: Path,
            *,
            rerun_best: bool,
        ) -> dict[str, object]:
            calls.append(
                {
                    "root": project_root,
                    "task_spec": task_spec,
                    "archive": archive_dir,
                    "rerun_best": rerun_best,
                }
            )
            return {"gate": "PASS", "errors": [], "rerun_evidence": [{}, {}, {}, {}]}

        return validate_archive

    monkeypatch.setattr(
        conditional_reachability_gate,
        "_load_validate_archive",
        fake_loader,
    )
    checks = conditional_reachability_gate.run(
        archive,
        validator_config={
            "project_root": str(root),
            "task_spec": "config/reachability/v2.json",
            "rerun_best_smoke": False,
            "rerun_best_formal": True,
        },
    )

    assert all(check.passed for check in checks)
    assert calls == [
        {
            "root": root.resolve(),
            "task_spec": spec.resolve(),
            "archive": archive.resolve(),
            "rerun_best": True,
        }
    ]


def test_gate_reports_validator_failure_as_structure(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "project"
    spec = root / "task.json"
    spec.parent.mkdir(parents=True)
    spec.write_text("{}", encoding="utf-8")
    script = root / "code" / "python" / "scripts" / (
        "validate_conditional_reachability.py"
    )
    script.parent.mkdir(parents=True)
    script.write_text("# fixture\n", encoding="utf-8")
    archive = _write_archive(tmp_path, "smoke")

    monkeypatch.setattr(
        conditional_reachability_gate,
        "_load_validate_archive",
        lambda _path: (
            lambda *_args, **_kwargs: {
                "gate": "FAIL_STRUCTURE",
                "errors": ["base job set mismatch"],
                "rerun_evidence": [],
            }
        ),
    )
    checks = conditional_reachability_gate.run(
        archive,
        validator_config={
            "project_root": str(root),
            "task_spec": "task.json",
            "rerun_best_smoke": False,
            "rerun_best_formal": True,
        },
    )

    assert len(checks) == 1
    assert checks[0].name == "structure:conditional_reachability_gate"
    assert checks[0].passed is False
    assert "base job set mismatch" in checks[0].detail


def test_gate_discovers_project_root_from_nested_working_directory(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "project"
    nested = root / "config" / "oer-wf"
    nested.mkdir(parents=True)
    spec = root / "config" / "reachability" / "v2.json"
    spec.parent.mkdir(parents=True)
    spec.write_text("{}", encoding="utf-8")
    script = root / "code" / "python" / "scripts" / (
        "validate_conditional_reachability.py"
    )
    script.parent.mkdir(parents=True)
    script.write_text("# fixture\n", encoding="utf-8")
    archive = _write_archive(tmp_path, "smoke")
    seen: list[Path] = []

    def fake_loader(_path: Path):
        def validate_archive(
            project_root: Path,
            *_args,
            **_kwargs,
        ) -> dict[str, object]:
            seen.append(project_root)
            return {"gate": "PASS", "errors": [], "rerun_evidence": []}

        return validate_archive

    monkeypatch.chdir(nested)
    monkeypatch.setattr(
        conditional_reachability_gate,
        "_load_validate_archive",
        fake_loader,
    )
    checks = conditional_reachability_gate.run(
        archive,
        validator_config={
            "project_root": ".",
            "task_spec": "config/reachability/v2.json",
            "rerun_best_smoke": False,
        },
    )

    assert all(check.passed for check in checks)
    assert seen == [root.resolve()]


def test_gate_rejects_task_spec_path_escape(tmp_path: Path) -> None:
    archive = _write_archive(tmp_path, "smoke")

    checks = conditional_reachability_gate.run(
        archive,
        validator_config={
            "project_root": str(tmp_path),
            "task_spec": "../outside.json",
        },
    )

    assert len(checks) == 1
    assert checks[0].name == "structure:conditional_reachability_gate_config"
    assert checks[0].passed is False
    assert "relative path" in checks[0].detail


def test_v2_workflow_example_freezes_runtime_contract() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "v2_conditional_reachability_lsoda.yaml"
    )
    model = TaskSpec.model_validate(
        yaml.safe_load(path.read_text(encoding="utf-8"))
    )

    assert model.commit == "fbda4cff248f498b29e1c054aaab2fcaab24e40f"
    assert model.supports_resume is True
    assert model.resume_required_files == [
        "task_spec.json",
        "targets.json",
        "parameter_library.csv",
    ]
    assert model.workers == 8
    assert model.args == [
        "--task-spec",
        "config/reachability/v2-conditional-reachability.json",
    ]
    assert model.smoke.args == ["--smoke"]
    assert model.smoke.overrides == {}
    assert model.expected_files == [
        "task_spec.json",
        "parameter_library.csv",
        "targets.json",
        "base_results.jsonl",
        "stress_results.jsonl",
        "summary.json",
        "run_manifest.json",
        "STATUS.json",
    ]
    assert model.smoke.expected_files == model.expected_files
    assert model.validators == [
        "schema_check",
        "finite_check",
        "provenance",
        "conditional_reachability_gate",
    ]
    assert model.validator_config == {
        "conditional_reachability_gate": {
            "project_root": ".",
            "task_spec": "config/reachability/v2-conditional-reachability.json",
            "rerun_best_smoke": False,
            "rerun_best_formal": True,
        }
    }
    assert model.env == {
        "PYTHONPATH": "code/python/src",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
    }
