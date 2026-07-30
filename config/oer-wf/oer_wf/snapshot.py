"""Frozen, secret-safe TaskSpec contract stored with every run."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

import yaml

from oer_wf.models import TaskSpec

SNAPSHOT_FILENAME = "task_spec.snapshot.yaml"


def build_snapshot_dict(spec: TaskSpec, *, is_smoke: bool) -> dict[str, Any]:
    expected = list(spec.smoke.expected_files if is_smoke else spec.expected_files)
    for owned in (SNAPSHOT_FILENAME, "STATUS.json"):
        if owned not in expected:
            expected.append(owned)
    payload: dict[str, Any] = {
        "task_name": spec.task_name,
        "commit": spec.commit,
        "script": spec.script,
        "args": list(spec.args),
        "workers": spec.workers,
        "env": dict(spec.env),
        "python": spec.python.model_dump(mode="json"),
        "worktree_root": spec.worktree_root,
        "supports_resume": spec.supports_resume,
        "resume_required_files": list(spec.resume_required_files),
        "output_dir": spec.output_dir,
        "expected_files": expected,
        "validators": list(spec.validators),
        "validator_config": dict(spec.validator_config or {}),
        "is_smoke": is_smoke,
    }
    if is_smoke:
        payload["smoke_expected_files"] = list(spec.smoke.expected_files)
    return payload


def snapshot_yaml_text(spec: TaskSpec, *, is_smoke: bool) -> str:
    return yaml.safe_dump(
        build_snapshot_dict(spec, is_smoke=is_smoke),
        sort_keys=True,
        default_flow_style=False,
    )


def load_snapshot(text: str) -> dict[str, Any]:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("snapshot must be a mapping")
    required = ("task_name", "commit", "script", "output_dir", "expected_files", "validators")
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError(f"snapshot missing fields: {missing}")
    if not isinstance(data["expected_files"], list) or not data["expected_files"]:
        raise ValueError("snapshot expected_files must be a non-empty list")
    if not isinstance(data["validators"], list) or not data["validators"]:
        raise ValueError("snapshot validators must be a non-empty list")
    validator_config = data.get("validator_config") or {}
    if not isinstance(validator_config, dict):
        raise ValueError("snapshot validator_config must be a mapping")
    remote_required = False
    for name, raw in validator_config.items():
        if not isinstance(raw, dict):
            raise ValueError(f"validator_config.{name} must be a mapping")
        execution = raw.get("execution", "local")
        if execution not in {"local", "remote_worktree"}:
            raise ValueError(f"validator_config.{name}.execution is invalid")
        timeout = raw.get("timeout_sec", 600)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, int)
            or not 1 <= timeout <= 3600
        ):
            raise ValueError(
                f"validator_config.{name}.timeout_sec must be 1..3600"
            )
        remote_required = remote_required or execution == "remote_worktree"
    if remote_required:
        missing_runtime = [
            key for key in ("env", "python", "worktree_root") if key not in data
        ]
        if missing_runtime:
            raise ValueError(
                "remote verification snapshot missing: "
                + ", ".join(missing_runtime)
            )
        if not isinstance(data["env"], dict):
            raise ValueError("snapshot env must be a mapping")
        python = data["python"]
        if not isinstance(python, dict):
            raise ValueError("snapshot python must be a mapping")
        if python.get("source") not in {"main_repo", "worktree"}:
            raise ValueError("snapshot python.source is invalid")
        for label, value in (
            ("python.path", python.get("path")),
            ("worktree_root", data["worktree_root"]),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"snapshot {label} must be a relative path")
            path = PurePosixPath(value)
            if path.is_absolute() or ".." in path.parts or value.startswith("~"):
                raise ValueError(f"snapshot {label} must be a safe relative path")
        commit = str(data["commit"])
        if re.fullmatch(r"[0-9a-fA-F]{40}", commit) is None:
            raise ValueError(
                "remote verification snapshot commit must be a full Git SHA-1"
            )
    return data
