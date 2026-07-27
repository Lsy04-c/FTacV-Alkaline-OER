"""Pydantic models for task_spec, lock, STATUS, and unified CLI response."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class StatusEnum(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    RUNNING = "running"
    INCONSISTENT = "inconsistent"


class FailType(str, Enum):
    ENVIRONMENT = "environment"
    TRANSPORT = "transport"
    STRUCTURE = "structure"
    NUMERICAL = "numerical"
    SCIENTIFIC = "scientific"
    NULL = "null"


class PythonSource(str, Enum):
    MAIN_REPO = "main_repo"
    WORKTREE = "worktree"


class ComputeStatus(str, Enum):
    """STATUS.json lifecycle states (written by the universal wrapper)."""

    STARTING = "STARTING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAIL_NUMERICAL = "FAIL_NUMERICAL"
    FAIL_INFRA = "FAIL_INFRA"


# Exit code convention used by the wrapper
EXIT_NUMERICAL = 2  # script may use this to signal FAIL_NUMERICAL


# ---------------------------------------------------------------------------
# task_spec.yaml
# ---------------------------------------------------------------------------

class PythonSpec(BaseModel):
    source: PythonSource = PythonSource.MAIN_REPO
    path: str = ".venv/bin/python"


class BuildSpec(BaseModel):
    required: bool = False
    source: str = "code/cpp"
    command: str = "cmake --build code/cpp/build --config Release"
    expected_artifact: str = "liboercn"  # platform-agnostic basename


class SmokeSpec(BaseModel):
    enabled: bool = True
    overrides: dict[str, Any] = Field(default_factory=dict)
    expected_files: list[str] = Field(
        default_factory=lambda: ["summary.csv", "manifest.json"]
    )


class TaskSpec(BaseModel):
    """Declarative task description. task_id is derived, never hand-written."""

    task_name: str
    commit: str
    description: str = ""

    python: PythonSpec = Field(default_factory=PythonSpec)
    worktree_root: str = "worktrees"
    env: dict[str, str] = Field(default_factory=dict)

    build: BuildSpec = Field(default_factory=BuildSpec)

    script: str
    args: list[str] = Field(default_factory=list)
    workers: int = 1
    output_dir: str  # relative base; actual run creates <output_dir>/<timestamp>/

    smoke: SmokeSpec = Field(default_factory=SmokeSpec)

    expected_files: list[str] = Field(
        default_factory=lambda: ["summary.csv", "manifest.json", "STATUS.json"]
    )
    validators: list[str] = Field(
        default_factory=lambda: [
            "schema_check",
            "finite_check",
            "provenance",
            "manifest_hash",
        ]
    )

    @property
    def commit_short(self) -> str:
        return self.commit[:7] if len(self.commit) >= 7 else self.commit

    @property
    def task_id(self) -> str:
        return f"{self.commit_short}/{self.task_name}"

    @field_validator("args")
    @classmethod
    def no_reserved_args(cls, v: list[str]) -> list[str]:
        reserved = {"--output", "--workers"}
        for a in v:
            if a in reserved or a.startswith("--output=") or a.startswith("--workers="):
                raise ValueError(
                    f"args must not contain reserved flags {reserved}; "
                    "wf injects --output and --workers automatically"
                )
        return v

    @staticmethod
    def _assert_relative(name: str, value: str) -> str:
        """Reject absolute paths and parent-directory escapes."""
        if not value or not str(value).strip():
            raise ValueError(f"{name} must be a non-empty relative path")
        v = str(value).strip().replace("\\", "/")
        if v.startswith("/") or (len(v) >= 2 and v[1] == ":"):
            raise ValueError(
                f"{name} must be relative to worktree root, got absolute: {value}"
            )
        parts = v.split("/")
        if ".." in parts:
            raise ValueError(f"{name} must not contain '..' path segments: {value}")
        if v.startswith("~"):
            raise ValueError(f"{name} must not start with '~': {value}")
        return value

    @field_validator("script", "output_dir", "worktree_root")
    @classmethod
    def relative_paths(cls, v: str, info):
        return cls._assert_relative(info.field_name, v)

    @field_validator("python")
    @classmethod
    def python_path_relative(cls, v: "PythonSpec") -> "PythonSpec":
        cls._assert_relative("python.path", v.path)
        return v

    @field_validator("build")
    @classmethod
    def build_paths_relative(cls, v: Optional["BuildSpec"]) -> Optional["BuildSpec"]:
        if v is not None and v.required:
            cls._assert_relative("build.source", v.source)
        return v
        return v

    def resolve_python(self, main_repo: Path, worktree: Path) -> Path:
        root = main_repo if self.python.source == PythonSource.MAIN_REPO else worktree
        return root / self.python.path

    def worktree_path(self, main_repo: Path) -> Path:
        return main_repo / self.worktree_root / self.commit_short / self.task_name


# ---------------------------------------------------------------------------
# .wf_lock
# ---------------------------------------------------------------------------

class LockInfo(BaseModel):
    task_id: str
    task_name: str
    spec_hash: str
    commit: str
    created_at: str
    worktree_path: str

    @classmethod
    def create(
        cls,
        task_id: str,
        task_name: str,
        spec_hash: str,
        commit: str,
        worktree_path: str | Path,
    ) -> "LockInfo":
        return cls(
            task_id=task_id,
            task_name=task_name,
            spec_hash=spec_hash,
            commit=commit,
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            worktree_path=str(worktree_path),
        )


# ---------------------------------------------------------------------------
# STATUS.json (written by universal wrapper)
# ---------------------------------------------------------------------------

def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class StatusFile(BaseModel):
    status: ComputeStatus
    exit_code: Optional[int] = None
    pid: Optional[int] = None
    started_at: str = Field(default_factory=_utc_now)
    finished_at: Optional[str] = None
    commit: str = ""
    task_id: str = ""
    spec_hash: Optional[str] = None
    command: list[str] = Field(default_factory=list)
    output_dir: str = ""
    error_msg: Optional[str] = None
    extra: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Unified CLI response
# ---------------------------------------------------------------------------

class CheckResult(BaseModel):
    name: str
    passed: bool
    detail: str = ""


class WfResponse(BaseModel):
    status: StatusEnum
    fail_type: FailType = FailType.NULL
    checks: list[CheckResult] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
    next_action: str = ""
    message: str = ""

    def to_json(self, **kwargs: Any) -> str:
        return self.model_dump_json(indent=2, **kwargs)
