"""Bridge oer-wf verification to the pre-experiment recovery validator."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Callable

from oer_wf.models import CheckResult


ValidateArchive = Callable[..., dict[str, Any]]
VALIDATOR_SCRIPT = Path(
    "code/python/scripts/validate_pre_experiment_recovery.py"
)


def _failure(name: str, detail: str) -> list[CheckResult]:
    return [CheckResult(name=name, passed=False, detail=detail)]


def _relative_path(value: Any, name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty relative path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{name} must be a relative path without '..'")
    return path


def _load_validate_archive(script_path: Path) -> ValidateArchive:
    spec = importlib.util.spec_from_file_location(
        "_oer_wf_pre_experiment_recovery_validator",
        script_path,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load validator script: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    function = getattr(module, "validate_archive", None)
    if not callable(function):
        raise ImportError(f"validate_archive missing from {script_path}")
    return function


def _resolve_project_root(value: Any, task_spec_rel: Path) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("project_root must be a non-empty path")
    configured = Path(value).expanduser()
    candidates = [configured.resolve()] if configured.is_absolute() else []
    if not candidates:
        for anchor in (Path.cwd(), Path(__file__).resolve().parent):
            start = (anchor / configured).resolve()
            candidates.extend([start, *start.parents])
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if (
            (candidate / task_spec_rel).is_file()
            and (candidate / VALIDATOR_SCRIPT).is_file()
        ):
            return candidate
    raise ValueError(f"project_root not found from configured path: {configured}")


def run(
    archive_dir: Path,
    expected_files: list[str] | None = None,
    *,
    validator_config: dict[str, Any] | None = None,
) -> list[CheckResult]:
    del expected_files
    cfg = validator_config or {}
    try:
        task_spec_rel = _relative_path(cfg.get("task_spec"), "task_spec")
        project_root = _resolve_project_root(
            cfg.get("project_root"),
            task_spec_rel,
        )
        task_spec = (project_root / task_spec_rel).resolve()
        validate_archive = _load_validate_archive(
            project_root / VALIDATOR_SCRIPT
        )
    except (OSError, ValueError, TypeError, ImportError) as exc:
        return _failure(
            "structure:pre_experiment_recovery_gate_config",
            str(exc),
        )
    try:
        result = validate_archive(
            project_root,
            task_spec,
            archive_dir.resolve(),
        )
    except Exception as exc:
        return _failure(
            "structure:pre_experiment_recovery_gate",
            f"validator error: {exc}",
        )
    errors = result.get("errors")
    if not isinstance(errors, list):
        return _failure(
            "structure:pre_experiment_recovery_gate",
            "validator errors must be a list",
        )
    stage = result.get("stage")
    scientific = result.get("scientific_gate_passed")
    archive_valid = result.get("gate") == "PASS" and not errors
    passed = archive_valid and (stage == "S0" or scientific is True)
    name = (
        "structure:pre_experiment_recovery_gate"
        if not archive_valid
        else "scientific:pre_experiment_recovery_gate"
    )
    detail = (
        f"gate={result.get('gate')}; stage={stage}; "
        f"stage_status={result.get('stage_status')}; "
        f"eligible_pairs={len(result.get('eligible_parameter_pairs', []))}"
    )
    if errors:
        detail += "; errors: " + "; ".join(str(item) for item in errors[:12])
    return [CheckResult(name=name, passed=passed, detail=detail)]
