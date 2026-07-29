#!/usr/bin/env python3
"""Run the frozen V2 conditional model-reachability study."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))

import numpy as np

from oer_aem.data_contract import read_strict_experimental_trace
from oer_aem.experimental import analyze_ftacv_trace, build_experimental_target
from oer_aem.features import wrapped_phase_difference
from oer_aem.inversion import (
    InversionConfig,
    extract_features,
    match_experimental_sampling,
    params_from_vector,
)
from oer_aem.physics import DynamicSolverError, OERPhysics
from oer_aem.reachability import (
    classify_dataset,
    generate_sobol_library,
    masked_nrmse,
    score_candidate,
    wrapped_phase_rmse,
)


OUTPUT_FILES = {
    "task_spec.json",
    "parameter_library.csv",
    "targets.json",
    "base_results.jsonl",
    "stress_results.jsonl",
    "summary.json",
    "run_manifest.json",
}

WORKFLOW_OWNED_FILES = {
    "STATUS.json",
    "task_spec.snapshot.yaml",
    "._status_signal",
}
WORKFLOW_UNTRACKED_PATHS = {".wf_lock"}
WORKFLOW_UNTRACKED_PREFIXES = ("results/",)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def load_spec(path: str | Path) -> dict[str, Any]:
    """Load and minimally validate the frozen V2 task specification."""
    source = Path(path)
    try:
        spec = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("task spec is not valid JSON") from exc
    if not isinstance(spec, dict):
        raise ValueError("task spec must contain a JSON object")
    if spec.get("schema_version") != 1:
        raise ValueError("unsupported task spec schema_version")
    if spec.get("analysis_id") != "v2-conditional-model-reachability":
        raise ValueError("unexpected analysis_id")
    if spec.get("solver_backend") != "lsoda":
        raise ValueError("V2 scientific runner requires solver_backend=lsoda")
    if spec.get("feature_mode") != "hybrid":
        raise ValueError("V2 scientific runner requires feature_mode=hybrid")
    datasets = spec.get("datasets")
    if not isinstance(datasets, list) or {
        row.get("dataset_id") for row in datasets if isinstance(row, dict)
    } != {"FT2", "FT3", "FT4", "FT8"}:
        raise ValueError("task spec must freeze FT2, FT3, FT4 and FT8")
    return spec


def _base_job(
    *,
    dataset: Mapping[str, Any],
    candidate_id: int,
    encoded: Sequence[float],
    physical: Mapping[str, float],
    task_spec_hash: str,
    parameter_library_hash: str,
) -> dict[str, Any]:
    job_id = f"base:{dataset['dataset_id']}:{candidate_id:06d}"
    payload = {
        "job_id": job_id,
        "job_kind": "base",
        "dataset_id": str(dataset["dataset_id"]),
        "dataset_sha256": str(dataset["sha256"]),
        "candidate_id": int(candidate_id),
        "encoded_params": [float(value) for value in encoded],
        "physical_params": {
            str(name): float(value) for name, value in physical.items()
        },
        "task_spec_hash": task_spec_hash,
        "parameter_library_hash": parameter_library_hash,
    }
    return {**payload, "job_input_hash": _sha256_json(payload)}


def build_job_plan(
    spec: Mapping[str, Any],
    *,
    smoke: bool,
) -> dict[str, Any]:
    """Build the deterministic base-job prefix for smoke or formal execution."""
    candidate_count = (
        int(spec["runtime"]["smoke_candidate_count"])
        if smoke
        else int(spec["candidate_count"])
    )
    library = generate_sobol_library(
        tuple(tuple(row) for row in spec["diagnostic_parameter_specs"]),
        int(spec["candidate_count"]),
        seed=int(spec["sobol_seed"]),
    )
    task_spec_hash = _sha256_json(spec)
    base_jobs = [
        _base_job(
            dataset=dataset,
            candidate_id=candidate_id,
            encoded=library.encoded[candidate_id],
            physical=library.physical[candidate_id],
            task_spec_hash=task_spec_hash,
            parameter_library_hash=library.sha256,
        )
        for dataset in spec["datasets"]
        for candidate_id in range(candidate_count)
    ]
    return {
        "smoke": bool(smoke),
        "task_spec_hash": task_spec_hash,
        "parameter_library_hash": library.sha256,
        "parameter_library": library,
        "base_jobs": base_jobs,
        "stress_jobs": [],
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    if raw and not raw.endswith("\n"):
        raise ValueError(f"{path.name} ends with an incomplete JSON line")
    rows = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line:
            raise ValueError(f"{path.name} contains a blank JSON line")
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{path.name} contains invalid JSON at line {line_number}"
            ) from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path.name} line {line_number} is not an object")
        rows.append(row)
    return rows


def load_resume_state(
    output: str | Path,
    expected_jobs: Sequence[Mapping[str, Any]],
    *,
    result_files: Sequence[str] = (
        "base_results.jsonl",
        "stress_results.jsonl",
    ),
) -> dict[str, dict[str, Any]]:
    """Load completed rows only when files, IDs and input hashes are exact."""
    directory = Path(output)
    unknown = sorted(
        path.name
        for path in directory.iterdir()
        if path.name not in OUTPUT_FILES | WORKFLOW_OWNED_FILES
    )
    if unknown:
        raise ValueError(f"unknown output files: {', '.join(unknown)}")
    expected = {
        str(job["job_id"]): str(job["job_input_hash"])
        for job in expected_jobs
    }
    rows_by_id: dict[str, dict[str, Any]] = {}
    for name in result_files:
        path = directory / name
        if not path.exists():
            continue
        for row in _read_jsonl(path):
            job_id = str(row.get("job_id", ""))
            if job_id not in expected:
                raise ValueError(f"unknown job_id in resume data: {job_id!r}")
            if job_id in rows_by_id:
                raise ValueError(f"duplicate job_id in resume data: {job_id}")
            if row.get("job_input_hash") != expected[job_id]:
                raise ValueError(f"job hash mismatch for {job_id}")
            rows_by_id[job_id] = row
    return rows_by_id


def compute_feature_match(
    target: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    active_harmonics: Sequence[int],
    thresholds: Mapping[str, float],
) -> dict[str, Any]:
    """Compute the frozen two-stage component metrics for one candidate."""
    harmonics = tuple(sorted({int(value) for value in active_harmonics}))
    if not harmonics or any(value < 1 for value in harmonics):
        raise ValueError("at least one positive active harmonic is required")
    target_grid = np.asarray(target["e_grid"], dtype=float).reshape(-1)
    candidate_grid = np.asarray(candidate["e_grid"], dtype=float).reshape(-1)
    if (
        target_grid.shape != candidate_grid.shape
        or not np.allclose(target_grid, candidate_grid, rtol=0.0, atol=1e-12)
    ):
        raise ValueError("target and candidate feature grids must match")

    metrics: dict[str, float] = {
        "dc_nrmse": masked_nrmse(
            np.asarray(candidate["dc"], dtype=float),
            np.asarray(target["dc"], dtype=float),
            np.ones(target_grid.size, dtype=bool),
        )
    }
    target_global_amplitude = np.asarray(
        target["complex_harmonics"]["amplitude"],
        dtype=float,
    )
    candidate_global_amplitude = np.asarray(
        candidate["complex_harmonics"]["amplitude"],
        dtype=float,
    )
    target_global_phase = np.asarray(
        target["complex_harmonics"]["phase"],
        dtype=float,
    )
    candidate_global_phase = np.asarray(
        candidate["complex_harmonics"]["phase"],
        dtype=float,
    )
    max_active_amplitude = max(
        abs(float(target_global_amplitude[harmonic - 1]))
        for harmonic in harmonics
    )
    amplitude_floor = max(
        0.02 * max_active_amplitude,
        np.finfo(float).eps,
    )

    global_thresholds = {"dc_nrmse": float(thresholds["dc_nrmse"])}
    for harmonic in harmonics:
        index = harmonic - 1
        denominator = max(
            abs(float(target_global_amplitude[index])),
            amplitude_floor,
        )
        amplitude_name = f"global_amplitude_h{harmonic}"
        phase_name = f"global_phase_h{harmonic}"
        metrics[amplitude_name] = float(
            abs(
                candidate_global_amplitude[index]
                - target_global_amplitude[index]
            )
            / denominator
        )
        metrics[phase_name] = float(
            abs(
                wrapped_phase_difference(
                    candidate_global_phase[index],
                    target_global_phase[index],
                )
            )
        )
        global_thresholds[amplitude_name] = float(
            thresholds["global_amplitude_relative_error"]
        )
        global_thresholds[phase_name] = float(
            thresholds["global_phase_error_rad"]
        )

    target_lockin = target["lockin"]
    candidate_lockin = candidate["lockin"]
    target_valid = np.asarray(
        target_lockin["valid_mask"],
        dtype=bool,
    ).reshape(-1)
    candidate_valid = np.asarray(
        candidate_lockin["valid_mask"],
        dtype=bool,
    ).reshape(-1)
    if target_valid.shape != target_grid.shape or candidate_valid.shape != (
        target_grid.shape
    ):
        raise ValueError("lock-in valid masks must match the feature grid")
    target_valid_count = int(np.count_nonzero(target_valid))
    if target_valid_count < 2:
        raise ValueError("target lock-in block has insufficient valid points")

    lockin_thresholds: dict[str, float] = {
        "lockin_valid_fraction_min": float(
            thresholds["lockin_valid_fraction_min"]
        )
    }
    common_valid = target_valid & candidate_valid
    metrics["lockin_valid_fraction"] = float(
        np.count_nonzero(common_valid) / target_valid_count
    )
    for harmonic in harmonics:
        index = harmonic - 1
        target_amplitude = np.asarray(
            target_lockin["amplitude"][index],
            dtype=float,
        )
        candidate_amplitude = np.asarray(
            candidate_lockin["amplitude"][index],
            dtype=float,
        )
        target_phase = np.asarray(
            target_lockin["phase"][index],
            dtype=float,
        )
        candidate_phase = np.asarray(
            candidate_lockin["phase"][index],
            dtype=float,
        )
        finite_mask = (
            common_valid
            & np.isfinite(target_amplitude)
            & np.isfinite(candidate_amplitude)
            & np.isfinite(target_phase)
            & np.isfinite(candidate_phase)
        )
        if np.count_nonzero(finite_mask) < 1:
            raise ValueError(
                f"lock-in H{harmonic} has no valid target-candidate intersection"
            )
        amplitude_name = f"lockin_amplitude_h{harmonic}"
        phase_name = f"lockin_phase_h{harmonic}"
        peak_name = f"lockin_peak_shift_h{harmonic}"
        metrics[amplitude_name] = masked_nrmse(
            candidate_amplitude,
            target_amplitude,
            finite_mask,
        )
        metrics[phase_name] = wrapped_phase_rmse(
            candidate_phase,
            target_phase,
            finite_mask,
        )
        valid_indices = np.flatnonzero(finite_mask)
        target_peak = valid_indices[
            int(np.argmax(target_amplitude[finite_mask]))
        ]
        candidate_peak = valid_indices[
            int(np.argmax(candidate_amplitude[finite_mask]))
        ]
        metrics[peak_name] = float(
            abs(target_grid[candidate_peak] - target_grid[target_peak])
        )
        lockin_thresholds[amplitude_name] = float(
            thresholds["lockin_amplitude_nrmse"]
        )
        lockin_thresholds[phase_name] = float(
            thresholds["lockin_phase_rmse_rad"]
        )
        lockin_thresholds[peak_name] = float(
            thresholds["lockin_peak_shift_v"]
        )

    global_score = score_candidate(metrics, global_thresholds)
    lockin_score = score_candidate(metrics, lockin_thresholds)
    return {
        "metrics": metrics,
        "global_score": global_score.score,
        "global_passed": global_score.passed,
        "lockin_score": lockin_score.score,
        "lockin_passed": lockin_score.passed,
        "score": max(global_score.score, lockin_score.score),
        "passed": global_score.passed and lockin_score.passed,
        "limiting_metrics": sorted(
            set(
                global_score.limiting_metrics
                if global_score.score >= lockin_score.score
                else lockin_score.limiting_metrics
            )
        ),
    }


def _serialize(value: Any) -> Any:
    if isinstance(value, complex):
        return {"real": float(value.real), "imag": float(value.imag)}
    if isinstance(value, np.complexfloating):
        return {"real": float(value.real), "imag": float(value.imag)}
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.ndarray):
        return [_serialize(item) for item in value.tolist()]
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _serialize(item) for key, item in value.items()}
    return value


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_text(
        path,
        json.dumps(
            _serialize(value),
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
    )


def _atomic_jsonl(
    path: Path,
    rows_by_id: Mapping[str, Mapping[str, Any]],
    planned_ids: Sequence[str],
) -> None:
    lines = [
        json.dumps(
            _serialize(rows_by_id[job_id]),
            ensure_ascii=False,
            allow_nan=False,
        )
        for job_id in planned_ids
        if job_id in rows_by_id
    ]
    _atomic_text(path, "".join(f"{line}\n" for line in lines))


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _is_workflow_untracked_path(path: str) -> bool:
    return path in WORKFLOW_UNTRACKED_PATHS or path.startswith(
        WORKFLOW_UNTRACKED_PREFIXES
    )


def classify_git_status(status_porcelain_z: str) -> dict[str, Any]:
    """Ignore only untracked runtime artifacts; preserve all source changes."""
    dirty_paths: list[str] = []
    ignored_workflow_paths: list[str] = []
    fields = status_porcelain_z.split("\0")
    index = 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        if not entry:
            continue
        if len(entry) < 4 or entry[2] != " ":
            raise ValueError(f"malformed git status entry: {entry!r}")
        status = entry[:2]
        path = entry[3:]
        if "R" in status or "C" in status:
            if index >= len(fields) or not fields[index]:
                raise ValueError(
                    f"missing source path for git status: {entry!r}"
                )
            old_path = fields[index]
            index += 1
            dirty_paths.append(f"{old_path} -> {path}")
        elif status == "??" and _is_workflow_untracked_path(path):
            ignored_workflow_paths.append(path)
        else:
            dirty_paths.append(path)
    return {
        "dirty": bool(dirty_paths),
        "dirty_paths": dirty_paths,
        "ignored_workflow_paths": ignored_workflow_paths,
    }


def _git_provenance() -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    if isinstance(status, bytes):
        status = status.decode("utf-8", errors="surrogateescape")
    classified = classify_git_status(status)
    dirty_paths = list(classified["dirty_paths"])
    content_hasher = hashlib.sha256()
    for relative in sorted(dirty_paths):
        content_hasher.update(relative.encode("utf-8", errors="surrogateescape"))
        path = ROOT / relative
        if path.is_file():
            content_hasher.update(b"\0file\0")
            content_hasher.update(path.read_bytes())
        elif path.is_dir():
            content_hasher.update(b"\0directory\0")
            for child in sorted(item for item in path.rglob("*") if item.is_file()):
                child_relative = child.relative_to(ROOT).as_posix()
                content_hasher.update(
                    child_relative.encode("utf-8", errors="surrogateescape")
                )
                content_hasher.update(b"\0")
                content_hasher.update(child.read_bytes())
        else:
            content_hasher.update(b"\0missing\0")
    return {
        "source_commit": commit,
        "dirty": classified["dirty"],
        "dirty_paths": sorted(dirty_paths),
        "ignored_workflow_paths": sorted(
            classified["ignored_workflow_paths"]
        ),
        "dirty_content_sha256": (
            content_hasher.hexdigest() if dirty_paths else None
        ),
    }


def _freeze_run_spec(
    spec: Mapping[str, Any],
    *,
    smoke: bool,
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind a run contract to the exact source state used by its jobs."""
    return {
        **dict(spec),
        "run_mode": "smoke" if smoke else "formal",
        "source_state": {
            "source_commit": str(provenance["source_commit"]),
            "dirty": bool(provenance["dirty"]),
            "dirty_paths": list(provenance.get("dirty_paths", [])),
            "ignored_workflow_paths": list(
                provenance.get("ignored_workflow_paths", [])
            ),
            "dirty_content_sha256": provenance.get(
                "dirty_content_sha256"
            ),
        },
    }


