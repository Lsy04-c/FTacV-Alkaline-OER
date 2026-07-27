"""Contract test for the real Legion infrastructure smoke entrypoint."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_workflow_smoke_task_writes_expected_evidence(tmp_path: Path) -> None:
    script = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "workflow_smoke_task.py"
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--output",
            str(tmp_path),
            "--workers",
            "2",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / "summary.csv").read_text(encoding="utf-8") == (
        "check,value\nworkers,2\narithmetic,55\n"
    )
    manifest = json.loads(
        (tmp_path / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["schema_version"] == 1
    assert manifest["workers"] == 2
    assert manifest["checks"]["sum_of_squares_1_to_5"] == 55
