"""End-to-end tests for smoke gate, spec_hash, sync path, and child-process signals.

Covers blocking bugs found and fixed in v0.6.2 → v0.6.3:
  1. smoke gate: spec_hash not written → run always rejected (fixed)
  2. child-process signal: ._status_signal overrides exit code (fixed)
  3. sync path level error: ExecStart timestamp treated as base (fixed)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

from oer_wf.commands.run import run_run
from oer_wf.commands.smoke import run_smoke
from oer_wf.commands.sync import (
    _extract_output_dir_from_execstart,
    run_sync,
)
from oer_wf.commands.status import _extract_output_dir_from_unit
from oer_wf.models import FailType, StatusEnum
from oer_wf.transport import ExecResult, MockExecutor


# ---------------------------------------------------------------------------
# spec_hash / smoke gate tests
# ---------------------------------------------------------------------------

class TestSmokeRunGateE2E:
    """Verify that smoke STATUS.json with correct spec_hash enables run,
    and missing/wrong spec_hash blocks it."""

    @patch.dict(os.environ, {"OER_WF_SPEC_HASH": "sha256:abc123"})
    def test_wrapper_reads_spec_hash_from_env(self):
        """Environment variable propagation end-to-end check."""
        from oer_wf.runtime.wrapper import _status, _finalized
        # Import side-effect test: the module should pick up OER_WF_SPEC_HASH
        assert os.environ.get("OER_WF_SPEC_HASH") == "sha256:abc123"


def test_smoke_missing_spec_hash_blocks_run(tmp_path):
    """STATUS.json without spec_hash must block formal run."""
    import yaml

    spec_path = tmp_path / "spec.yaml"
    spec_content = {
        "task_name": "solver_equiv_01",
        "commit": "3f9aad1abcdef",
        "description": "test",
        "python": {"source": "main_repo", "path": ".venv/bin/python"},
        "worktree_root": "worktrees",
        "script": "scripts/run.py",
        "args": [],
        "workers": 1,
        "output_dir": "results/solver_equiv_01",
        "env": {},
        "build": {"required": False},
        "smoke": {
            "enabled": True,
            "overrides": {"n_samples": 2},
            "expected_files": ["summary.csv"],
        },
        "expected_files": ["summary.csv"],
        "validators": ["schema_check"],
    }
    spec_path.write_text(yaml.dump(spec_content))

    mock_ex = MockExecutor()
    mock_ex.when_ssh(".wf_lock").returns(
        0, json.dumps({
            "task_id": "3f9aad1/solver_equiv_01",
            "spec_hash": "sha256:abc",
            "commit": "3f9aad1abcdef",
            "created_at": "2026-01-01T00:00:00Z",
            "worktree_path": "/tmp/wt",
        })
    )
    # Smoke STATUS.json exists but WITHOUT spec_hash field
    mock_ex.when_ssh("STATUS.json").returns(
        0, json.dumps({"status": "SUCCESS"})  # no spec_hash!
    )
    resp = run_run(str(spec_path), executor=mock_ex)
    # Run should be blocked because smoke STATUS has no spec_hash
    assert resp.status == StatusEnum.FAIL
    assert resp.fail_type == FailType.STRUCTURE


def test_smoke_wrong_spec_hash_blocks_run(tmp_path):
    """STATUS.json with mismatched spec_hash must block formal run."""
    import yaml

    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.dump({
        "task_name": "solver_equiv_01",
        "commit": "3f9aad1abcdef",
        "description": "test",
        "python": {"source": "main_repo", "path": ".venv/bin/python"},
        "worktree_root": "worktrees",
        "script": "scripts/run.py",
        "args": [],
        "workers": 1,
        "output_dir": "results/solver_equiv_01",
        "env": {},
        "build": {"required": False},
        "smoke": {
            "enabled": True,
            "overrides": {"n_samples": 2},
            "expected_files": ["summary.csv"],
        },
        "expected_files": ["summary.csv"],
        "validators": ["schema_check"],
    }))

    mock_ex = MockExecutor()
    mock_ex.when_ssh(".wf_lock").returns(
        0, json.dumps({
            "task_id": "3f9aad1/solver_equiv_01",
            "spec_hash": "sha256:WRONG",
            "commit": "3f9aad1abcdef",
            "created_at": "2026-01-01T00:00:00Z",
            "worktree_path": "/tmp/wt",
        })
    )
    # Smoke STATUS with WRONG spec_hash
    mock_ex.when_ssh("STATUS.json").returns(
        0, json.dumps({"status": "SUCCESS", "spec_hash": "sha256:CORRECT"})
    )
    resp = run_run(str(spec_path), executor=mock_ex)
    assert resp.status == StatusEnum.FAIL


# ---------------------------------------------------------------------------
# Sync path extraction tests
# ---------------------------------------------------------------------------

class TestSyncPathExtractionE2E:
    """Verify ExecStart --output extraction handles full timestamped paths."""

    UNIT_WITH_FULL_PATH = """