def _target_artifact(
    analysis: Mapping[str, Any],
    target: Mapping[str, Any],
    active_harmonics: Sequence[int],
) -> dict[str, Any]:
    lockin = target["lockin"]
    complex_block = target["complex_harmonics"]
    valid = np.asarray(lockin["valid_mask"], dtype=bool).reshape(-1)

    def nullable_channels(channels: Sequence[Any]) -> list[list[float | None]]:
        encoded = []
        for channel in channels:
            values = np.asarray(channel, dtype=float).reshape(-1)
            if values.shape != valid.shape:
                raise ValueError("lock-in target channel shape mismatch")
            if not np.all(np.isfinite(values[valid])):
                raise ValueError("lock-in target is non-finite in its valid region")
            encoded.append(
                [
                    float(value) if is_valid else None
                    for value, is_valid in zip(values, valid)
                ]
            )
        return encoded

    return {
        "meta": analysis["meta"],
        "active_harmonics": [int(value) for value in active_harmonics],
        "e_grid": target["e_grid"],
        "dc": target["dc"],
        "complex_harmonics": {
            "amplitude": complex_block["amplitude"],
            "phase": complex_block["phase"],
            "snr": complex_block["snr"],
        },
        "lockin": {
            "amplitude": nullable_channels(lockin["amplitude"]),
            "phase": nullable_channels(lockin["phase"]),
            "valid_mask": valid,
            "fc_used": lockin["fc_used"],
            "effective_resolution_v": lockin["effective_resolution_v"],
        },
    }


