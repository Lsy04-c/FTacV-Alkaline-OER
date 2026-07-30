"""Bridge oer-wf verification to the independent V3 archive validator."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Callable

from oer_wf.models import CheckResult


ValidateArchive = Callable[..., dict[str, Any]]
VALIDATOR_SCRIPT = Path(
    "code/python/scripts/validate_v3_residual_attribution.py"
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
        "_oer_wf_v3_residual_validator",
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
    """Run the V3 validator with mode-specific rerun policy."""
    del expected_files
    cfg = validator_config or {}
    try:
        task_spec_rel = _relative_path(cfg.get("task_spec"), "task_spec")
        project_root = _resolve_project_root(
            cfg.get("project_root"),
            task_spec_rel,
        )
        task_spec = (project_root / task_spec_rel).resolve()
        for key in ("rerun_nearest_smoke", "rerun_nearest_formal"):
            if key in cfg and not isinstance(cfg[key], bool):
                raise ValueError(f"{key} must be boolean")
        frozen = json.loads(
            (archive_dir / "v3_task_spec.json").read_text(encoding="utf-8")
        )
        mode = frozen.get("run_mode")
        if mode not in {"smoke", "formal"}:
            raise ValueError("archive V3 run_mode must be smoke or formal")
        rerun = bool(
            cfg.get(f"rerun_nearest_{mode}", mode == "formal")
        )
        script_path = project_root / VALIDATOR_SCRIPT
        if not task_spec.is_file() or not script_path.is_file():
            raise ValueError("V3 task spec or validator script not found")
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return _failure(
            "structure:v3_residual_attribution_gate_config",
            str(exc),
        )

    try:
        validate_archive = _load_validate_archive(script_path)
        result = validate_archive(
            project_root,
            task_spec,
            archive_dir.resolve(),
            rerun_nearest=rerun,
        )
    except Exception as exc:
        return _failure(
            "structure:v3_residual_attribution_gate",
            f"validator error: {exc}",
        )
    errors = result.get("errors")
    if not isinstance(errors, list):
        return _failure(
            "structure:v3_residual_attribution_gate",
            "validator errors must be a list",
        )
    evidence = result.get("rerun_evidence", [])
    gate = str(result.get("gate"))
    passed = gate == "PASS" and not errors
    if passed and rerun and (
        not isinstance(evidence, list) or len(evidence) != 4
    ):
        passed = False
        errors = ["formal V3 rerun must provide four evidence rows"]
    detail = (
        f"gate={result.get('gate')}; mode={mode}; "
        f"rerun_nearest={str(rerun).lower()}; "
        f"rerun_evidence={len(evidence) if isinstance(evidence, list) else 'invalid'}"
    )
    if errors:
        detail += "; errors: " + "; ".join(str(item) for item in errors[:12])
    name = (
        "numerical:v3_residual_attribution_gate"
        if gate == "FAIL_NUMERICAL"
        else "scientific:v3_residual_attribution_gate"
        if gate == "FAIL_SCIENTIFIC"
        else "structure:v3_residual_attribution_gate"
    )
    return [
        CheckResult(
            name=name,
            passed=passed,
            detail=detail,
        )
    ]
