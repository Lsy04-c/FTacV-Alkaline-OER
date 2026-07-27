"""Shared command construction for smoke and formal run.

Both `wf smoke` and `wf run` call the same builders so there is only one
source of truth for argv, output directories, and env.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from oer_wf.models import TaskSpec
from oer_wf.utils.paths import timestamp_utc


@dataclass
class RunPlan:
    """Fully resolved execution plan (smoke or formal)."""

    task_id: str
    commit_short: str
    worktree: Path
    python: Path
    script: Path
    argv: list[str]  # full argv including python + script + args + injected flags
    env: dict[str, str]
    output_dir: Path  # absolute, timestamped
    is_smoke: bool = False
    overrides: dict[str, Any] = field(default_factory=dict)

    @property
    def command_str(self) -> str:
        # shell-safe-ish representation for logging / systemd ExecStart
        parts = []
        for a in self.argv:
            if " " in a or any(c in a for c in "\"'$"):
                parts.append("'" + a.replace("'", "'\\''") + "'")
            else:
                parts.append(a)
        return " ".join(parts)


def make_output_dir(
    worktree: Path,
    output_base: str,
    *,
    is_smoke: bool = False,
    timestamp: Optional[str] = None,
) -> Path:
    """
    Create a unique timestamped output directory.

    Formal:  <worktree>/<output_base>/<YYYYMMDD_HHMMSS>/
    Smoke:   <worktree>/<output_base>/_smoke_<YYYYMMDD_HHMMSS>/

    --force only ever creates a *new* timestamp dir; it never overwrites.
    """
    ts = timestamp or timestamp_utc()
    base = worktree / output_base
    if is_smoke:
        out = base / f"_smoke_{ts}"
    else:
        out = base / ts
    out.mkdir(parents=True, exist_ok=True)
    return out


def build_command(
    spec: TaskSpec,
    *,
    main_repo: Path,
    worktree: Path,
    output_dir: Path,
    is_smoke: bool = False,
    extra_overrides: Optional[dict[str, Any]] = None,
) -> RunPlan:
    """
    Build the full argv for a smoke or formal run.

    Rules:
      - user `args` are passed through unchanged
      - `--output` and `--workers` are always injected at the end by wf
      - if args already contain those flags → TaskSpec validator already rejected
      - smoke overrides are appended as `--key value` pairs (stringified)
      - scientific keys must NOT appear in smoke.overrides by convention
        (enforced by documentation + optional allow-list later)
    """
    python = spec.resolve_python(main_repo, worktree)
    script = worktree / spec.script

    argv: list[str] = [str(python), str(script)]
    argv.extend(spec.args)

    overrides: dict[str, Any] = {}
    if is_smoke:
        overrides.update(spec.smoke.overrides)
    if extra_overrides:
        overrides.update(extra_overrides)

    for key, val in overrides.items():
        # normalize: allow keys with or without leading dashes
        flag = key if key.startswith("-") else f"--{key}"
        argv.append(flag)
        argv.append(str(val))

    # Injected by wf – always last
    argv.extend(["--output", str(output_dir)])
    argv.extend(["--workers", str(spec.workers)])

    env = dict(spec.env)

    return RunPlan(
        task_id=spec.task_id,
        commit_short=spec.commit_short,
        worktree=worktree,
        python=python,
        script=script,
        argv=argv,
        env=env,
        output_dir=output_dir,
        is_smoke=is_smoke,
        overrides=overrides,
    )
