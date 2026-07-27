"""wf run – start a formal calculation via systemd + universal wrapper."""

from __future__ import annotations

import base64
import shlex
from pathlib import Path
from typing import Optional

from oer_wf.lock import spec_hash as compute_spec_hash

from oer_wf import config
from oer_wf.commands.prepare import load_spec
from oer_wf.models import FailType, WfResponse
from oer_wf.response import fail, ok, running
from oer_wf.runtime.command import build_command, make_output_dir
from oer_wf.transport import Executor, RealExecutor
from oer_wf.utils.systemd import (
    parse_show,
    render_unit,
    show_cmd,
    unit_name,
    unit_path_user,
)


def run_run(
    spec_path: str | Path,
    force: bool = False,
    skip_smoke: bool = False,
    executor: Optional[Executor] = None,
) -> WfResponse:
    """
    Start formal calculation.

    Rules:
      - requires worktree + matching .wf_lock (run prepare first)
      - default: reject if unit is active; reject if unit exists in
        failed/inactive unless --force
      - --force: always create a *new* timestamped output_dir; never overwrite
      - launches via universal wrapper so STATUS.json is always written
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

    main_repo = config.WSL_MAIN_REPO
    wt = spec.worktree_path(main_repo)
    unit = unit_name(spec.task_id)

    # ---- 1. worktree + lock must exist and match ----
    r_lock = ex.ssh_exec(f"test -f {wt}/.wf_lock && cat {wt}/.wf_lock || echo MISSING")
    if not r_lock.ok or "MISSING" in r_lock.stdout:
        return fail(
            FailType.STRUCTURE,
            f"worktree/lock missing: {wt}",
            next_action=f"wf prepare {spec_path}",
        )


    # ---- 1b. smoke gate (unless --skip-smoke) ----
    if not skip_smoke and spec.smoke.enabled:
        # Look for a successful smoke STATUS under results/<task>/_smoke_*
        smoke_glob = f"{wt}/{spec.output_dir}/_smoke_*/STATUS.json"
        # Use grep/python one-liner; keep quoting simple for SSH layer
        smoke_cmd = (
            "python3 - <<'PY'\n"
            "import glob, json, sys\n"
            f"files = sorted(glob.glob({smoke_glob!r}))\n"
            "ok = False\n"
            "for f in files:\n"
            "    try:\n"
            "        data = json.load(open(f))\n"
            "        st = data.get('status')\n"
            "    except Exception:\n"
            "        continue\n"
            "    if st == 'SUCCESS':\n"
            f"        if data.get('spec_hash', '') == {compute_spec_hash(spec)!r}:\n"
            "            print('OK:' + f)\n"
            "            ok = True\n"
            "            break\n"
            "        else:\n"
            "            print('HASH_MISMATCH:' + f)\n"
            "if not ok:\n"
            "    print('DONE')\n"
            "PY"
        )
        r_smoke = ex.ssh_exec(smoke_cmd)
        if not r_smoke.ok or "OK:" not in (r_smoke.stdout or ""):
            return fail(
                FailType.STRUCTURE,
                "no successful smoke STATUS found under "
                f"{wt}/{spec.output_dir}/_smoke_*/STATUS.json. "
                "Formal run is gated on smoke pass.",
                next_action=(
                    f"wf smoke {spec_path}   "
                    f"# or: wf run {spec_path} --skip-smoke (explicit bypass)"
                ),
                data={"smoke_glob": str(smoke_glob)},
            )

    # ---- 2. systemd state gate ----
    r_show = ex.ssh_exec(show_cmd(unit))
    sd = parse_show(unit, r_show.stdout if r_show.ok else "")

    if sd.is_active:
        return running(
            message=f"unit already active: {unit}",
            next_action=f"wf status {spec.task_id}",
            data={
                "task_id": spec.task_id,
                "unit": unit,
                "systemd": {"active": sd.active, "sub": sd.sub, "pid": sd.main_pid},
            },
        )

    if sd.exists and sd.is_inactive and not force:
        return fail(
            FailType.ENVIRONMENT,
            f"unit exists in state '{sd.active}/{sd.sub}'. "
            "Refuse to re-use without --force (which creates a new output dir).",
            next_action=f"wf clean {spec.task_id}   # or: wf run {spec_path} --force",
            data={"unit": unit, "active": sd.active, "sub": sd.sub},
        )

    # ---- 3. build RunPlan (new timestamp dir always) ----
    # We need a remote mkdir; construct path deterministically then create.
    # Timestamp is generated locally; collision probability is negligible.
    from oer_wf.utils.paths import timestamp_utc

    ts = timestamp_utc()
    # Probe: ensure worktree is reachable for path resolution
    r_wt = ex.ssh_exec(f"test -d {wt} && echo yes || echo no")
    if not r_wt.ok or "yes" not in r_wt.stdout:
        return fail(
            FailType.STRUCTURE,
            f"worktree directory missing: {wt}",
            next_action=f"wf prepare {spec_path}",
        )

    # Create output dir on remote
    out_rel = f"{spec.output_dir}/{ts}"
    out_abs = f"{wt}/{out_rel}"
    r_mkdir = ex.ssh_exec(f"mkdir -p {shlex.quote(out_abs)} && echo OK")
    if not r_mkdir.ok or "OK" not in r_mkdir.stdout:
        return fail(
            FailType.TRANSPORT,
            f"cannot create output dir: {out_abs}",
            next_action="check disk space / permissions",
            data={"stderr": r_mkdir.stderr},
        )

    # Local Path objects for build_command (paths are WSL-absolute strings)
    worktree_p = Path(str(wt))
    main_p = Path(str(main_repo))
    output_p = Path(out_abs)

    plan = build_command(
        spec,
        main_repo=main_p,
        worktree=worktree_p,
        output_dir=output_p,
        is_smoke=False,
    )

    # ---- 4. wrap command with universal wrapper ----
    status_file = f"{out_abs}/STATUS.json"
    # Prefer the same python that runs the script, with -m oer_wf.runtime.wrapper
    # The wrapper module must be importable on the remote. We assume oer-wf is
    # installed in the project venv, or PYTHONPATH includes it.
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

    # ---- 5. write systemd unit (user level) ----
    env = dict(plan.env)
    env["OER_WF_SPEC_HASH"] = compute_spec_hash(spec)
    env["OER_WF_TASK_ID"] = spec.task_id

    unit_body = render_unit(
        unit=unit,
        description=f"oer-wf {spec.task_id}",
        workdir=str(wt),
        exec_start=exec_start,
        env=env,
    )
    b64 = base64.b64encode(unit_body.encode("utf-8")).decode("ascii")
    unit_file = f"$HOME/.config/systemd/user/{unit}"

    r_unit = ex.ssh_exec(
        f"mkdir -p \"$HOME/.config/systemd/user\" && "
        f"echo {b64} | base64 -d > {unit_file} && "
        f"systemctl --user daemon-reload && "
        f"echo OK"
    )
    if not r_unit.ok or "OK" not in r_unit.stdout:
        return fail(
            FailType.ENVIRONMENT,
            f"failed to install unit: {r_unit.stderr.strip() or r_unit.stdout.strip()}",
            next_action="check systemd user session (loginctl enable-linger)",
            data={"stderr": r_unit.stderr},
        )

    # ---- 6. start ----
    r_start = ex.ssh_exec(f"systemctl --user start {unit} && echo STARTED")
    if not r_start.ok or "STARTED" not in r_start.stdout:
        # oneshot may finish very fast; also accept if already inactive with STATUS
        r_show2 = ex.ssh_exec(show_cmd(unit))
        sd2 = parse_show(unit, r_show2.stdout if r_show2.ok else "")
        if not sd2.is_active and sd2.result not in ("success",):
            return fail(
                FailType.ENVIRONMENT,
                f"systemctl start failed: {r_start.stderr.strip() or r_start.stdout.strip()}",
                next_action=f"wf status {spec.task_id}",
                data={"stderr": r_start.stderr, "systemd": sd2.__dict__},
            )

    return ok(
        message=f"started {spec.task_id} → {out_rel}",
        next_action=f"wf status {spec.task_id}",
        data={
            "task_id": spec.task_id,
            "unit": unit,
            "output_dir": out_abs,
            "output_rel": out_rel,
            "timestamp": ts,
            "force": force,
            "command": plan.argv,
            "wrapped": True,
        },
    )
