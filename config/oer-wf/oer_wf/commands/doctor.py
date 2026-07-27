"""wf doctor – read-only environment health check."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from oer_wf import config
from oer_wf.models import CheckResult, FailType, WfResponse
from oer_wf.response import fail, ok, warning
from oer_wf.transport import Executor, RealExecutor


def run_doctor(executor: Optional[Executor] = None) -> WfResponse:
    """Run all environment checks and return a unified response."""
    ex = executor or RealExecutor()
    checks: list[CheckResult] = []
    warnings: list[str] = []

    # ------------------------------------------------------------------
    # 1. SSH → WSL connectivity
    # ------------------------------------------------------------------
    r = ex.ssh_exec("whoami && uname -s && uname -r")
    if r.ok:
        lines = [ln.strip() for ln in r.stdout.strip().splitlines() if ln.strip()]
        who = lines[0] if lines else "?"
        kernel = lines[2] if len(lines) >= 3 else "?"
        checks.append(CheckResult(
            name="ssh_wsl",
            passed=True,
            detail=f"connected as {who}, kernel {kernel}",
        ))
    else:
        checks.append(CheckResult(
            name="ssh_wsl",
            passed=False,
            detail=f"ssh failed: {r.stderr.strip() or r.stdout.strip()}",
        ))
        return fail(
            FailType.ENVIRONMENT,
            "Cannot reach WSL via SSH. Check sshd / ForceCommand / network.",
            next_action="fix ssh connection (see docs/ssh_setup.md)",
            checks=checks,
        )

    # ------------------------------------------------------------------
    # 2. Clock skew (Mac local vs WSL UTC)
    # ------------------------------------------------------------------
    local_utc = datetime.now(timezone.utc)
    r_date = ex.ssh_exec("date -u +%Y-%m-%dT%H:%M:%SZ")
    if r_date.ok:
        remote_str = r_date.stdout.strip()
        try:
            remote_utc = datetime.strptime(remote_str, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            skew = abs((local_utc - remote_utc).total_seconds())
            if skew > config.CLOCK_SKEW_WARN_SEC:
                checks.append(CheckResult(
                    name="clock_skew",
                    passed=False,
                    detail=f"skew {skew:.1f}s > {config.CLOCK_SKEW_WARN_SEC}s threshold",
                ))
                warnings.append(f"clock skew {skew:.1f}s")
            else:
                checks.append(CheckResult(
                    name="clock_skew",
                    passed=True,
                    detail=f"skew {skew:.1f}s (ok)",
                ))
        except ValueError:
            checks.append(CheckResult(
                name="clock_skew",
                passed=False,
                detail=f"cannot parse remote date: {remote_str}",
            ))
            warnings.append("clock parse failed")
    else:
        checks.append(CheckResult(
            name="clock_skew",
            passed=False,
            detail="date command failed on remote",
        ))
        warnings.append("clock check failed")

    # ------------------------------------------------------------------
    # 3. Main repo exists & is a git repo
    # ------------------------------------------------------------------
    repo = str(config.WSL_MAIN_REPO)
    r_repo = ex.ssh_exec(f"test -d {repo}/.git && echo yes || echo no")
    if r_repo.ok and "yes" in r_repo.stdout:
        checks.append(CheckResult(name="main_repo", passed=True, detail=repo))
    else:
        checks.append(CheckResult(
            name="main_repo",
            passed=False,
            detail=f"{repo} is not a git repository",
        ))
        return fail(
            FailType.ENVIRONMENT,
            f"Main repo not found or not a git repo: {repo}",
            next_action=f"clone or fix repo at {repo}",
            checks=checks,
        )

    # ------------------------------------------------------------------
    # 4. Git status (dirty warning only)
    # ------------------------------------------------------------------
    r_git = ex.ssh_exec(f"cd {repo} && git rev-parse --short HEAD && git status --porcelain")
    if r_git.ok:
        lines = r_git.stdout.strip().splitlines()
        head = lines[0] if lines else "?"
        dirty = len(lines) > 1
        detail = f"HEAD {head}" + (" (dirty)" if dirty else " (clean)")
        checks.append(CheckResult(name="git_status", passed=True, detail=detail))
        if dirty:
            warnings.append("main repo is dirty")
    else:
        checks.append(CheckResult(
            name="git_status",
            passed=False,
            detail=r_git.stderr.strip() or "git failed",
        ))
        warnings.append("git status failed")

    # ------------------------------------------------------------------
    # 5. Python / venv
    # ------------------------------------------------------------------
    venv_py = f"{repo}/.venv/bin/python"
    r_py = ex.ssh_exec(f"test -x {venv_py} && {venv_py} --version")
    if r_py.ok:
        checks.append(CheckResult(
            name="venv_python",
            passed=True,
            detail=r_py.stdout.strip(),
        ))
    else:
        checks.append(CheckResult(
            name="venv_python",
            passed=False,
            detail=f"{venv_py} missing or not executable",
        ))
        return fail(
            FailType.ENVIRONMENT,
            "Project venv not found. Create it before running calculations.",
            next_action=f"cd {repo} && python -m venv .venv && .venv/bin/pip install -r requirements.txt",
            checks=checks,
        )

    # ------------------------------------------------------------------
    # 6. rsync availability (remote)
    # ------------------------------------------------------------------
    r_rsync = ex.ssh_exec("command -v rsync && rsync --version | head -1")
    if r_rsync.ok:
        checks.append(CheckResult(
            name="rsync",
            passed=True,
            detail=r_rsync.stdout.strip().splitlines()[-1] if r_rsync.stdout.strip() else "present",
        ))
    else:
        checks.append(CheckResult(
            name="rsync",
            passed=False,
            detail="rsync not found in WSL PATH",
        ))
        return fail(
            FailType.ENVIRONMENT,
            "rsync not installed in WSL. Install with: sudo apt install rsync",
            next_action="sudo apt install rsync",
            checks=checks,
        )

    # ------------------------------------------------------------------
    # 7. systemd availability (v0.6.2: separate checks, no chained fallbacks)
    # Each check runs independently; degraded is a warning, not a hard fail.
    # ------------------------------------------------------------------
    r_bin = ex.ssh_exec("command -v systemctl >/dev/null && echo found || echo missing")
    has_systemctl = "found" in (r_bin.stdout or "")

    r_state = ex.ssh_exec("systemctl --user is-system-running 2>/dev/null || systemctl is-system-running 2>/dev/null || echo unknown")
    sd_state = (r_state.stdout or "").strip().splitlines()
    # Take the first meaningful output line (not the multi-command noise)
    sd_value = [s for s in sd_state if s in ("running", "degraded", "starting", "stopping", "maintenance", "offline", "unknown")]
    sd_actual = sd_value[0] if sd_value else "unknown"

    if not has_systemctl:
        checks.append(CheckResult(name="systemd", passed=False, detail="systemctl not found"))
        warnings.append("systemd unavailable: systemctl binary missing")
    elif sd_actual in ("running", "degraded"):
        checks.append(CheckResult(
            name="systemd",
            passed=True,
            detail=sd_actual + (" (non-fatal; some units failed)" if sd_actual == "degraded" else ""),
        ))
        if sd_actual == "degraded":
            warnings.append("systemd is degraded (usable, but inspect failed units)")
    else:
        checks.append(CheckResult(
            name="systemd",
            passed=True,
            detail=f"state={sd_actual} (acceptable for doctor)",
        ))
        warnings.append(f"systemd state={sd_actual}")

    # ------------------------------------------------------------------
    # Aggregate
    # ------------------------------------------------------------------
    all_hard_pass = all(c.passed for c in checks if c.name not in ("clock_skew", "git_status", "systemd"))
    if not all_hard_pass:
        return fail(
            FailType.ENVIRONMENT,
            "One or more critical environment checks failed.",
            next_action="fix the failed checks above",
            checks=checks,
        )

    if warnings:
        return warning(
            message="; ".join(warnings),
            next_action="wf prepare <task_spec.yaml>",
            data={"warnings": warnings},
            checks=checks,
        )

    return ok(
        message="environment healthy",
        next_action="wf prepare <task_spec.yaml>",
        checks=checks,
    )
