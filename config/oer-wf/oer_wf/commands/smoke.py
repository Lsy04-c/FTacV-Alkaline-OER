"""wf smoke – constrained formal run + structural acceptance.

Reuses the same RunPlan + universal wrapper as `wf run`.
Only applies smoke.overrides (sample size etc.); scientific config is unchanged.
"""

from __future__ import annotations

import base64
import json
import shlex
import time
from pathlib import Path
from typing import Any, Optional

from oer_wf import config
from oer_wf.commands.prepare import load_spec
from oer_wf.lock import spec_hash as compute_spec_hash
from oer_wf.models import CheckResult, FailType, WfResponse
from oer_wf.response import fail, ok, warning
from oer_wf.runtime.command import build_command
from oer_wf.transport import Executor, RealExecutor
from oer_wf.utils.paths import timestamp_utc
from oer_wf.utils.systemd import parse_show, render_unit, show_cmd, unit_name


# Keys that must NEVER appear in smoke overrides (scientific risk).
# Enforcement is soft-fail with explicit message; expand as needed.
# Allow-list approach would be ideal; until task_spec declares
# smoke_safe_keys, we block any key that looks scientific / structural.
_FORBIDDEN_OVERRIDE_KEYS = {
    # solvers / numerics core
    "solver", "solver_backend", "solver_method", "integrator", "ode_solver",
    "lsoda", "cvode", "radau", "bdf", "rk45",
    # grid / discretization
    "grid", "mesh", "points_per_cycle", "n_points", "n_grid", "grid_size",
    "dt", "time_step", "timestep", "delta_t",
    # model / physics
    "model", "physics", "equation", "mechanism", "feature_mode", "features",
    "kinetics", "thermo", "transport_model",
    # parameter classification / priors
    "free_params", "fixed_params", "prior", "priors", "bounds",
    "param_names", "parameters",
    # objective / likelihood structure
    "objective", "likelihood", "loss", "metric",
    # random seed only allowed if explicitly in allow list later
}


def _unit_name_smoke(task_id: str) -> str:
    """Separate unit so smoke never collides with formal run unit."""
    base = unit_name(task_id).removesuffix(".service")
    return f"{base}-smoke.service"


def _check_forbidden_overrides(overrides: dict[str, Any]) -> list[str]:
    bad = []
    # Only these keys are considered safe for smoke size reduction
    _SAFE_PREFIXES = (
        "n_samples", "n_sample", "max_steps", "max_step", "max_iter",
        "max_evals", "timeout", "dry_run", "debug", "verbose", "n_jobs",
        "workers",  # note: workers still injected by wf; override here is blocked at args level
        "max_profiles", "grid_points",  # runtime controls, not scientific
    )
    for k in overrides:
        key = k.lstrip("-").lower().replace("-", "_")
        if key in _FORBIDDEN_OVERRIDE_KEYS:
            bad.append(k)
            continue
        # Block anything not on the safe prefix list (default-deny for unknown keys)
        if not any(key == s or key.startswith(s + "_") for s in _SAFE_PREFIXES):
            bad.append(k)
    return bad


def _structural_checks(
    ex: Executor,
    output_dir: str,
    expected_files: list[str],
) -> list[CheckResult]:
    """Lightweight structural acceptance after smoke finishes."""
    checks: list[CheckResult] = []

    # 1. expected files present
    for name in expected_files:
        r = ex.ssh_exec(f"test -f {shlex.quote(output_dir + '/' + name)} && echo yes || echo no")
        ok_file = r.ok and "yes" in r.stdout
        checks.append(
            CheckResult(
                name=f"file:{name}",
                passed=ok_file,
                detail="present" if ok_file else "missing",
            )
        )

    # 2. STATUS.json terminal + SUCCESS preferred
    r_st = ex.ssh_exec(f"cat {shlex.quote(output_dir + '/STATUS.json')} 2>/dev/null || echo MISSING")
    if not r_st.ok or "MISSING" in r_st.stdout:
        checks.append(CheckResult(name="status_json", passed=False, detail="missing"))
    else:
        try:
            data = json.loads(r_st.stdout.strip())
            st = data.get("status")
            if st == "SUCCESS":
                checks.append(CheckResult(name="status_json", passed=True, detail="SUCCESS"))
            elif st in ("FAIL_NUMERICAL", "FAIL_INFRA"):
                checks.append(
                    CheckResult(
                        name="status_json",
                        passed=False,
                        detail=f"{st}: {data.get('error_msg') or ''}",
                    )
                )
            else:
                checks.append(
                    CheckResult(name="status_json", passed=False, detail=f"non-terminal: {st}")
                )
        except json.JSONDecodeError as e:
            checks.append(CheckResult(name="status_json", passed=False, detail=f"corrupt: {e}"))

    # 3. optional schema hint: summary.csv has header line
    if any(f.endswith(".csv") for f in expected_files):
        csv_name = next(f for f in expected_files if f.endswith(".csv"))
        r_csv = ex.ssh_exec(
            f"test -f {shlex.quote(output_dir + '/' + csv_name)} && "
            f"head -1 {shlex.quote(output_dir + '/' + csv_name)} || echo NOHEADER"
        )
        if r_csv.ok and r_csv.stdout.strip() and "NOHEADER" not in r_csv.stdout:
            checks.append(
                CheckResult(
                    name="csv_header",
                    passed=True,
                    detail=r_csv.stdout.strip()[:80],
                )
            )
        else:
            checks.append(CheckResult(name="csv_header", passed=False, detail="no header"))

    return checks


