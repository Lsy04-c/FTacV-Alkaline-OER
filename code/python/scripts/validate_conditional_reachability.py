#!/usr/bin/env python3
"""Independently validate a V2 conditional-reachability archive."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.stats import qmc


REQUIRED_FILES = {
    "task_spec.json",
    "parameter_library.csv",
    "targets.json",
    "base_results.jsonl",
    "stress_results.jsonl",
    "summary.json",
    "run_manifest.json",
}
STEADY_STATE_ENDPOINTS = (5.0, 50.0, 500.0, 5000.0, 50000.0)
STEADY_STATE_RHS_MAX = 1e-8


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _json_hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} is invalid JSON") from exc


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    if raw and not raw.endswith("\n"):
        raise ValueError(f"{path.name} ends with an incomplete JSON line")
    rows = []
    for number, line in enumerate(raw.splitlines(), 1):
        if not line:
            raise ValueError(f"{path.name} has a blank line")
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name}:{number} is invalid JSON") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path.name}:{number} is not an object")
        rows.append(row)
    return rows


def _assert_finite(value: Any, location: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"non-finite value at {location}")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _assert_finite(item, f"{location}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_finite(item, f"{location}[{index}]")


def recompute_scores(
    *,
    metrics: Mapping[str, float],
    active_harmonics: Sequence[int],
    thresholds: Mapping[str, float],
) -> dict[str, Any]:
    """Duplicate the runner's tolerance-ratio scoring without importing it."""
    global_ratios = [
        float(metrics["dc_nrmse"]) / float(thresholds["dc_nrmse"])
    ]
    lockin_ratios = [
        float(thresholds["lockin_valid_fraction_min"])
        / float(metrics["lockin_valid_fraction"])
    ]
    for harmonic in active_harmonics:
        global_ratios.extend(
            [
                float(metrics[f"global_amplitude_h{harmonic}"])
                / float(thresholds["global_amplitude_relative_error"]),
                float(metrics[f"global_phase_h{harmonic}"])
                / float(thresholds["global_phase_error_rad"]),
            ]
        )
        lockin_ratios.extend(
            [
                float(metrics[f"lockin_amplitude_h{harmonic}"])
                / float(thresholds["lockin_amplitude_nrmse"]),
                float(metrics[f"lockin_phase_h{harmonic}"])
                / float(thresholds["lockin_phase_rmse_rad"]),
                float(metrics[f"lockin_peak_shift_h{harmonic}"])
                / float(thresholds["lockin_peak_shift_v"]),
            ]
        )
    if not np.all(np.isfinite(global_ratios + lockin_ratios)):
        raise ValueError("score inputs must be finite")
    global_score = max(global_ratios)
    lockin_score = max(lockin_ratios)
    return {
        "global_score": float(global_score),
        "global_passed": bool(global_score <= 1.0),
        "lockin_score": float(lockin_score),
        "lockin_passed": bool(lockin_score <= 1.0),
        "score": float(max(global_score, lockin_score)),
        "passed": bool(global_score <= 1.0 and lockin_score <= 1.0),
    }


def compare_rerun_metrics(
    archived: Mapping[str, float],
    rerun: Mapping[str, float],
) -> None:
    """Require identical component sets within the frozen rerun tolerance."""
    if set(archived) != set(rerun):
        raise ValueError("rerun metric component set mismatch")
    for name in archived:
        if not math.isclose(
            float(archived[name]),
            float(rerun[name]),
            rel_tol=1e-8,
            abs_tol=1e-8,
        ):
            raise ValueError(f"rerun metric mismatch: {name}")


def _masked_nrmse(
    candidate: Any,
    target: Any,
    mask: Any,
) -> float:
    candidate = np.asarray(candidate, dtype=float)
    target = np.asarray(target, dtype=float)
    mask = np.asarray(mask, dtype=bool)
    if candidate.shape != target.shape or candidate.shape != mask.shape:
        raise ValueError("rerun metric shapes do not match")
    if not np.any(mask):
        raise ValueError("rerun metric mask is empty")
    if not np.all(np.isfinite(candidate[mask])) or not np.all(
        np.isfinite(target[mask])
    ):
        raise ValueError("rerun metric contains non-finite valid values")
    scale = max(float(np.max(np.abs(target[mask]))), np.finfo(float).eps)
    return float(np.sqrt(np.mean((candidate[mask] - target[mask]) ** 2)) / scale)


