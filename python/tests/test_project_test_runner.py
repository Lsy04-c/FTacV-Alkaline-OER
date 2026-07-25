"""Tests for the repository-standard pytest launcher."""

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run_tests.py"
SPEC = importlib.util.spec_from_file_location("run_tests", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_project_python_prefers_repository_virtualenv(tmp_path):
    root = tmp_path / "repo"
    interpreter = root / ".venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.touch()

    assert MODULE.project_python(root, fallback="/system/python") == str(
        interpreter
    )


def test_pytest_command_uses_selected_interpreter():
    assert MODULE.pytest_command("/project/python", ["tests", "-q"]) == [
        "/project/python",
        "-m",
        "pytest",
        "tests",
        "-q",
    ]