def run_smoke(
    spec_path: str | Path,
    *,
    timeout_sec: int = 600,
    poll_interval: float = 2.0,
    executor: Optional[Executor] = None,
) -> WfResponse:
    """
    Run smoke as a constrained formal execution:

      1. require worktree + lock
      2. reject forbidden scientific overrides
      3. build RunPlan(is_smoke=True) → _smoke_<ts> dir
      4. launch via wrapper + dedicated smoke systemd unit
      5. poll until terminal STATUS or timeout
      6. structural checks (expected_files, STATUS, csv header)
    """
    ex = executor or RealExecutor()

    try:
        spec = load_spec(spec_path)
    except Exception as e:
        return fail(
            FailType.STRUCTURE,
            f"invalid task_spec: {e}",
            next_action="fix the YAML schema",
        )

    if not spec.smoke.enabled:
        return fail(
            FailType.STRUCTURE,
            "smoke.enabled is false in task_spec",
            next_action="enable smoke or skip this step",
        )

    bad = _check_forbidden_overrides(spec.smoke.overrides)
    if bad:
        return fail(
            FailType.SCIENTIFIC,
            f"smoke.overrides contains forbidden scientific keys: {bad}. "
            "Smoke may only change sample size / step limits etc.",
            next_action="remove scientific keys from smoke.overrides",
        )

    main_repo = config.WSL_MAIN_REPO
    wt = spec.worktree_path(main_repo)
    unit = _unit_name_smoke(spec.task_id)

    # ---- lock required ----
    r_lock = ex.ssh_exec(f"test -f {wt}/.wf_lock && cat {wt}/.wf_lock || echo MISSING")
    if not r_lock.ok or "MISSING" in r_lock.stdout:
        return fail(
            FailType.STRUCTURE,
            f"worktree/lock missing: {wt}",
            next_action=f"wf prepare {spec_path}",
        )

    # ---- refuse if smoke unit already active ----
    r_show = ex.ssh_exec(show_cmd(unit))
    sd = parse_show(unit, r_show.stdout if r_show.ok else "")
    if sd.is_active:
        return fail(
            FailType.ENVIRONMENT,
            f"smoke unit already active: {unit}",
            next_action=f"systemctl --user stop {unit}; or wait",
            data={"unit": unit},
        )

    # ---- output dir ----
    ts = timestamp_utc()
    out_abs = f"{wt}/{spec.output_dir}/_smoke_{ts}"
    r_mkdir = ex.ssh_exec(f"mkdir -p {shlex.quote(out_abs)} && echo OK")
    if not r_mkdir.ok or "OK" not in r_mkdir.stdout:
        return fail(
            FailType.TRANSPORT,
            f"cannot create smoke output dir: {out_abs}",
            data={"stderr": r_mkdir.stderr},
        )

    worktree_p = Path(str(wt))
    main_p = Path(str(main_repo))
    output_p = Path(out_abs)

    plan = build_command(
        spec,
        main_repo=main_p,
        worktree=worktree_p,
        output_dir=output_p,
        is_smoke=True,
    )

    status_file = f"{out_abs}/STATUS.json"
    wrap_argv = [
        str(plan.python),
        "-m",
        "oer_wf.runtime.wrapper",
        "--status-file",
        status_file,
        "--task-id",
        plan.task_id,
        "--commit",
        plan.commit_short,
        "--output-dir",
        str(plan.output_dir),
        "--",
        *plan.argv,
    ]
    exec_start = " ".join(shlex.quote(a) for a in wrap_argv)

    env = dict(plan.env)
    env["OER_WF_SPEC_HASH"] = compute_spec_hash(spec)
    env["OER_WF_TASK_ID"] = spec.task_id

    unit_body = render_unit(
        unit=unit,
        description=f"oer-wf smoke {spec.task_id}",
        workdir=str(wt),
        exec_start=exec_start,
        env=env,
    )
    b64 = base64.b64encode(unit_body.encode("utf-8")).decode("ascii")
    unit_file = f"$HOME/.config/systemd/user/{unit}"

    r_unit = ex.ssh_exec(
        f"mkdir -p \"$HOME/.config/systemd/user\" && "
        f"echo {b64} | base64 -d > {unit_file} && "
        f"systemctl --user daemon-reload && echo OK"
    )
    if not r_unit.ok or "OK" not in r_unit.stdout:
        return fail(
            FailType.ENVIRONMENT,
            f"failed to install smoke unit: {r_unit.stderr.strip() or r_unit.stdout.strip()}",
            next_action="check systemd user session",
        )

    r_start = ex.ssh_exec(f"systemctl --user start {unit}; echo RC:$?")
    # oneshot may finish before start returns; do not hard-fail on non-zero yet

    # ---- poll STATUS until terminal or timeout ----
    deadline = time.time() + timeout_sec
    last_status = None
    while time.time() < deadline:
        r_st = ex.ssh_exec(
            f"cat {shlex.quote(status_file)} 2>/dev/null || echo __MISSING__"
        )
        if r_st.ok and "__MISSING__" not in r_st.stdout:
            try:
                data = json.loads(r_st.stdout.strip())
                last_status = data.get("status")
                if last_status in ("SUCCESS", "FAIL_NUMERICAL", "FAIL_INFRA"):
                    break
            except json.JSONDecodeError:
                pass
        # also check if unit is fully dead with no STATUS yet
        r_show2 = ex.ssh_exec(show_cmd(unit))
        sd2 = parse_show(unit, r_show2.stdout if r_show2.ok else "")
        if not sd2.is_active and last_status is None:
            # brief grace for STATUS flush
            time.sleep(0.5)
            r_st2 = ex.ssh_exec(
                f"cat {shlex.quote(status_file)} 2>/dev/null || echo __MISSING__"
            )
            if r_st2.ok and "__MISSING__" not in r_st2.stdout:
                try:
                    data = json.loads(r_st2.stdout.strip())
                    last_status = data.get("status")
                except json.JSONDecodeError:
                    pass
            break
        time.sleep(poll_interval)

    if last_status is None:
        return fail(
            FailType.ENVIRONMENT,
            f"smoke timed out or STATUS never appeared after {timeout_sec}s",
            next_action=f"journalctl --user -u {unit} -n 50",
            data={"output_dir": out_abs, "unit": unit},
        )

    if last_status != "SUCCESS":
        return fail(
            FailType.NUMERICAL if last_status == "FAIL_NUMERICAL" else FailType.ENVIRONMENT,
            f"smoke finished with {last_status}",
            next_action="fix smoke overrides / script; do not proceed to formal run",
            data={"output_dir": out_abs, "status": last_status, "unit": unit},
        )

    # ---- structural acceptance ----
    expected = list(spec.smoke.expected_files)
    if "STATUS.json" not in expected:
        expected = expected + ["STATUS.json"]
    checks = _structural_checks(ex, out_abs, expected)
    hard_fail = [c for c in checks if not c.passed and c.name.startswith("file:")]
    status_fail = [c for c in checks if c.name == "status_json" and not c.passed]

    if hard_fail or status_fail:
        return fail(
            FailType.STRUCTURE,
            "smoke structural checks failed: "
            + ", ".join(c.name for c in hard_fail + status_fail),
            next_action="fix expected_files / script output; do not proceed to formal run",
            data={"output_dir": out_abs, "checks": [c.model_dump() for c in checks]},
            checks=checks,
        )

    soft = [c for c in checks if not c.passed]
    if soft:
        return warning(
            message="smoke passed with warnings: " + ", ".join(c.name for c in soft),
            next_action=f"wf run {spec_path}",
            data={
                "output_dir": out_abs,
                "task_id": spec.task_id,
                "overrides": plan.overrides,
                "checks": [c.model_dump() for c in checks],
            },
            checks=checks,
        )

    return ok(
        message=f"smoke passed: {out_abs}",
        next_action=f"wf run {spec_path}",
        data={
            "output_dir": out_abs,
            "task_id": spec.task_id,
            "overrides": plan.overrides,
            "unit": unit,
            "checks": [c.model_dump() for c in checks],
        },
        checks=checks,
    )
