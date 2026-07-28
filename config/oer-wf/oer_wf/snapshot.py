"""Frozen, secret-safe TaskSpec contract stored with every run."""

from __future__ import annotations

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
        "supports_resume": spec.supports_resume,
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
    return data
