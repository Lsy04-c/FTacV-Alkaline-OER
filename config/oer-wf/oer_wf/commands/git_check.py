"""wf git-check – change scope, tests, and delivery checklist.

Does NOT auto-commit or push. Produces a structured report for human/Agent review.
"""

from __future__ import annotations

import re
from typing import Optional

from oer_wf import config
from oer_wf.models import CheckResult, FailType, WfResponse
from oer_wf.response import fail, ok, warning
from oer_wf.transport import Executor, RealExecutor

# Files / patterns that must not be staged for a scientific delivery commit
_EXCLUDED_PATTERNS = [
    r"\.wf_lock$",
    r"_smoke_",
    r"results/.*/[0-9]{8}_[0-9]{6}/",  # timestamped result dirs
    r"__pycache__",
    r"\.pytest_cache",
    r"\.venv/",
    r"\.egg-info/",
    r"\.DS_Store$",
    r"\.wf/",
]


def _is_excluded(path: str) -> bool:
    for pat in _EXCLUDED_PATTERNS:
        if re.search(pat, path):
            return True
    return False


def run_git_check(
    *,
    run_tests: bool = True,
    executor: Optional[Executor] = None,
) -> WfResponse:
    """
    Inspect git state on the remote main repo and optionally run pytest.

    Output data:
      - branch, head
      - staged / unstaged / untracked (filtered)
      - excluded_files (should not commit)
      - test_summary
      - commit_message_draft
    """
    ex = executor or RealExecutor()
    repo = str(config.WSL_MAIN_REPO)
    checks: list[CheckResult] = []

    # ---- identity ----
    r_head = ex.ssh_exec(
        f"cd {repo} && git rev-parse --abbrev-ref HEAD && "
        f"git rev-parse --short HEAD && git status --porcelain=v1"
    )
    if not r_head.ok:
        return fail(
            FailType.ENVIRONMENT,
            f"git status failed: {r_head.stderr.strip() or r_head.stdout.strip()}",
            next_action="check SSH and repo path",
        )

    lines = [ln for ln in r_head.stdout.splitlines() if ln.strip()]
    if len(lines) < 2:
        return fail(
            FailType.ENVIRONMENT,
            "unexpected git output",
            data={"stdout": r_head.stdout},
        )

    branch = lines[0].strip()
    head = lines[1].strip()
    porcelain = lines[2:]

    staged: list[str] = []
    unstaged: list[str] = []
    untracked: list[str] = []
    excluded: list[str] = []

    for ln in porcelain:
        # porcelain v1: XY PATH or XY ORIG -> PATH
        if len(ln) < 4:
            continue
        xy, path = ln[:2], ln[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[-1]
        if _is_excluded(path):
            excluded.append(path)
            continue
        x, y = xy[0], xy[1]
        if x in "MADRCU":  # staged
            staged.append(path)
        if y in "MADRCU":  # unstaged
            unstaged.append(path)
        if xy == "??":
            untracked.append(path)

    checks.append(
        CheckResult(
            name="git_clean_scope",
            passed=len(excluded) == 0 or True,  # informational
            detail=f"staged={len(staged)} unstaged={len(unstaged)} "
            f"untracked={len(untracked)} excluded={len(excluded)}",
        )
    )

    if excluded:
        checks.append(
            CheckResult(
                name="excluded_present",
                passed=True,
                detail=f"{len(excluded)} paths should not be committed",
            )
        )

    # ---- diff stat ----
    r_stat = ex.ssh_exec(f"cd {repo} && git diff --stat HEAD 2>/dev/null | tail -5")
    diff_stat = r_stat.stdout.strip() if r_stat.ok else ""

    # ---- tests ----
    test_summary = {"passed": None, "failed": None, "skipped": None, "raw": ""}
    if run_tests:
        r_test = ex.ssh_exec(
            f"cd {repo} && "
            f"(test -x .venv/bin/pytest && .venv/bin/pytest -q --tb=no 2>&1 || "
            f"pytest -q --tb=no 2>&1 || echo PYTEST_UNAVAILABLE)",
            timeout=300,
        )
        raw = r_test.stdout.strip()
        test_summary["raw"] = raw[-2000:] if len(raw) > 2000 else raw
        if "PYTEST_UNAVAILABLE" in raw:
            checks.append(
                CheckResult(name="pytest", passed=False, detail="pytest not available")
            )
        else:
            # parse "N passed" / "N failed"
            m_pass = re.search(r"(\d+) passed", raw)
            m_fail = re.search(r"(\d+) failed", raw)
            m_skip = re.search(r"(\d+) skipped", raw)
            test_summary["passed"] = int(m_pass.group(1)) if m_pass else 0
            test_summary["failed"] = int(m_fail.group(1)) if m_fail else 0
            test_summary["skipped"] = int(m_skip.group(1)) if m_skip else 0
            ok_tests = test_summary["failed"] == 0 and "error" not in raw.lower()[:200]
            checks.append(
                CheckResult(
                    name="pytest",
                    passed=ok_tests,
                    detail=f"passed={test_summary['passed']} failed={test_summary['failed']} "
                    f"skipped={test_summary['skipped']}",
                )
            )

    # ---- commit message draft ----
    changed = sorted(set(staged + unstaged + untracked))
    if changed:
        draft_lines = [
            f"chore: update after verification @ {head}",
            "",
            "Changed:",
            *[f"- {p}" for p in changed[:30]],
        ]
        if len(changed) > 30:
            draft_lines.append(f"- ... and {len(changed) - 30} more")
    else:
        draft_lines = [f"chore: no pending changes @ {head}"]

    commit_message_draft = "\n".join(draft_lines)

    data = {
        "branch": branch,
        "head": head,
        "staged_files": staged,
        "unstaged_files": unstaged,
        "untracked_files": untracked,
        "excluded_files": excluded,
        "diff_stat": diff_stat,
        "test_summary": test_summary,
        "commit_message_draft": commit_message_draft,
    }

    test_failed = any(c.name == "pytest" and not c.passed for c in checks)
    if test_failed:
        return fail(
            FailType.STRUCTURE,
            "pytest reported failures",
            next_action="fix failing tests before commit",
            data=data,
            checks=checks,
        )

    if not changed and not excluded:
        return ok(
            message=f"clean tree on {branch} @ {head}",
            next_action="nothing to commit; or proceed to next scientific task",
            data=data,
            checks=checks,
        )

    if excluded and not changed:
        return warning(
            message="only excluded paths dirty (smoke/results/lock); do not commit them",
            next_action="leave excluded files untracked; no delivery commit needed",
            data=data,
            checks=checks,
        )

    return ok(
        message=f"{len(changed)} deliverable path(s) on {branch} @ {head}",
        next_action="人工确认 commit message 后 git add/commit/push（不自动提交）",
        data=data,
        checks=checks,
    )
