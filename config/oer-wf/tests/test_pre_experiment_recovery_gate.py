from __future__ import annotations

from pathlib import Path

from oer_wf.validators import pre_experiment_recovery_gate


def _project(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "project"
    task_spec = root / "config" / "recovery" / "pre-experiment-a6-v2.json"
    task_spec.parent.mkdir(parents=True)
    task_spec.write_text("{}", encoding="utf-8")
    script = (
        root
        / "code"
        / "python"
        / "scripts"
        / "validate_pre_experiment_recovery.py"
    )
    script.parent.mkdir(parents=True)
    script.write_text("# fixture\n", encoding="utf-8")
    archive = tmp_path / "archive"
    archive.mkdir()
    return root, task_spec, archive


def test_gate_bridges_to_independent_validator(tmp_path, monkeypatch):
    root, task_spec, archive = _project(tmp_path)
    calls = []

    def fake_loader(path):
        def validate(root_arg, spec_arg, archive_arg):
            calls.append((root_arg, spec_arg, archive_arg))
            return {
                "gate": "PASS",
                "stage": "S1",
                "stage_status": "S1_ELIGIBLE",
                "scientific_gate_passed": True,
                "eligible_parameter_pairs": [["k0_2", "k0_3"]],
                "errors": [],
            }

        return validate

    monkeypatch.setattr(
        pre_experiment_recovery_gate,
        "_load_validate_archive",
        fake_loader,
    )
    checks = pre_experiment_recovery_gate.run(
        archive,
        validator_config={
            "project_root": str(root),
            "task_spec": "config/recovery/pre-experiment-a6-v2.json",
        },
    )

    assert all(check.passed for check in checks)
    assert calls == [(root.resolve(), task_spec.resolve(), archive.resolve())]


def test_gate_rejects_task_spec_path_escape(tmp_path):
    root, _, archive = _project(tmp_path)

    checks = pre_experiment_recovery_gate.run(
        archive,
        validator_config={
            "project_root": str(root),
            "task_spec": "../outside.json",
        },
    )

    assert checks[0].passed is False
    assert checks[0].name == "structure:pre_experiment_recovery_gate_config"
