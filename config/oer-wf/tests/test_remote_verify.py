"""Remote frozen-worktree validator worker tests."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from oer_wf.models import CheckResult
from oer_wf import remote_verify


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _payload(main: Path) -> tuple[dict, Path]:
    worktree = main / "worktrees" / "abcdef1" / "task"
    archive = worktree / "results" / "gate" / "20260730_120000"
    archive.mkdir(parents=True)
    (archive / "STATUS.json").write_text('{"status":"SUCCESS"}')
    return (
        {
            "validator": "probe",
            "expected_files": ["STATUS.json"],
            "validator_config": {"execution": "remote_worktree", "limit": 3},
            "worktree": str(worktree),
            "archive": str(archive),
            "commit": "abcdef1234567890",
            "commit_short": "abcdef1",
            "task_name": "task",
            "timestamp": "20260730_120000",
            "worktree_root": "worktrees",
            "env": {"OMP_NUM_THREADS": "1"},
        },
        archive,
    )


def test_decode_request_round_trip() -> None:
    raw = {"validator": "probe", "n": 1}
    encoded = base64.urlsafe_b64encode(
        json.dumps(raw).encode("utf-8")
    ).decode("ascii")

    assert remote_verify.decode_request(encoded) == raw


def test_source_probe_parses_real_git_status(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmp_path,
        check=True,
    )
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=tmp_path, check=True)
    (tmp_path / ".wf_lock").write_text("{}\n", encoding="utf-8")
    result_file = tmp_path / "results" / "run" / "STATUS.json"
    result_file.parent.mkdir(parents=True)
    result_file.write_text('{"status":"SUCCESS"}\n', encoding="utf-8")

    result = remote_verify._source_probe(tmp_path)

    assert result["tracked_clean"] is True
    assert result["invalid_untracked"] == []


def test_execute_rejects_archive_outside_frozen_worktree(
    tmp_path: Path,
    monkeypatch,
) -> None:
    main = tmp_path / "repo"
    payload, _ = _payload(main)
    outside = tmp_path / "outside" / payload["timestamp"]
    outside.mkdir(parents=True)
    payload["archive"] = str(outside)
    monkeypatch.setattr(remote_verify.config, "WSL_MAIN_REPO", main)

    result = remote_verify.execute(payload)

    assert result["status"] == "fail"
    assert result["fail_type"] == "structure"
    assert "outside frozen worktree" in result["message"]


def test_execute_rejects_commit_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    main = tmp_path / "repo"
    payload, _ = _payload(main)
    monkeypatch.setattr(remote_verify.config, "WSL_MAIN_REPO", main)

    result = remote_verify.execute(
        payload,
        source_probe=lambda _: {
            "commit": "deadbeef",
            "tracked_clean": True,
            "invalid_untracked": [],
        },
    )

    assert result["status"] == "fail"
    assert result["fail_type"] == "environment"
    assert "commit mismatch" in result["message"]


def test_execute_restores_env_and_does_not_write_archive(
    tmp_path: Path,
    monkeypatch,
) -> None:
    main = tmp_path / "repo"
    payload, archive = _payload(main)
    monkeypatch.setattr(remote_verify.config, "WSL_MAIN_REPO", main)
    before = _tree_hash(archive)
    seen = {}

    def invoke(name, archive_path, expected, validator_config):
        seen["name"] = name
        seen["archive"] = archive_path
        seen["expected"] = expected
        seen["config"] = validator_config
        seen["env"] = os.environ["OMP_NUM_THREADS"]
        seen["cwd"] = Path.cwd()
        return (
            "remote_worktree",
            600,
            [CheckResult(name="scientific:probe", passed=True, detail="ok")],
        )

    result = remote_verify.execute(
        payload,
        source_probe=lambda _: {
            "commit": payload["commit"],
            "tracked_clean": True,
            "invalid_untracked": [],
        },
        validator_invoke=invoke,
    )

    assert result["status"] == "pass"
    assert result["checks"] == [
        {"name": "scientific:probe", "passed": True, "detail": "ok"}
    ]
    assert seen["config"] == {"execution": "remote_worktree", "limit": 3}
    assert seen["env"] == "1"
    assert seen["cwd"] == Path(payload["worktree"])
    assert _tree_hash(archive) == before


def test_execute_rejects_invalid_untracked_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    main = tmp_path / "repo"
    payload, _ = _payload(main)
    monkeypatch.setattr(remote_verify.config, "WSL_MAIN_REPO", main)

    result = remote_verify.execute(
        payload,
        source_probe=lambda _: {
            "commit": payload["commit"],
            "tracked_clean": True,
            "invalid_untracked": ["code/python/debug.py"],
        },
    )

    assert result["status"] == "fail"
    assert result["fail_type"] == "environment"
    assert "untracked source" in result["message"]


def test_execute_rejects_secret_like_environment_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    main = tmp_path / "repo"
    payload, _ = _payload(main)
    payload["env"] = {"API_TOKEN": "not-allowed"}
    monkeypatch.setattr(remote_verify.config, "WSL_MAIN_REPO", main)

    result = remote_verify.execute(payload)

    assert result["status"] == "fail"
    assert result["fail_type"] == "environment"
    assert "secret-like" in result["message"]