def _rerun_feature_metrics(
    target: Mapping[str, Any],
    candidate: Mapping[str, Any],
    active_harmonics: Sequence[int],
) -> dict[str, float]:
    """Duplicate V2 feature metrics for an independent LSODA rerun."""
    grid = np.asarray(target["e_grid"], dtype=float)
    candidate_grid = np.asarray(candidate["e_grid"], dtype=float)
    if grid.shape != candidate_grid.shape or not np.allclose(
        grid, candidate_grid, rtol=0.0, atol=1e-12
    ):
        raise ValueError("rerun feature grids do not match")
    metrics = {
        "dc_nrmse": _masked_nrmse(
            candidate["dc"],
            target["dc"],
            np.ones(grid.size, dtype=bool),
        )
    }
    target_amplitude = np.asarray(
        target["complex_harmonics"]["amplitude"], dtype=float
    )
    candidate_amplitude = np.asarray(
        candidate["complex_harmonics"]["amplitude"], dtype=float
    )
    target_phase = np.asarray(
        target["complex_harmonics"]["phase"], dtype=float
    )
    candidate_phase = np.asarray(
        candidate["complex_harmonics"]["phase"], dtype=float
    )
    maximum = max(abs(float(target_amplitude[h - 1])) for h in active_harmonics)
    floor = max(0.02 * maximum, np.finfo(float).eps)
    for harmonic in active_harmonics:
        index = harmonic - 1
        metrics[f"global_amplitude_h{harmonic}"] = float(
            abs(candidate_amplitude[index] - target_amplitude[index])
            / max(abs(float(target_amplitude[index])), floor)
        )
        metrics[f"global_phase_h{harmonic}"] = float(
            abs(
                np.angle(
                    np.exp(
                        1j * (candidate_phase[index] - target_phase[index])
                    )
                )
            )
        )

    target_lockin = target["lockin"]
    candidate_lockin = candidate["lockin"]
    target_valid = np.asarray(target_lockin["valid_mask"], dtype=bool)
    candidate_valid = np.asarray(candidate_lockin["valid_mask"], dtype=bool)
    common = target_valid & candidate_valid
    metrics["lockin_valid_fraction"] = float(
        np.count_nonzero(common) / np.count_nonzero(target_valid)
    )
    for harmonic in active_harmonics:
        index = harmonic - 1
        ta = np.asarray(target_lockin["amplitude"][index], dtype=float)
        ca = np.asarray(candidate_lockin["amplitude"][index], dtype=float)
        tp = np.asarray(target_lockin["phase"][index], dtype=float)
        cp = np.asarray(candidate_lockin["phase"][index], dtype=float)
        mask = (
            common
            & np.isfinite(ta)
            & np.isfinite(ca)
            & np.isfinite(tp)
            & np.isfinite(cp)
        )
        metrics[f"lockin_amplitude_h{harmonic}"] = _masked_nrmse(
            ca, ta, mask
        )
        phase_residual = np.angle(np.exp(1j * (cp[mask] - tp[mask])))
        metrics[f"lockin_phase_h{harmonic}"] = float(
            np.sqrt(np.mean(phase_residual**2))
        )
        valid_indices = np.flatnonzero(mask)
        target_peak = valid_indices[int(np.argmax(ta[mask]))]
        candidate_peak = valid_indices[int(np.argmax(ca[mask]))]
        metrics[f"lockin_peak_shift_h{harmonic}"] = float(
            abs(grid[candidate_peak] - grid[target_peak])
        )
    return metrics