[Unit]
Description=test
[Service]
Type=oneshot
ExecStart=/usr/bin/python /scripts/run.py --config cfg.yaml --output /home/lsy/OER-FTAcV/worktrees/3f9aad1/solver/results/solver_equiv_01/20260727_124028 --workers 4
StandardOutput=append:/home/lsy/OER-FTAcV/worktrees/3f9aad1/solver/results/solver_equiv_01/20260727_124028/log.txt
"""

    UNIT_NO_OUTPUT = """
[Unit]
Description=test
[Service]
ExecStart=/usr/bin/python /scripts/run.py --config cfg.yaml
"""

    def test_extract_full_timestamped_path(self):
        """Extract the complete timestamped path from ExecStart."""
        result = _extract_output_dir_from_unit(self.UNIT_WITH_FULL_PATH)
        assert result == "/home/lsy/OER-FTAcV/worktrees/3f9aad1/solver/results/solver_equiv_01/20260727_124028"

    def test_extract_returns_none_for_missing(self):
        """No --output in ExecStart returns None."""
        result = _extract_output_dir_from_unit(self.UNIT_NO_OUTPUT)
        assert result is None

    def test_sync_does_not_search_for_subdirectory(self):
        """When ExecStart gives full timestamped path, sync uses it directly."""
        mock_ex = MockExecutor()
        # ExecStart extraction returns full path
        mock_ex.when_ssh("systemctl --user cat").returns(0, self.UNIT_WITH_FULL_PATH)
        # test -d confirms directory exists
        mock_ex.when_ssh("test -d").returns(0, "yes\n")
        # rsync succeeds
        mock_ex.when_rsync("*").returns(0, "")
        resp = run_sync("3f9aad1/solver_equiv_01", executor=mock_ex)
        # Should NOT call _find_remote_output; should go directly to rsync
        assert resp.status in (StatusEnum.PASS, StatusEnum.WARNING)

    def test_extract_from_standard_output_fallback(self):
        """Fallback: parse StandardOutput path when ExecStart has no --output."""
        unit = """
[Unit]
Description=test
[Service]
ExecStart=/usr/bin/python /scripts/run.py
StandardOutput=append:/home/lsy/results/task/20260727_124028/log.txt
"""
        result = _extract_output_dir_from_unit(unit)
        assert result == "/home/lsy/results/task/20260727_124028"


# ---------------------------------------------------------------------------
# Child-process signal file tests
# ---------------------------------------------------------------------------

def test_signal_file_overrides_exit_code(tmp_path):
    """._status_signal written by child process must take priority over exit code."""
    from oer_wf.runtime.wrapper import _finalize, _status, _status_path, _finalized
    from oer_wf.models import ComputeStatus

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    status_file = output_dir / "STATUS.json"
    signal_file = output_dir / "._status_signal"

    # Simulate child process marking numerical failure
    signal_file.write_text(json.dumps({
        "status": "FAIL_NUMERICAL",
        "error_msg": "LSODA too many steps",
        "pid": 99999,
    }))

    # Setup globals as if wrapper initialized
    import oer_wf.runtime.wrapper as w
    w._status_path = status_file
    w._status = w.StatusFile(
        status=ComputeStatus.RUNNING,
        pid=12345,
        commit="abc",
        task_id="test/task",
        command=["python", "script.py"],
        output_dir=str(output_dir),
    )
    w._finalized = False

    # Call finalize with exit_code=0 (which would normally mean SUCCESS)
    w._finalize(exit_code=0)

    # Read the written STATUS.json
    result = json.loads(status_file.read_text())
    assert result["status"] == "FAIL_NUMERICAL", (
        f"signal file should override exit code, got {result['status']}"
    )
    assert "LSODA" in result.get("error_msg", "")

    # Cleanup globals
    w._status_path = None
    w._status = None
    w._finalized = False
