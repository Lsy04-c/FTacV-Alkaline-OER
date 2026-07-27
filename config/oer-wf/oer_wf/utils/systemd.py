"""systemd helpers shared by run / status / clean."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


def unit_name(task_id: str) -> str:
    """systemd unit name derived from task_id (replace / and .)."""
    safe = task_id.replace("/", "-").replace(".", "-")
    return f"oer-wf-{safe}.service"


def unit_path_user(task_id: str) -> str:
    """User-level unit file path (relative to ~)."""
    return f"~/.config/systemd/user/{unit_name(task_id)}"


@dataclass
class SystemdState:
    """Parsed view of a unit's lifecycle."""

    unit: str
    exists: bool
    active: str  # active | inactive | failed | activating | deactivating | unknown
    sub: str = ""  # running | dead | exited | failed | ...
    main_pid: Optional[int] = None
    result: str = ""  # success | exit-code | signal | ...
    exec_main_status: Optional[int] = None
    raw: str = ""

    @property
    def is_active(self) -> bool:
        return self.active == "active"

    @property
    def is_failed(self) -> bool:
        return self.active == "failed" or self.sub == "failed"

    @property
    def is_inactive(self) -> bool:
        return self.active in ("inactive", "failed")


def parse_show(unit: str, show_output: str) -> SystemdState:
    """Parse `systemctl --user show <unit> -p ...` output."""
    fields: dict[str, str] = {}
    for line in show_output.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            fields[k.strip()] = v.strip()

    active = fields.get("ActiveState", "unknown")
    # LoadState=not-found means unit does not exist
    load = fields.get("LoadState", "")
    exists = load not in ("not-found", "masked") and bool(show_output.strip())

    main_pid: Optional[int] = None
    if fields.get("MainPID", "0") not in ("", "0"):
        try:
            main_pid = int(fields["MainPID"])
        except ValueError:
            main_pid = None

    exec_status: Optional[int] = None
    if "ExecMainStatus" in fields:
        try:
            exec_status = int(fields["ExecMainStatus"])
        except ValueError:
            pass

    return SystemdState(
        unit=unit,
        exists=exists,
        active=active if exists else "unknown",
        sub=fields.get("SubState", ""),
        main_pid=main_pid,
        result=fields.get("Result", ""),
        exec_main_status=exec_status,
        raw=show_output,
    )


def show_cmd(unit: str) -> str:
    """Remote command to query unit state (user bus first, system fallback)."""
    props = (
        "LoadState,ActiveState,SubState,MainPID,Result,ExecMainStatus"
    )
    return (
        f"systemctl --user show {unit} -p {props} 2>/dev/null || "
        f"systemctl show {unit} -p {props} 2>/dev/null || "
        f"echo 'LoadState=not-found'"
    )


def render_unit(
    *,
    unit: str,
    description: str,
    workdir: str,
    exec_start: str,
    env: dict[str, str],
) -> str:
    """Render a simple oneshot-capable user service file."""
    env_lines = "\n".join(f"Environment={k}={v}" for k, v in env.items())
    return f"""[Unit]
Description={description}
After=network.target

[Service]
Type=oneshot
WorkingDirectory={workdir}
{env_lines}
ExecStart={exec_start}
RemainAfterExit=no
TimeoutStartSec=infinity

[Install]
WantedBy=default.target
"""
