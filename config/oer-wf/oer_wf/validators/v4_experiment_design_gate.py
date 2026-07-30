"""Bridge oer-wf verification to the independent V4 archive validator."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Callable

from oer_wf.models import CheckResult


ValidateArchive = Callable[..., dict[str, Any]]
VALIDATOR_SCRIPT = Path(
    "code/python/scripts/validate_v4_experiment_design.py"
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
        "_oer_wf_v4_experiment_design_validator",
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
    if configured.is_absolute():
        candidates = [configured.resolve()]
    else:
        candidates = []
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
    """Run the V4 validator with mode-specific selected-rerun policy."""
    del expected_files
    cfg = validator_config or {}
    try:
        task_spec_rel = _relative_path(cfg.get("task_spec"), "task_spec")
        project_root = _resolve_project_root(
            cfg.get("project_root"),
            task_spec_rel,
        )
        task_spec = (project_root / task_spec_rel).resolve()
        for key in ("rerun_selected_smoke", "rerun_selected_formal"):
            if key in cfg and not isinstance(cfg[key], bool):
                raise ValueError(f"{key} must be boolean")
        frozen = json.loads(
            (archive_dir / "v4_task_spec.json").read_text(encoding="utf-8")
        )
        mode = frozen.get("run_mode")
        if mode not in {"smoke", "formal"}:
            raise ValueError("archive V4 run_mode must be smoke or formal")
        rerun = bool(
            cfg.get(f"rerun_selected_{mode}", mode == "formal")
        )
        script_path = project_root / VALIDATOR_SCRIPT
        if not task_spec.is_file() or not script_path.is_file():
            raise ValueError("V4 task spec or validator script not found")
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return _failure(
            "structure:v4_experiment_design_gate_config",
            str(exc),
        )

    try:
        validate_archive = _load_validate_archive(script_path)
        result = validate_archive(
            project_root,
            task_spec,
            archive_dir.resolve(),
            rerun_selected=rerun,
        )
    except Exception as exc:
        return _failure(
            "structure:v4_experiment_design_gate",
            f"validator error: {exc}",
        )
    errors = result.get("errors")
    if not isinstance(errors, list):
        return _failure(
            "structure:v4_experiment_design_gate",
            "validator errors must be a list",
        )
    evidence = result.get("rerun_evidence", [])
    status = result.get("recommendation_status")
    passed = result.get("gate") == "PASS" and not errors
    if passed and rerun:
        expected_reruns = (
            8
            if status in {"RECOMMEND_TWO", "LOCAL_LINEARITY_UNSTABLE"}
            else 0
            if status == "NO_ROBUST_RECOMMENDATION"
            else None
        )
        if (
            expected_reruns is None
            or not isinstance(evidence, list)
            or len(evidence) != expected_reruns
        ):
            passed = False
            errors = [
                "formal V4 rerun evidence count does not match "
                f"recommendation status: status={status}"
            ]
    detail = (
        f"gate={result.get('gate')}; mode={mode}; "
        f"status={status}; rerun_selected={str(rerun).lower()}; "
        f"rerun_evidence={len(evidence) if isinstance(evidence, list) else 'invalid'}"
    )
    if errors:
        detail += "; errors: " + "; ".join(str(item) for item in errors[:12])
    return [
        CheckResult(
            name="structure:v4_experiment_design_gate",
            passed=passed,
            detail=detail,
        )
    ]
