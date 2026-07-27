"""Worktree lock (.wf_lock) read / write / validate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

import yaml

from oer_wf.models import LockInfo, TaskSpec


LOCK_FILENAME = ".wf_lock"


def spec_hash(spec: TaskSpec) -> str:
    """Stable SHA-256 of the canonical task_spec content (excluding derived fields)."""
    # Dump to canonical YAML so key order is stable
    raw = yaml.dump(
        spec.model_dump(mode="json", exclude_none=True),
        sort_keys=True,
        default_flow_style=False,
    )
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def lock_path(worktree: Path) -> Path:
    return worktree / LOCK_FILENAME


def read_lock(worktree: Path) -> Optional[LockInfo]:
    p = lock_path(worktree)
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    return LockInfo.model_validate(data)


def write_lock(worktree: Path, info: LockInfo) -> None:
    worktree.mkdir(parents=True, exist_ok=True)
    p = lock_path(worktree)
    p.write_text(info.model_dump_json(indent=2) + "\n", encoding="utf-8")


def remove_lock(worktree: Path) -> bool:
    p = lock_path(worktree)
    if p.exists():
        p.unlink()
        return True
    return False


def check_lock(worktree: Path, spec: TaskSpec) -> tuple[str, Optional[LockInfo]]:
    """
    Returns (action, existing_lock):
      - "create"  : no lock, safe to create worktree + lock
      - "reuse"   : lock present and spec_hash matches
      - "conflict": lock present but spec_hash differs → caller must clean
    """
    existing = read_lock(worktree)
    if existing is None:
        return "create", None

    expected = spec_hash(spec)
    if existing.spec_hash == expected and existing.task_id == spec.task_id:
        return "reuse", existing

    return "conflict", existing