def build_targets(
    spec: Mapping[str, Any],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, InversionConfig],
    dict[str, dict[str, Any]],
]:
    """Build in-memory targets/configs plus their JSON-safe evidence block."""
    targets: dict[str, dict[str, Any]] = {}
    configs: dict[str, InversionConfig] = {}
    artifacts: dict[str, dict[str, Any]] = {}
    fixed = tuple(
        sorted(
            (str(name), float(value))
            for name, value in spec["fixed_baseline"].items()
        )
    )
    parameter_specs = tuple(
        tuple(row) for row in spec["diagnostic_parameter_specs"]
    )
    for dataset in spec["datasets"]:
        path = ROOT / str(dataset["path"])
        if _sha256_file(path) != dataset["sha256"]:
            raise ValueError(
                f"raw data hash mismatch for {dataset['dataset_id']}"
            )
        trace, _ = read_strict_experimental_trace(path)
        analysis = analyze_ftacv_trace(trace)
        n_points, points_per_cycle = match_experimental_sampling(
            float(analysis["meta"]["duration"]),
            float(analysis["meta"]["f"]),
            points_per_cycle=int(spec["points_per_cycle"]),
        )
        config = InversionConfig(
            E_start=float(analysis["meta"]["E_start"]),
            E_end=float(analysis["meta"]["E_end"]),
            f=float(analysis["meta"]["f"]),
            dE=float(analysis["meta"]["dE"]),
            n_points=n_points,
            points_per_cycle=points_per_cycle,
            feature_grid_size=int(spec["feature_grid_size"]),
            discard_fraction=float(spec["discard_fraction"]),
            fixed_params=fixed,
            param_specs=parameter_specs,
            fit_harmonics=tuple(int(h) for h in spec["fit_harmonics"]),
            feature_mode=str(spec["feature_mode"]),
            solver_backend=str(spec["solver_backend"]),
        )
        target = build_experimental_target(trace, analysis, config)
        snr = np.asarray(
            target["complex_harmonics"]["snr"],
            dtype=float,
        )
        active = tuple(
            harmonic
            for harmonic in config.fit_harmonics
            if snr[harmonic - 1] > config.snr_floor
        )
        if not active:
            raise ValueError(
                f"no active H1-H3 channel for {dataset['dataset_id']}"
            )
        dataset_id = str(dataset["dataset_id"])
        targets[dataset_id] = target
        configs[dataset_id] = config
        artifacts[dataset_id] = _target_artifact(
            analysis,
            target,
            active,
        )
    return targets, configs, artifacts


