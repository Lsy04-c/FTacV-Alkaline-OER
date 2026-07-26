"""Tests for the workspace baseline audit helper."""

import importlib.util
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "code"
    / "python"
    / "scripts"
    / "audit_workspace_baseline.py"
)
SPEC = importlib.util.spec_from_file_location("audit_workspace_baseline", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_project_python_prefers_repository_virtualenv(tmp_path):
    project = tmp_path / "project"
    interpreter = project / ".venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.touch()

    assert MODULE.project_python(project, fallback="/system/python") == str(
        interpreter
    )
