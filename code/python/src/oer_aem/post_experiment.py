"""Build a reproducible, non-inverting target bundle from collected FTacV data."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .data_contract import read_strict_experimental_trace
from .experiment_intake import validate_intake
from .experimental import analyze_ftacv_trace, build_experimental_target
from .inversion import InversionConfig


REQUIRED_INDEPENDENT_INPUT_GROUPS = {
    "Ru": ("Ru",),
    "CdlA": ("CdlA", "Cdl"),
    "A": ("A", "geometric_area"),
    "GammaA": ("GammaA", "active_site_amount"),
    "load": ("load", "catalyst_loading"),
}

# This is a policy-level record, deliberately separate from a future task's
# concrete fixed values.  It makes the bundle's intended scientific role
# visible without pretending that a target bundle itself authorizes inversion.
CURRENT_A6_ROLE_POLICY = {
    "schema_version": 1,
    "policy_id": "a6-current-stiff-coordinate-v1",
    "free_parameters": ["k0_2", "k0_3", "G_OH", "G_O"],
    "fixed_parameters": [
        "A",
        "Cdl",
        "Ru",
        "E0_pre",
        "k0_1",
        "k0_4",
        "k0_pre",
        "scaling_OOH_OH",
        "gamma",
        "a",
    ],
    "diagnostic_parameters": [],
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _code_provenance(root: Path) -> dict[str, str | bool | None]:
    """Record the checked-out source identity when the supplied root is Git."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain=v1"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return {"source_commit": None, "dirty": None}
    return {"source_commit": commit or None, "dirty": bool(status)}


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def build_post_experiment_bundle(
    project_root: str | Path,
    manifest_path: str | Path,
    output_dir: str | Path,
    *,
    feature_mode: str = "hybrid",
) -> dict[str, Any]:
    """Validate intake and materialize targets without starting inversion.

    A non-ready intake produces a deterministic waiting/failed summary and no
    scientific arrays.  Raw files are read only; output is a new directory.
    """
    root = Path(project_root).resolve()
    manifest_file = Path(manifest_path).resolve()
    output = Path(output_dir).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"bundle output must be empty: {output}")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    intake = validate_intake(root, manifest)
    independent = manifest.get("independent_inputs", {})
    missing_inputs = []
    for canonical, aliases in REQUIRED_INDEPENDENT_INPUT_GROUPS.items():
        records = [independent.get(name) for name in aliases] if isinstance(independent, Mapping) else []
        if not any(
            isinstance(record, Mapping)
            and record.get("value") is not None
            and record.get("independent_of_ftacv") is True
            for record in records
        ):
            missing_inputs.append(canonical)
    if intake["status"] == "READY_FOR_A1_AUDIT" and missing_inputs:
        intake = dict(intake)
        intake["status"] = "WAITING_FOR_INDEPENDENT_INPUT"
        intake["next_action"] = "collect_independent_inputs"
        intake["missing_independent_inputs"] = missing_inputs
    manifest_hash = _sha256(manifest_file)
    role_policy = dict(CURRENT_A6_ROLE_POLICY)
    base = {
        "schema_version": 1,
        "status": intake["status"],
        "next_action": intake["next_action"],
        "intake": intake,
        "source_manifest": manifest_file.relative_to(root).as_posix(),
        "source_manifest_sha256": manifest_hash,
        "feature_mode": feature_mode,
        "parameter_role_policy": role_policy,
        "parameter_role_policy_sha256": _canonical_sha256(role_policy),
        "code_provenance": _code_provenance(root),
        "datasets": [],
    }
    output.mkdir(parents=True, exist_ok=True)
    if intake["status"] != "READY_FOR_A1_AUDIT":
        (output / "bundle_summary.json").write_text(
            json.dumps(base, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return base

    arrays: dict[str, np.ndarray] = {}
    for dataset in manifest["datasets"]:
        if dataset.get("collection_state") != "collected":
            continue
        condition_id = str(dataset["condition_id"])
        raw_path = root / str(dataset["raw_file"]["path"])
        trace, facts = read_strict_experimental_trace(raw_path)
        analysis = analyze_ftacv_trace(trace)
        meta = analysis["meta"]
        points_per_cycle = max(1, int(round(len(trace.time) / (meta["duration"] * meta["f"]))))
        config = InversionConfig(
            n_points=len(trace.time),
            points_per_cycle=points_per_cycle,
            feature_grid_size=min(2048, max(128, len(trace.time) // 4)),
            fit_harmonics=tuple(int(n) for n in analysis["suggested_fit_harmonics"] if int(n) <= 3),
            feature_mode=feature_mode,
            f=float(meta["f"]),
            dE=float(meta["dE"]),
            E_start=float(meta["E_start"]),
            E_end=float(meta["E_end"]),
        )
        target = build_experimental_target(trace, analysis, config)
        arrays[f"{condition_id}__e_grid"] = np.asarray(target["e_grid"], dtype=float)
        arrays[f"{condition_id}__dc"] = np.asarray(target["dc"], dtype=float)
        for index, harmonic in enumerate(target["harm"], start=1):
            arrays[f"{condition_id}__h{index}"] = np.asarray(harmonic, dtype=float)
        base["datasets"].append(
            {
                "dataset_id": dataset["dataset_id"],
                "condition_id": condition_id,
                "analysis_role": dataset["analysis_role"],
                "raw_file": dataset["raw_file"]["path"],
                "raw_sha256": facts.sha256,
                "analysis": _jsonable(analysis),
                "target_keys": sorted(key for key in arrays if key.startswith(condition_id + "__")),
            }
        )

    np.savez_compressed(output / "targets.npz", **arrays)
    base["status"] = "TARGET_BUNDLE_READY"
    base["next_action"] = "run_new_batch_a1_audit_before_inversion"
    base["array_sha256"] = _sha256(output / "targets.npz")
    (output / "bundle_summary.json").write_text(
        json.dumps(base, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return base