def _attempt_rows(attempts: Sequence[Any]) -> list[dict[str, Any]]:
    return [
        (
            asdict(attempt)
            if hasattr(attempt, "__dataclass_fields__")
            else dict(vars(attempt))
        )
        for attempt in attempts
    ]


def _classify_exception(exc: Exception) -> str:
    if isinstance(exc, RuntimeError) and "steady-state" in str(exc).lower():
        return "ODE_INITIALIZATION"
    return "FEATURE_OR_CONTRACT"


def evaluate_job(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Worker entry point for one base or fixed-input stress solve."""
    job = dict(payload["job"])
    config: InversionConfig = payload["config"]
    target = payload["target"]
    active_harmonics = tuple(payload["active_harmonics"])
    thresholds = payload["thresholds"]
    started = time.perf_counter()
    attempts: list[dict[str, Any]] = []
    try:
        params = params_from_vector(
            job["encoded_params"],
            config,
            config.param_specs,
        )
        solution = OERPhysics.solve_ode_system_detailed(params)
        attempts = _attempt_rows(solution.attempts)
        features = extract_features(solution.i_total, config)
        match = compute_feature_match(
            target,
            features,
            active_harmonics=active_harmonics,
            thresholds=thresholds,
        )
        return {
            **job,
            "success": True,
            "failure_kind": None,
            "failure_message": None,
            "solver_attempts": attempts,
            "solver_backend_used": solution.backend_used,
            "solver_fallback_used": bool(solution.fallback_used),
            "steady_state_elapsed_s": solution.steady_state_elapsed_s,
            "steady_state_rhs_norm": solution.steady_state_rhs_norm,
            "steady_state_attempts": _attempt_rows(
                solution.steady_state_attempts
            ),
            "runtime_seconds": time.perf_counter() - started,
            **match,
        }
    except DynamicSolverError as exc:
        attempts = _attempt_rows(exc.attempts)
        steady_state_elapsed_s = exc.steady_state_elapsed_s
        steady_state_rhs_norm = exc.steady_state_rhs_norm
        steady_state_attempts = _attempt_rows(exc.steady_state_attempts)
        failure_kind = "ODE"
        message = str(exc)
    except Exception as exc:  # noqa: BLE001
        steady_state_elapsed_s = None
        steady_state_rhs_norm = None
        steady_state_attempts = []
        failure_kind = _classify_exception(exc)
        message = f"{type(exc).__name__}: {exc}"
    return {
        **job,
        "success": False,
        "failure_kind": failure_kind,
        "failure_message": message,
        "solver_attempts": attempts,
        "solver_backend_used": None,
        "solver_fallback_used": None,
        "steady_state_elapsed_s": steady_state_elapsed_s,
        "steady_state_rhs_norm": steady_state_rhs_norm,
        "steady_state_attempts": steady_state_attempts,
        "runtime_seconds": time.perf_counter() - started,
        "metrics": None,
        "global_score": None,
        "global_passed": False,
        "lockin_score": None,
        "lockin_passed": False,
        "score": None,
        "passed": False,
        "limiting_metrics": [],
    }


def _iter_results(
    payloads: Sequence[Mapping[str, Any]],
    *,
    workers: int,
):
    if workers <= 1:
        for payload in payloads:
            yield evaluate_job(payload)
        return
    with ProcessPoolExecutor(
        max_workers=min(int(workers), len(payloads))
    ) as executor:
        futures = {
            executor.submit(evaluate_job, payload): payload["job"]["job_id"]
            for payload in payloads
        }
        for future in as_completed(futures):
            yield future.result()


def _run_jobs(
    *,
    jobs: Sequence[Mapping[str, Any]],
    existing: dict[str, dict[str, Any]],
    result_path: Path,
    targets: Mapping[str, Mapping[str, Any]],
    configs: Mapping[str, InversionConfig],
    target_artifacts: Mapping[str, Mapping[str, Any]],
    thresholds: Mapping[str, float],
    workers: int,
) -> tuple[dict[str, dict[str, Any]], int]:
    planned_ids = [str(job["job_id"]) for job in jobs]
    remaining = [job for job in jobs if job["job_id"] not in existing]
    payloads = []
    for job in remaining:
        dataset_id = str(job["dataset_id"])
        config = configs[dataset_id]
        if job["job_kind"] == "stress":
            fixed = dict(config.fixed_params)
            fixed[str(job["stress_parameter"])] = float(job["stress_value"])
            config = InversionConfig(
                **{
                    **config.__dict__,
                    "fixed_params": tuple(sorted(fixed.items())),
                }
            )
        payloads.append(
            {
                "job": job,
                "target": targets[dataset_id],
                "config": config,
                "active_harmonics": target_artifacts[dataset_id][
                    "active_harmonics"
                ],
                "thresholds": thresholds,
            }
        )
    executed = 0
    for row in _iter_results(payloads, workers=workers):
        job_id = str(row["job_id"])
        if job_id in existing or job_id not in planned_ids:
            raise ValueError(f"worker returned invalid job_id: {job_id}")
        existing[job_id] = row
        executed += 1
        _atomic_jsonl(result_path, existing, planned_ids)
    return existing, executed


def _stress_jobs(
    spec: Mapping[str, Any],
    base_jobs: Sequence[Mapping[str, Any]],
    base_rows: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_dataset: dict[str, list[Mapping[str, Any]]] = {}
    for job in base_jobs:
        row = base_rows[str(job["job_id"])]
        if row.get("success") and row.get("score") is not None:
            by_dataset.setdefault(str(job["dataset_id"]), []).append(row)
    jobs: list[dict[str, Any]] = []
    for dataset in spec["datasets"]:
        dataset_id = str(dataset["dataset_id"])
        ranked = sorted(
            by_dataset.get(dataset_id, []),
            key=lambda row: (float(row["score"]), int(row["candidate_id"])),
        )
        selected = ranked[: int(spec["top_stress_candidates"])]
        if len(selected) != int(spec["top_stress_candidates"]):
            continue
        for row in selected:
            for scenario in spec["fixed_stress_scenarios"]:
                job_id = (
                    f"stress:{dataset_id}:{int(row['candidate_id']):06d}:"
                    f"{scenario['scenario_id']}"
                )
                payload = {
                    "job_id": job_id,
                    "job_kind": "stress",
                    "dataset_id": dataset_id,
                    "dataset_sha256": str(dataset["sha256"]),
                    "candidate_id": int(row["candidate_id"]),
                    "encoded_params": list(row["encoded_params"]),
                    "physical_params": dict(row["physical_params"]),
                    "stress_scenario_id": str(scenario["scenario_id"]),
                    "stress_parameter": str(scenario["parameter"]),
                    "stress_value": float(scenario["value"]),
                    "task_spec_hash": str(row["task_spec_hash"]),
                    "parameter_library_hash": str(
                        row["parameter_library_hash"]
                    ),
                }
                jobs.append(
                    {**payload, "job_input_hash": _sha256_json(payload)}
                )
    return jobs


def _prefix_improvement(rows: Sequence[Mapping[str, Any]]) -> float:
    successful = [
        row
        for row in rows
        if row.get("success") and row.get("score") is not None
    ]
    prefix = [
        row for row in successful if int(row["candidate_id"]) < 256
    ]
    if not successful or not prefix:
        return 0.0
    best_full = min(float(row["score"]) for row in successful)
    best_prefix = min(float(row["score"]) for row in prefix)
    return float(
        max(0.0, best_prefix - best_full)
        / max(abs(best_prefix), np.finfo(float).eps)
    )


def build_summary(
    *,
    spec: Mapping[str, Any],
    smoke: bool,
    base_rows: Sequence[Mapping[str, Any]],
    stress_rows: Sequence[Mapping[str, Any]],
    workers: int,
    duration_seconds: float,
    reused_jobs: int,
    executed_jobs: int,
) -> dict[str, Any]:
    datasets: dict[str, Any] = {}
    for dataset in spec["datasets"]:
        dataset_id = str(dataset["dataset_id"])
        base = [
            row for row in base_rows if row["dataset_id"] == dataset_id
        ]
        stress = [
            row for row in stress_rows if row["dataset_id"] == dataset_id
        ]
        successful = [row for row in base if row.get("success")]
        reached = any(bool(row.get("passed")) for row in successful)
        nearest = (
            min(
                successful,
                key=lambda row: (
                    float(row["score"]),
                    int(row["candidate_id"]),
                ),
            )
            if successful
            else None
        )
        success_fraction = len(successful) / max(len(base), 1)
        improvement = _prefix_improvement(base) if not smoke else None
        scenario_reached = {
            scenario["scenario_id"]: any(
                row.get("stress_scenario_id") == scenario["scenario_id"]
                and bool(row.get("passed"))
                for row in stress
            )
            for scenario in spec["fixed_stress_scenarios"]
        }
        stress_changed = (
            any(value != reached for value in scenario_reached.values())
            if not smoke
            else None
        )
        classification = (
            None
            if smoke
            else classify_dataset(
                contract_valid=True,
                ode_success_fraction=success_fraction,
                baseline_reached=reached,
                stress_changed=bool(stress_changed),
                prefix_improvement=float(improvement),
            )
        )
        datasets[dataset_id] = {
            "scientific_classification": classification,
            "base_job_count": len(base),
            "stress_job_count": len(stress),
            "ode_success_fraction": success_fraction,
            "baseline_reached": reached,
            "prefix_improvement": improvement,
            "stress_changed": stress_changed,
            "stress_scenario_reached": (
                None if smoke else scenario_reached
            ),
            "nearest_candidate": (
                None
                if nearest is None
                else {
                    "candidate_id": int(nearest["candidate_id"]),
                    "score": float(nearest["score"]),
                    "passed": bool(nearest["passed"]),
                }
            ),
        }
    expected_base = len(spec["datasets"]) * (
        int(spec["runtime"]["smoke_candidate_count"])
        if smoke
        else int(spec["candidate_count"])
    )
    expected_stress = (
        0
        if smoke
        else len(spec["datasets"])
        * int(spec["top_stress_candidates"])
        * len(spec["fixed_stress_scenarios"])
    )
    complete = (
        len(base_rows) == expected_base
        and len(stress_rows) == expected_stress
    )
    return {
        "schema_version": 1,
        "analysis_id": spec["analysis_id"],
        "run_mode": "smoke" if smoke else "formal",
        "structure_complete": complete,
        "scientific_classification_enabled": not smoke,
        "datasets": datasets,
        "base_job_count": len(base_rows),
        "stress_job_count": len(stress_rows),
        "workers": int(workers),
        "duration_seconds": float(duration_seconds),
        "reused_jobs": int(reused_jobs),
        "executed_jobs": int(executed_jobs),
    }


def _write_parameter_library(
    path: Path,
    plan: Mapping[str, Any],
    spec: Mapping[str, Any],
) -> None:
    library = plan["parameter_library"]
    specs = [
        tuple(row)
        for row in spec["diagnostic_parameter_specs"]
    ]
    rows = []
    for candidate_id, (unit, encoded, physical) in enumerate(
        zip(library.unit, library.encoded, library.physical)
    ):
        row: dict[str, Any] = {"candidate_id": candidate_id}
        for index, (name, _, _, _) in enumerate(specs):
            row[f"unit_{name}"] = float(unit[index])
            row[f"encoded_{name}"] = float(encoded[index])
            row[f"physical_{name}"] = float(physical[name])
        rows.append(row)
    fieldnames = list(rows[0])
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _prepare_output(
    output: Path,
    *,
    resume: bool,
) -> None:
    if output.exists() and not output.is_dir():
        raise ValueError("output path exists and is not a directory")
    output.mkdir(parents=True, exist_ok=True)
    unexpected = [
        path for path in output.iterdir()
        if path.name not in WORKFLOW_OWNED_FILES
    ]
    if not resume and unexpected:
        raise ValueError("output directory is not empty; use --resume")


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.workers < 1:
        raise ValueError("--workers must be positive")
    spec = load_spec(args.task_spec)
    output = args.output.resolve()
    _prepare_output(output, resume=args.resume)
    provenance = _git_provenance()
    if not args.smoke and provenance["dirty"]:
        raise ValueError("formal V2 execution requires a clean git worktree")
    for variable in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ[variable] = "1"

    frozen_spec = _freeze_run_spec(
        spec,
        smoke=args.smoke,
        provenance=provenance,
    )
    plan = build_job_plan(frozen_spec, smoke=args.smoke)
    targets, configs, target_artifacts = build_targets(spec)
    task_spec_path = output / "task_spec.json"
    targets_path = output / "targets.json"
    parameter_path = output / "parameter_library.csv"
    if args.resume:
        if not task_spec_path.exists() or not targets_path.exists():
            raise ValueError("resume requires task_spec.json and targets.json")
        existing_spec = json.loads(task_spec_path.read_text(encoding="utf-8"))
        existing_targets = json.loads(targets_path.read_text(encoding="utf-8"))
        if _sha256_json(existing_spec) != _sha256_json(frozen_spec):
            raise ValueError("resume task spec hash mismatch")
        if _sha256_json(existing_targets) != _sha256_json(
            _serialize(target_artifacts)
        ):
            raise ValueError("resume target hash mismatch")
    else:
        _atomic_json(task_spec_path, frozen_spec)
        _atomic_json(targets_path, target_artifacts)
        _write_parameter_library(parameter_path, plan, spec)

    started = time.perf_counter()
    base_jobs = plan["base_jobs"]
    base_existing = (
        load_resume_state(
            output,
            base_jobs,
            result_files=("base_results.jsonl",),
        )
        if args.resume
        else {}
    )
    reused = len(base_existing)
    base_existing, base_executed = _run_jobs(
        jobs=base_jobs,
        existing=base_existing,
        result_path=output / "base_results.jsonl",
        targets=targets,
        configs=configs,
        target_artifacts=target_artifacts,
        thresholds=spec["thresholds"],
        workers=args.workers,
    )

    stress_jobs = [] if args.smoke else _stress_jobs(
        spec,
        base_jobs,
        base_existing,
    )
    stress_existing = (
        load_resume_state(
            output,
            stress_jobs,
            result_files=("stress_results.jsonl",),
        )
        if args.resume and stress_jobs
        else {}
    )
    reused += len(stress_existing)
    stress_executed = 0
    if stress_jobs:
        stress_existing, stress_executed = _run_jobs(
            jobs=stress_jobs,
            existing=stress_existing,
            result_path=output / "stress_results.jsonl",
            targets=targets,
            configs=configs,
            target_artifacts=target_artifacts,
            thresholds=spec["thresholds"],
            workers=args.workers,
        )
    else:
        _atomic_jsonl(output / "stress_results.jsonl", {}, ())

    base_rows = [base_existing[job["job_id"]] for job in base_jobs]
    stress_rows = [
        stress_existing[job["job_id"]] for job in stress_jobs
    ]
    summary = build_summary(
        spec=spec,
        smoke=args.smoke,
        base_rows=base_rows,
        stress_rows=stress_rows,
        workers=args.workers,
        duration_seconds=time.perf_counter() - started,
        reused_jobs=reused,
        executed_jobs=base_executed + stress_executed,
    )
    _atomic_json(output / "summary.json", summary)
    manifest = {
        "schema_version": 1,
        "analysis_id": spec["analysis_id"],
        "run_mode": "smoke" if args.smoke else "formal",
        "provenance": {
            **provenance,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "command": [sys.executable, *sys.argv]
            if argv is None
            else [sys.executable, *argv],
        },
        "task_spec_sha256": _sha256_file(task_spec_path),
        "parameter_library_sha256": _sha256_file(parameter_path),
        "targets_sha256": _sha256_file(targets_path),
        "artifact_sha256": {
            name: _sha256_file(output / name)
            for name in (
                "base_results.jsonl",
                "stress_results.jsonl",
                "summary.json",
            )
        },
        "parameter_library_content_sha256": plan[
            "parameter_library_hash"
        ],
    }
    _atomic_json(output / "run_manifest.json", manifest)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
