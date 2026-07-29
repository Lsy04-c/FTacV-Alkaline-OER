"""Bridge oer-wf verification to the independent V2 archive validator."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Callable

from oer_wf.models import CheckResult


ValidateArchive = Callable[..., dict[str, Any]]
VALIDATOR_SCRIPT = Path(
    "code/python/scripts/validate_conditional_reachability.py"
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
        "_oer_wf_conditional_reachability_validator",
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
        anchors = [Path.cwd(), Path(__file__).resolve().parent]
        candidates = []
        for anchor in anchors:
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
    raise ValueError(
        "project_root not found from configured path: "
        f"{configured}"
    )


def run(
    archive_dir: Path,
    expected_files: list[str] | None = None,
    *,
    validator_config: dict[str, Any] | None = None,
) -> list[CheckResult]:
    """Run the independent validator with mode-specific rerun policy."""
    del expected_files
    cfg = validator_config or {}
    try:
        task_spec_rel = _relative_path(cfg.get("task_spec"), "task_spec")
        project_root = _resolve_project_root(
            cfg.get("project_root"),
            task_spec_rel,
        )
        task_spec = (project_root / task_spec_rel).resolve()
        if not task_spec.is_relative_to(project_root):
            raise ValueError("task_spec must remain inside project_root")
        for key in ("rerun_best_smoke", "rerun_best_formal"):
            if key in cfg and not isinstance(cfg[key], bool):
                raise ValueError(f"{key} must be boolean")
        task_spec_json = archive_dir / "task_spec.json"
        frozen = json.loads(task_spec_json.read_text(encoding="utf-8"))
        mode = frozen.get("run_mode")
        if mode not in {"smoke", "formal"}:
            raise ValueError("archive task_spec.json run_mode must be smoke or formal")
        rerun_best = bool(
            cfg.get(
                f"rerun_best_{mode}",
                mode == "formal",
            )
        )
        script_path = project_root / VALIDATOR_SCRIPT
        for path, label in (
            (project_root, "project_root"),
            (task_spec, "task_spec"),
            (script_path, "validator script"),
        ):
            exists = path.is_dir() if label == "project_root" else path.is_file()
            if not exists:
                raise ValueError(f"{label} not found: {path}")
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return _failure(
            "structure:conditional_reachability_gate_config",
            str(exc),
        )

    try:
        validate_archive = _load_validate_archive(script_path)
        result = validate_archive(
            project_root,
            task_spec,
            archive_dir.resolve(),
            rerun_best=rerun_best,
        )
    except Exception as exc:
        return _failure(
            "structure:conditional_reachability_gate",
            f"validator error: {exc}",
        )

    gate = result.get("gate")
    errors = result.get("errors")
    if not isinstance(errors, list):
        return _failure(
            "structure:conditional_reachability_gate",
            "validator result errors must be a list",
        )
    passed = gate == "PASS" and not errors
    rerun_evidence = result.get("rerun_evidence", [])
    if passed and rerun_best and (
        not isinstance(rerun_evidence, list) or len(rerun_evidence) != 4
    ):
        passed = False
        errors = [
            "formal rerun-best must provide exactly four dataset evidence rows"
        ]
    detail = (
        f"gate={gate}; mode={mode}; rerun_best={str(rerun_best).lower()}; "
        f"rerun_evidence={len(rerun_evidence) if isinstance(rerun_evidence, list) else 'invalid'}"
    )
    if errors:
        detail += "; errors: " + "; ".join(str(item) for item in errors[:12])
    return [
        CheckResult(
            name="structure:conditional_reachability_gate",
            passed=passed,
            detail=detail,
        )
    ]
