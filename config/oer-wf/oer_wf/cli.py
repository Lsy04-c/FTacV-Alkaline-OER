"""Typer CLI entry point for oer-wf."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from oer_wf import __version__
from oer_wf.commands.clean import run_clean
from oer_wf.commands.doctor import run_doctor
from oer_wf.commands.prepare import run_prepare
from oer_wf.commands.run import run_run
from oer_wf.commands.smoke import run_smoke
from oer_wf.commands.status import run_status
from oer_wf.commands.git_check import run_git_check
from oer_wf.commands.sync import run_sync
from oer_wf.commands.verify import run_verify
from oer_wf.models import WfResponse

app = typer.Typer(
    name="wf",
    help="OER-FTAcV reusable computational workflow CLI",
    no_args_is_help=True,
    add_completion=False,
)
console = Console(stderr=True)


def _emit(resp: WfResponse) -> None:
    """Print JSON to stdout and set exit code."""
    print(resp.to_json())
    if resp.status.value in ("fail", "inconsistent"):
        raise typer.Exit(code=1)
    if resp.status.value == "warning":
        raise typer.Exit(code=0)


def _version_callback(value: bool) -> None:
    if value:
        print(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-V",
        help="Show version and exit",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    pass


@app.command()
def doctor() -> None:
    """Read-only environment health check (SSH, clock, git, venv, rsync, systemd)."""
    resp = run_doctor()
    _emit(resp)


@app.command()
def prepare(
    spec: Path = typer.Argument(
        ..., exists=True, readable=True, help="Path to task_spec.yaml"
    ),
) -> None:
    """Create or reuse a commit-specific worktree and write .wf_lock."""
    resp = run_prepare(spec)
    _emit(resp)


@app.command()
def clean(
    task_id: str = typer.Argument(..., help="task_id (commit_short/task_name)"),
    force: bool = typer.Option(
        False, "--force", help="Also remove the entire worktree"
    ),
    keep_results: bool = typer.Option(
        False, "--keep-results", help="Never delete result dirs"
    ),
) -> None:
    """Reset intermediate state for a task_id."""
    resp = run_clean(task_id, force=force, keep_results=keep_results)
    _emit(resp)


@app.command()
def run(
    spec: Path = typer.Argument(..., exists=True, readable=True),
    force: bool = typer.Option(
        False,
        "--force",
        help="Allow start when prior unit is inactive/failed; always creates a NEW timestamped output dir",
    ),
    skip_smoke: bool = typer.Option(
        False,
        "--skip-smoke",
        help="Bypass smoke-success gate (explicit; not recommended for formal runs)",
    ),
    resume_timestamp: Optional[str] = typer.Option(
        None,
        "--resume-timestamp",
        help="Resume one exact prior YYYYMMDD_HHMMSS output directory",
    ),
) -> None:
    """Start formal systemd calculation (wrapper + STATUS.json)."""
    resp = run_run(
        spec,
        force=force,
        skip_smoke=skip_smoke,
        resume_timestamp=resume_timestamp,
    )
    _emit(resp)


@app.command()
def status(
    task_id: str = typer.Argument(..., help="task_id (commit_short/task_name)"),
    output_dir: Optional[str] = typer.Option(
        None,
        "--output-dir",
        help="Absolute WSL path to a specific result dir (default: latest timestamp)",
    ),
) -> None:
    """Query systemd + STATUS.json (conflicts → inconsistent, never guess success)."""
    resp = run_status(task_id, output_dir=output_dir)
    _emit(resp)


@app.command()
def smoke(
    spec: Path = typer.Argument(..., exists=True, readable=True),
    timeout: int = typer.Option(
        600, "--timeout", help="Max seconds to wait for smoke STATUS terminal state"
    ),
) -> None:
    """Run smoke test (same core as run; safe overrides only + structural checks)."""
    resp = run_smoke(spec, timeout_sec=timeout)
    _emit(resp)


@app.command()
def sync(
    task_id: str = typer.Argument(..., help="task_id (commit_short/task_name)"),
    timestamp: Optional[str] = typer.Option(
        None, "--timestamp", help="Specific result timestamp (default: latest formal)"
    ),
    output_base: Optional[str] = typer.Option(
        None, "--output-base", help="Relative output base under worktree (default: results/<task_name>)"
    ),
) -> None:
    """rsync WSL results to Mac archive (never overwrites existing timestamp dir)."""
    resp = run_sync(task_id, timestamp=timestamp, output_base=output_base)
    _emit(resp)


@app.command()
def verify(
    task_id: str = typer.Argument(..., help="task_id (commit_short/task_name)"),
    timestamp: Optional[str] = typer.Option(
        None, "--timestamp", help="Specific archived timestamp (default: latest)"
    ),
    expected_files: Optional[list[str]] = typer.Option(
        None,
        "--expected-file",
        help="Expected file for a legacy archive; repeat for each file",
    ),
    validators: Optional[list[str]] = typer.Option(
        None,
        "--validator",
        help="Validator for a legacy archive; repeat for each validator",
    ),
) -> None:
    """Verify a Mac archive using its frozen task contract."""
    resp = run_verify(
        task_id,
        timestamp=timestamp,
        expected_files=expected_files,
        validators=validators,
    )
    _emit(resp)


@app.command("git-check")
def git_check(
    no_tests: bool = typer.Option(
        False, "--no-tests", help="Skip pytest (scope check only)"
    ),
) -> None:
    """Git change scope + optional tests + delivery checklist (never auto-commits)."""
    resp = run_git_check(run_tests=not no_tests)
    _emit(resp)


if __name__ == "__main__":
    app()
