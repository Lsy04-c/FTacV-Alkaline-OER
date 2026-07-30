"""Run one scientific validator inside its frozen Legion worktree."""

from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Callable, Iterator, Sequence

from oer_wf import config
from oer_wf.models import CheckResult
from oer_wf.validator_runner import run_validator


SourceProbe = Callable[[Path], dict[str, Any]]
ValidatorInvoke = Callable[
    [str, Path, list[str], dict[str, Any]],
    tuple[str, int, list[CheckResult]],
]


def decode_request(encoded: str) -> dict[str, Any]:
    raw = base64.urlsafe_b64decode(encoded.encode("ascii"))
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("remote verification request must be a JSON object")
    return value


def _source_probe(worktree: Path) -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=worktree,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tracked_clean = (
        subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--"],
            cwd=worktree,
            check=False,
        ).returncode
        == 0
        and subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=worktree,
            check=False,
        ).returncode
        == 0
    )
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=worktree,
        check=True,
        capture_output=True,
    ).stdout
    invalid_untracked: list[str] = []
    for entry in status.split("\0"):
        if not entry or not entry.startswith("?? "):
            continue
        path = entry[3:]
        if path != ".wf_lock" and not path.startswith("results/"):
            invalid_untracked.append(path)
    return {
        "commit": commit,
        "tracked_clean": tracked_clean,
        "invalid_untracked": invalid_untracked,
    }


@contextmanager
def _runtime(worktree: Path, env: dict[str, str]) -> Iterator[None]:
    old_cwd = Path.cwd()
    old_env = {key: os.environ.get(key) for key in env}
    try:
        os.chdir(worktree)
        os.environ.update(env)
        yield
    finally:
        os.chdir(old_cwd)
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _failure(fail_type: str, message: str) -> dict[str, Any]:
    return {
        "status": "fail",
        "fail_type": fail_type,
        "message": message,
        "checks": [],
    }


def _check_fail_type(checks: list[CheckResult]) -> str:
    failed = [check for check in checks if not check.passed]
    if any(check.name.startswith("scientific:") for check in failed):
        return "scientific"
    if any(check.name.startswith(("numerical:", "finite:")) for check in failed):
        return "numerical"
    return "structure"


def execute(
    payload: dict[str, Any],
    *,
    source_probe: SourceProbe = _source_probe,
    validator_invoke: ValidatorInvoke = run_validator,
) -> dict[str, Any]:
    """Validate paths/source, restore env, and invoke one validator."""
    started = time.monotonic()
    try:
        commit = str(payload["commit"])
        commit_short = str(payload["commit_short"])
        task_name = str(payload["task_name"])
        timestamp = str(payload["timestamp"])
        worktree_root = str(payload["worktree_root"])
        worktree = Path(str(payload["worktree"])).resolve()
        archive = Path(str(payload["archive"])).resolve()
        expected_worktree = (
            config.WSL_MAIN_REPO
            / worktree_root
            / commit_short
            / task_name
        ).resolve()
        if worktree != expected_worktree:
            return _failure(
                "structure",
                f"worktree does not match frozen task path: {worktree}",
            )
        try:
            archive.relative_to(worktree)
        except ValueError:
            return _failure("structure", "archive is outside frozen worktree")
        if archive.name != timestamp:
            return _failure("structure", "archive timestamp mismatch")
        if not archive.is_dir():
            return _failure("transport", f"remote archive missing: {archive}")
        env_raw = payload.get("env")
        if not isinstance(env_raw, dict):
            return _failure("environment", "frozen env is missing")
        env = {str(key): str(value) for key, value in env_raw.items()}
        secret_markers = ("TOKEN", "PASSWORD", "SECRET", "PRIVATE_KEY")
        secret_keys = [
            key
            for key in env
            if any(marker in key.upper() for marker in secret_markers)
        ]
        if secret_keys:
            return _failure(
                "environment",
                "frozen env contains secret-like key: " + ", ".join(secret_keys),
            )
        probe = source_probe(worktree)
        if str(probe.get("commit")) != commit:
            return _failure("environment", "frozen worktree commit mismatch")
        if probe.get("tracked_clean") is not True:
            return _failure("environment", "frozen worktree has tracked changes")
        invalid = list(probe.get("invalid_untracked") or [])
        if invalid:
            return _failure(
                "environment",
                "frozen worktree has untracked source: " + ", ".join(invalid),
            )
        validator = str(payload["validator"])
        expected_files = [str(item) for item in payload["expected_files"]]
        validator_config = dict(payload.get("validator_config") or {})
    except (
        KeyError,
        TypeError,
        ValueError,
        OSError,
        subprocess.SubprocessError,
    ) as exc:
        return _failure("structure", f"invalid remote request: {exc}")

    try:
        with _runtime(worktree, env):
            _, _, checks = validator_invoke(
                validator,
                archive,
                expected_files,
                validator_config,
            )
    except Exception as exc:
        return _failure("environment", f"remote validator crashed: {exc}")

    failed = [check for check in checks if not check.passed]
    return {
        "status": "fail" if failed else "pass",
        "fail_type": _check_fail_type(checks) if failed else "null",
        "message": (
            f"remote validator failed: {validator}"
            if failed
            else f"remote validator passed: {validator}"
        ),
        "checks": [check.model_dump() for check in checks],
        "validator": validator,
        "commit": commit,
        "worktree": str(worktree),
        "archive": str(archive),
        "env_keys": sorted(env),
        "duration_seconds": time.monotonic() - started,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", required=True)
    args = parser.parse_args(argv)
    try:
        result = execute(decode_request(args.payload))
    except Exception as exc:
        result = _failure("structure", f"invalid encoded request: {exc}")
    print(json.dumps(result, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