def rerun_nearest_candidates(
    root: Path,
    spec: Mapping[str, Any],
    frozen: Mapping[str, Any],
    targets_artifact: Mapping[str, Any],
    base_rows: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Rerun each archived nearest baseline candidate through the core LSODA path."""
    source_root = root / "code" / "python" / "src"
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    from oer_aem.data_contract import read_strict_experimental_trace
    from oer_aem.experimental import analyze_ftacv_trace, build_experimental_target
    from oer_aem.inversion import (
        InversionConfig,
        extract_features,
        match_experimental_sampling,
        params_from_vector,
    )
    from oer_aem.physics import OERPhysics

    if frozen["run_mode"] == "formal":
        current_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if current_commit != frozen["source_state"]["source_commit"]:
            raise ValueError("rerun commit does not match formal archive")

    fixed = tuple(
        sorted(
            (str(name), float(value))
            for name, value in spec["fixed_baseline"].items()
        )
    )
    parameter_specs = tuple(
        tuple(item) for item in spec["diagnostic_parameter_specs"]
    )
    evidence = []
    for dataset in spec["datasets"]:
        dataset_id = dataset["dataset_id"]
        nearest = summary["datasets"][dataset_id]["nearest_candidate"]
        if nearest is None:
            raise ValueError(f"nearest candidate missing for {dataset_id}")
        candidate_id = int(nearest["candidate_id"])
        archived = next(
            row
            for row in base_rows
            if row["dataset_id"] == dataset_id
            and int(row["candidate_id"]) == candidate_id
        )
        trace, _ = read_strict_experimental_trace(root / dataset["path"])
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
            solver_backend="lsoda",
        )
        target = build_experimental_target(trace, analysis, config)
        params = params_from_vector(
            archived["encoded_params"], config, parameter_specs
        )
        solution = OERPhysics.solve_ode_system_detailed(params)
        if solution.backend_used != archived["solver_backend_used"]:
            raise ValueError(f"rerun solver backend mismatch for {dataset_id}")
        features = extract_features(solution.i_total, config)
        rerun_metrics = _rerun_feature_metrics(
            target,
            features,
            targets_artifact[dataset_id]["active_harmonics"],
        )
        compare_rerun_metrics(archived["metrics"], rerun_metrics)
        evidence.append(
            {
                "dataset_id": dataset_id,
                "candidate_id": candidate_id,
                "backend_used": solution.backend_used,
                "steady_state_elapsed_s": solution.steady_state_elapsed_s,
                "steady_state_rhs_norm": solution.steady_state_rhs_norm,
            }
        )
    return evidence


def validate_steady_state_provenance(row: Mapping[str, Any]) -> None:
    """Independently validate one successful job's steady-state trace."""
    if not row.get("success"):
        return
    elapsed = float(row["steady_state_elapsed_s"])
    rhs_norm = float(row["steady_state_rhs_norm"])
    attempts = row["steady_state_attempts"]
    if elapsed not in STEADY_STATE_ENDPOINTS:
        raise ValueError("steady-state elapsed time is not a frozen endpoint")
    if not math.isfinite(rhs_norm) or rhs_norm > STEADY_STATE_RHS_MAX:
        raise ValueError("steady-state final RHS exceeds the frozen gate")
    if not isinstance(attempts, list) or not attempts:
        raise ValueError("steady-state attempts are missing")
    final = attempts[-1]
    if not math.isclose(
        float(final["elapsed_s"]), elapsed, rel_tol=0.0, abs_tol=0.0
    ) or not math.isclose(
        float(final["rhs_norm"]), rhs_norm, rel_tol=1e-12, abs_tol=1e-15
    ):
        raise ValueError("steady-state final attempt does not match summary")
    expected_prefix = list(
        STEADY_STATE_ENDPOINTS[: STEADY_STATE_ENDPOINTS.index(elapsed) + 1]
    )
    actual_endpoints = [float(item["elapsed_s"]) for item in attempts]
    if actual_endpoints != expected_prefix:
        raise ValueError("steady-state attempt endpoints are not a frozen prefix")
    for attempt in attempts:
        if attempt.get("success") is not True:
            raise ValueError("steady-state attempt reports solver failure")
        if (
            not math.isfinite(float(attempt["rhs_norm"]))
            or int(attempt["nfev"]) < 0
        ):
            raise ValueError("steady-state attempt contains invalid numerics")


def _library(spec: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray, str]:
    specs = tuple(tuple(row) for row in spec["diagnostic_parameter_specs"])
    count = int(spec["candidate_count"])
    unit = qmc.Sobol(
        d=len(specs),
        scramble=True,
        seed=int(spec["sobol_seed"]),
    ).random_base2(int(np.log2(count)))
    lows = np.array([float(row[2]) for row in specs])
    highs = np.array([float(row[3]) for row in specs])
    encoded = lows + unit * (highs - lows)
    hasher = hashlib.sha256()
    hasher.update(
        _canonical(
            {
                "specs": specs,
                "n_candidates": count,
                "seed": int(spec["sobol_seed"]),
            }
        )
    )
    hasher.update(np.asarray(unit, dtype="<f8").tobytes())
    hasher.update(np.asarray(encoded, dtype="<f8").tobytes())
    return unit, encoded, hasher.hexdigest()


def _physical(
    encoded: Sequence[float],
    specs: Sequence[Sequence[Any]],
) -> dict[str, float]:
    return {
        str(name): float(10.0**value if scale == "log10" else value)
        for value, (name, scale, _, _) in zip(encoded, specs)
    }


def _base_payload(
    dataset: Mapping[str, Any],
    candidate_id: int,
    encoded: Sequence[float],
    specs: Sequence[Sequence[Any]],
    task_hash: str,
    library_hash: str,
) -> dict[str, Any]:
    return {
        "job_id": f"base:{dataset['dataset_id']}:{candidate_id:06d}",
        "job_kind": "base",
        "dataset_id": str(dataset["dataset_id"]),
        "dataset_sha256": str(dataset["sha256"]),
        "candidate_id": candidate_id,
        "encoded_params": [float(value) for value in encoded],
        "physical_params": _physical(encoded, specs),
        "task_spec_hash": task_hash,
        "parameter_library_hash": library_hash,
    }


def expected_stress_jobs(
    spec: Mapping[str, Any],
    base_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Independently reconstruct the ranked formal stress-job set."""
    dataset_ids = []
    for row in base_rows:
        dataset_id = str(row["dataset_id"])
        if dataset_id not in dataset_ids:
            dataset_ids.append(dataset_id)
    jobs = []
    for dataset_id in dataset_ids:
        ranked = sorted(
            (
                row
                for row in base_rows
                if row["dataset_id"] == dataset_id
                and row.get("success")
                and row.get("score") is not None
            ),
            key=lambda row: (
                float(row["score"]),
                int(row["candidate_id"]),
            ),
        )[: int(spec["top_stress_candidates"])]
        for row in ranked:
            for scenario in spec["fixed_stress_scenarios"]:
                job_id = (
                    f"stress:{dataset_id}:{int(row['candidate_id']):06d}:"
                    f"{scenario['scenario_id']}"
                )
                payload = {
                    "job_id": job_id,
                    "job_kind": "stress",
                    "dataset_id": dataset_id,
                    "dataset_sha256": str(row["dataset_sha256"]),
                    "candidate_id": int(row["candidate_id"]),
                    "encoded_params": [
                        float(value) for value in row["encoded_params"]
                    ],
                    "physical_params": {
                        str(name): float(value)
                        for name, value in row["physical_params"].items()
                    },
                    "stress_scenario_id": str(scenario["scenario_id"]),
                    "stress_parameter": str(scenario["parameter"]),
                    "stress_value": float(scenario["value"]),
                    "task_spec_hash": str(row["task_spec_hash"]),
                    "parameter_library_hash": str(
                        row["parameter_library_hash"]
                    ),
                }
                jobs.append(
                    {**payload, "job_input_hash": _json_hash(payload)}
                )
    return jobs


def _classify(
    contract: bool,
    success: float,
    reached: bool,
    changed: bool,
    improvement: float,
) -> str:
    if not contract:
        return "FAIL_CONTRACT"
    if success < 0.95:
        return "INCONCLUSIVE_NUMERICAL"
    if changed:
        return "FIXED_INPUT_SENSITIVE"
    if reached:
        return "REACHED"
    if improvement > 0.10:
        return "INCONCLUSIVE_LIBRARY"
    return "NOT_REACHED_WITHIN_LIBRARY"


def _close(actual: Any, expected: Any, name: str) -> None:
    if isinstance(expected, bool):
        if actual is not expected:
            raise ValueError(f"{name} mismatch")
    elif not math.isclose(
        float(actual),
        float(expected),
        rel_tol=1e-10,
        abs_tol=1e-12,
    ):
        raise ValueError(f"{name} mismatch")


def validate_archive(
    root: str | Path,
    spec_path: str | Path,
    archive: str | Path,
    *,
    rerun_best: bool = False,
) -> dict[str, Any]:
    """Validate structure, hashes, jobs, scores and classifications."""
    root = Path(root).resolve()
    archive = Path(archive).resolve()
    errors: list[str] = []
    rerun_evidence: list[dict[str, Any]] = []
    try:
        missing = sorted(name for name in REQUIRED_FILES if not (archive / name).is_file())
        if missing:
            raise ValueError(f"missing files: {', '.join(missing)}")
        spec = _read_json(Path(spec_path))
        frozen = _read_json(archive / "task_spec.json")
        for key, value in spec.items():
            if frozen.get(key) != value:
                raise ValueError(f"frozen task spec mismatch at {key}")
        mode = frozen.get("run_mode")
        if mode not in {"smoke", "formal"}:
            raise ValueError("invalid run_mode")
        for dataset in spec["datasets"]:
            if _file_hash(root / dataset["path"]) != dataset["sha256"]:
                raise ValueError(f"raw hash mismatch for {dataset['dataset_id']}")

        unit, encoded, library_hash = _library(frozen)
        if np.any(unit.min(axis=0) > 0.02) or np.any(unit.max(axis=0) < 0.98):
            raise ValueError("Sobol boundary coverage failed")
        with (archive / "parameter_library.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            csv_rows = list(csv.DictReader(handle))
        if len(csv_rows) != int(spec["candidate_count"]):
            raise ValueError("parameter library row count mismatch")
        for index, row in enumerate(csv_rows):
            if int(row["candidate_id"]) != index:
                raise ValueError("parameter library candidate order mismatch")
            for dim, parameter in enumerate(spec["diagnostic_parameter_specs"]):
                name = parameter[0]
                _close(row[f"unit_{name}"], unit[index, dim], "unit coordinate")
                _close(
                    row[f"encoded_{name}"],
                    encoded[index, dim],
                    "encoded coordinate",
                )
        manifest = _read_json(archive / "run_manifest.json")
        if manifest["parameter_library_content_sha256"] != library_hash:
            raise ValueError("parameter library content hash mismatch")
        for name, key in (
            ("task_spec.json", "task_spec_sha256"),
            ("parameter_library.csv", "parameter_library_sha256"),
            ("targets.json", "targets_sha256"),
        ):
            if manifest[key] != _file_hash(archive / name):
                raise ValueError(f"{name} manifest hash mismatch")
        for name, digest in manifest["artifact_sha256"].items():
            if digest != _file_hash(archive / name):
                raise ValueError(f"{name} artifact hash mismatch")
        if mode == "formal" and manifest["provenance"]["dirty"]:
            raise ValueError("formal manifest is dirty")

        targets = _read_json(archive / "targets.json")
        base = _read_jsonl(archive / "base_results.jsonl")
        stress = _read_jsonl(archive / "stress_results.jsonl")
        for location, rows in (("base", base), ("stress", stress)):
            ids = [row.get("job_id") for row in rows]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate {location} job")
            for index, row in enumerate(rows):
                _assert_finite(row, f"{location}[{index}]")
                validate_steady_state_provenance(row)

        task_hash = _json_hash(frozen)
        count = int(spec["runtime"]["smoke_candidate_count"]) if mode == "smoke" else int(spec["candidate_count"])
        expected: dict[str, dict[str, Any]] = {}
        specs = spec["diagnostic_parameter_specs"]
        for dataset in spec["datasets"]:
            for candidate_id in range(count):
                payload = _base_payload(
                    dataset,
                    candidate_id,
                    encoded[candidate_id],
                    specs,
                    task_hash,
                    library_hash,
                )
                expected[payload["job_id"]] = payload
        if {row["job_id"] for row in base} != set(expected):
            raise ValueError("base job set mismatch")
        for row in base:
            payload = expected[row["job_id"]]
            if row["job_input_hash"] != _json_hash(payload):
                raise ValueError(f"job hash mismatch for {row['job_id']}")
            if any(row.get(key) != value for key, value in payload.items()):
                raise ValueError(f"base job payload mismatch for {row['job_id']}")
            if row.get("success"):
                active = targets[row["dataset_id"]]["active_harmonics"]
                scores = recompute_scores(
                    metrics=row["metrics"],
                    active_harmonics=active,
                    thresholds=spec["thresholds"],
                )
                for name, value in scores.items():
                    _close(row[name], value, f"{row['job_id']} {name}")

        summary = _read_json(archive / "summary.json")
        if mode == "smoke":
            if len(base) != 32 or stress:
                raise ValueError("smoke job counts mismatch")
            if any(
                block["scientific_classification"] is not None
                for block in summary["datasets"].values()
            ):
                raise ValueError("smoke must not contain scientific classification")
        else:
            if len(base) != 4 * 512 or len(stress) != 4 * 8 * 16:
                raise ValueError("formal job counts mismatch")
            expected_stress = {
                job["job_id"]: job for job in expected_stress_jobs(spec, base)
            }
            if {row["job_id"] for row in stress} != set(expected_stress):
                raise ValueError("formal stress job set mismatch")
            for row in stress:
                payload = expected_stress[row["job_id"]]
                if row["job_input_hash"] != payload["job_input_hash"]:
                    raise ValueError(
                        f"stress job hash mismatch for {row['job_id']}"
                    )
                if any(
                    row.get(key) != value
                    for key, value in payload.items()
                    if key != "job_input_hash"
                ):
                    raise ValueError(
                        f"stress job payload mismatch for {row['job_id']}"
                    )
                if row.get("success"):
                    scores = recompute_scores(
                        metrics=row["metrics"],
                        active_harmonics=targets[row["dataset_id"]][
                            "active_harmonics"
                        ],
                        thresholds=spec["thresholds"],
                    )
                    for name, value in scores.items():
                        _close(row[name], value, f"{row['job_id']} {name}")
            # Classification is independently reconstructed from raw rows.
            for dataset in spec["datasets"]:
                dataset_id = dataset["dataset_id"]
                rows = [row for row in base if row["dataset_id"] == dataset_id]
                successful = [row for row in rows if row.get("success")]
                reached = any(row.get("passed") for row in successful)
                success_fraction = len(successful) / len(rows)
                best_full = min(float(row["score"]) for row in successful)
                prefix = [
                    row for row in successful if int(row["candidate_id"]) < 256
                ]
                best_prefix = min(float(row["score"]) for row in prefix)
                improvement = max(0.0, best_prefix - best_full) / max(
                    abs(best_prefix), np.finfo(float).eps
                )
                scenario_reached = {
                    item["scenario_id"]: any(
                        row["dataset_id"] == dataset_id
                        and row.get("stress_scenario_id") == item["scenario_id"]
                        and row.get("passed")
                        for row in stress
                    )
                    for item in spec["fixed_stress_scenarios"]
                }
                changed = any(value != reached for value in scenario_reached.values())
                expected_class = _classify(
                    True, success_fraction, reached, changed, improvement
                )
                if (
                    summary["datasets"][dataset_id][
                        "scientific_classification"
                    ]
                    != expected_class
                ):
                    raise ValueError(
                        f"classification mismatch for {dataset_id}"
                    )
        if rerun_best:
            rerun_evidence = rerun_nearest_candidates(
                root,
                spec,
                frozen,
                targets,
                base,
                summary,
            )
    except (KeyError, TypeError, ValueError, OSError) as exc:
        errors.append(str(exc))

    gate = "PASS" if not errors else "FAIL_STRUCTURE"
    result = {
        "gate": gate,
        "errors": errors,
        "rerun_best": rerun_best,
        "rerun_evidence": rerun_evidence,
    }
    acceptance = [
        "# V2 Conditional Reachability Acceptance",
        "",
        f"- Gate: `{gate}`",
        f"- Rerun best: `{str(rerun_best).lower()}`",
    ]
    if rerun_evidence:
        acceptance.extend(
            [
                "",
                "## Rerun Evidence",
                *[
                    (
                        f"- {item['dataset_id']}: candidate "
                        f"{item['candidate_id']}, {item['backend_used']}, "
                        f"steady state {item['steady_state_elapsed_s']} s, "
                        f"RHS {item['steady_state_rhs_norm']:.6g}"
                    )
                    for item in rerun_evidence
                ],
            ]
        )
    if errors:
        acceptance.extend(["", "## Errors", *[f"- {item}" for item in errors]])
    (archive / "acceptance.md").write_text(
        "\n".join(acceptance) + "\n",
        encoding="utf-8",
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--task-spec", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--rerun-best", action="store_true")
    args = parser.parse_args(argv)
    result = validate_archive(
        args.root,
        args.task_spec,
        args.archive,
        rerun_best=args.rerun_best,
    )
    print(json.dumps(result, indent=2))
    return 0 if result["gate"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
