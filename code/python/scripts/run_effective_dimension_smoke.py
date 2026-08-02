#!/usr/bin/env python3
"""Run a development-only multi-anchor effective-dimension smoke study."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))

from oer_aem.anchor_design import generate_parameter_anchors
from oer_aem.anchor_design import (
    inactive_direction_probe_points,
    unit_coordinates_to_parameters,
)
from oer_aem.defaults import initialize_oer_parameters
from oer_aem.identifiability import (
    coordinate_scales_from_schema,
    decompose_importance_reports,
    estimate_diagonal_feature_stability,
    matrix_from_importance,
    select_candidate_dimension,
    subspace_alignment_diagnostics,
    subspace_residual_diagnostics,
    whiten_sensitivity,
)
from oer_aem.importance import (
    _run_forward,
    analyze_parameter_importance,
    feature_scale_vector_from_rows,
    feature_vector_from_rows,
)
from oer_aem.inversion import InversionConfig
from oer_aem.inversion import encode_params, extract_features, forward_current


SCHEMA_PATH = (
    ROOT / "config" / "parameter-schemas" / "m0-total-current-effective-v1.json"
)
PARAMETER_NAMES = (
    "k0_1",
    "k0_2",
    "k0_3",
    "k0_4",
    "G_OH",
    "G_O",
    "scaling_OOH_OH",
)
DEFAULT_ANCHOR_SEED = 17
NOISE_SEED_POOL = (
    101, 103, 107, 109, 113, 127, 131, 137, 139, 149, 151, 157,
    163, 167, 173, 179, 181, 191, 193, 197, 199, 211, 223, 227,
    229, 233, 239, 241, 251, 257, 263, 269, 271, 277, 281, 283,
    293, 307, 311, 313, 317, 331, 337, 347, 349, 353, 359, 367,
)
NONSMOOTH_EXCLUDED_FEATURES = ("Tafel", "onset")
SMOOTH_INCLUDED_FEATURES = (
    "DC shape",
    "Complex H1 real",
    "Complex H1 imag",
    "Complex H2 real",
    "Complex H2 imag",
    "Complex H3 real",
    "Complex H3 imag",
    "Lockin H1 real",
    "Lockin H1 imag",
    "Lockin H2 real",
    "Lockin H2 imag",
    "Lockin H3 real",
    "Lockin H3 imag",
)


def _feature_block(row_name: str) -> str:
    return re.sub(r"\[\d+\]$", "", str(row_name))


def block_balanced_noise_proxy(feature_names: Sequence[str]) -> np.ndarray:
    """Give every retained feature block equal aggregate proxy weight."""

    blocks = [_feature_block(name) for name in feature_names]
    counts = {block: blocks.count(block) for block in set(blocks)}
    return np.asarray([np.sqrt(counts[block]) for block in blocks], dtype=float)


def _smooth_report(
    report: Mapping[str, object],
    observed_feature_names: Sequence[str] | None = None,
) -> dict[str, object]:
    filtered = dict(report)
    observed = (
        None
        if observed_feature_names is None
        else {str(name) for name in observed_feature_names}
    )
    for key in (
        "signed_feature_sensitivity_matrix",
        "feature_sensitivity_matrix",
    ):
        if key in filtered:
            filtered[key] = [
                row
                for row in filtered[key]
                if _feature_block(str(row.get("feature")))
                in SMOOTH_INCLUDED_FEATURES
                and (observed is None or str(row.get("feature")) in observed)
            ]
    return filtered


def structurally_observed_feature_names(
    config: object,
    feature_names: Sequence[str],
    *,
    feature_extractor=extract_features,
) -> tuple[list[str], list[str]]:
    """Freeze rows observable under the acquisition and lock-in geometry."""

    geometry = feature_extractor(np.zeros(int(config.n_points), dtype=float), config)
    lockin = geometry.get("lockin")
    if not isinstance(lockin, Mapping):
        return [str(name) for name in feature_names], []
    valid = np.asarray(lockin.get("valid_mask"), dtype=bool).reshape(-1)
    if valid.size == 0:
        raise ValueError("lock-in valid mask must not be empty")
    included = []
    excluded = []
    for raw_name in feature_names:
        name = str(raw_name)
        match = re.fullmatch(r"Lockin H\d+ (?:real|imag)\[(\d+)\]", name)
        if match and (
            int(match.group(1)) >= valid.size or not valid[int(match.group(1))]
        ):
            excluded.append(name)
        else:
            included.append(name)
    return included, excluded


def feature_vector_from_current(
    current: np.ndarray,
    config: object,
    feature_names: Sequence[str],
    *,
    feature_extractor=extract_features,
) -> np.ndarray:
    """Extract the frozen smooth feature rows from one current trace."""

    features = feature_extractor(current, config)
    if "complex_harmonics" in features:
        coefficients = np.asarray(
            features["complex_harmonics"]["complex"], dtype=complex
        )
        for harmonic in config.fit_harmonics:
            coefficient = coefficients[harmonic - 1]
            features[f"Complex H{harmonic} real"] = float(coefficient.real)
            features[f"Complex H{harmonic} imag"] = float(coefficient.imag)
    if "lockin" in features:
        valid = np.asarray(features["lockin"]["valid_mask"], dtype=bool)
        channels = features["lockin"]["complex"]
        for harmonic in config.fit_harmonics:
            channel = np.asarray(channels[harmonic - 1], dtype=complex)
            features[f"Lockin H{harmonic} real"] = np.where(
                valid, channel.real, 0.0
            )
            features[f"Lockin H{harmonic} imag"] = np.where(
                valid, channel.imag, 0.0
            )
    return feature_vector_from_rows(features, feature_names)


def feature_block_scales(
    feature_names: Sequence[str],
    vector: np.ndarray,
) -> np.ndarray:
    """Return baseline maxima matching signed-sensitivity block scaling."""

    values = np.asarray(vector, dtype=float).reshape(-1)
    if values.shape != (len(feature_names),) or not np.all(np.isfinite(values)):
        raise ValueError("feature vector must match the frozen row contract")
    blocks = [_feature_block(name) for name in feature_names]
    maxima = {
        block: max(
            float(np.max(np.abs(values[np.asarray(blocks) == block]))),
            1e-30,
        )
        for block in set(blocks)
    }
    return np.asarray([maxima[block] for block in blocks], dtype=float)


def _schema_parameter_specs(
    schema: Mapping[str, object],
    parameter_names: Sequence[str],
) -> tuple[tuple[str, str, float, float], ...]:
    entries = schema.get("parameters")
    if not isinstance(entries, Mapping):
        raise ValueError("parameter schema must contain parameters")
    specs = []
    for name in parameter_names:
        entry = entries.get(name)
        if not isinstance(entry, Mapping):
            raise ValueError(f"parameter {name} is missing from schema")
        bounds = entry.get("bounds")
        if not isinstance(bounds, Sequence) or len(bounds) != 2:
            raise ValueError(f"parameter {name} bounds are unresolved")
        lower, upper = float(bounds[0]), float(bounds[1])
        transform = str(entry.get("transform"))
        if transform == "log10":
            if lower <= 0.0:
                raise ValueError(f"parameter {name} log10 bounds must be positive")
            lower, upper = float(np.log10(lower)), float(np.log10(upper))
        elif transform != "linear":
            raise ValueError(f"parameter {name} transform is unsupported")
        specs.append((str(name), transform, lower, upper))
    return tuple(specs)


def estimate_anchor_stability_scales(
    records: Sequence[Mapping[str, object]],
    schema: Mapping[str, object],
    *,
    parameter_names: Sequence[str],
    feature_names: Sequence[str],
    config: object,
    noise_fraction: float,
    noise_seeds: Sequence[int],
    current_runner=None,
    feature_vector_runner=feature_vector_from_current,
) -> tuple[dict[str, np.ndarray], dict[str, object]]:
    """Estimate a diagonal quantization-stability scale at every anchor."""

    specs = _schema_parameter_specs(schema, parameter_names)

    def default_current_runner(params, current_config):
        encoded = encode_params(params, specs)
        return forward_current(encoded, current_config, specs)

    simulate = current_runner or default_current_runner
    scales: dict[str, np.ndarray] = {}
    audit_rows = []
    for record in records:
        anchor_id = str(record["anchor_id"])
        params = unit_coordinates_to_parameters(
            schema,
            parameter_names,
            np.asarray(record["unit_coordinates"], dtype=float),
        )
        current = simulate(params, config)
        if current is None:
            raise ValueError(f"anchor {anchor_id} baseline current failed")
        current_values = np.asarray(current, dtype=float).reshape(-1)
        baseline = feature_vector_runner(
            current_values, config, feature_names
        )
        block_scales = feature_block_scales(feature_names, baseline)
        stability = estimate_diagonal_feature_stability(
            current_values,
            feature_extractor=lambda noisy, frozen=block_scales: (
                feature_vector_runner(noisy, config, feature_names) / frozen
            ),
            noise_fraction=noise_fraction,
            seeds=noise_seeds,
        )
        scales[anchor_id] = stability.standard_deviations
        audit_rows.append(
            {
                "anchor_id": anchor_id,
                "split": str(record["split"]),
                "current_sigma": stability.current_sigma,
                "minimum_feature_standard_deviation": float(
                    np.min(stability.standard_deviations)
                ),
                "maximum_feature_standard_deviation": float(
                    np.max(stability.standard_deviations)
                ),
            }
        )
    return scales, {
        "model": "diagonal_feature_stability_from_quantization_floor",
        "distribution": "uniform_quantization_error",
        "noise_fraction": float(noise_fraction),
        "noise_seeds": [int(seed) for seed in noise_seeds],
        "anchors": audit_rows,
        "limitation": (
            "Quantization-resolution propagation only; not repeatability "
            "uncertainty and not a full feature covariance."
        ),
    }


def decompose_training_reports(
    records: Sequence[Mapping[str, object]],
    schema: Mapping[str, object],
    *,
    stability_scales: Mapping[str, np.ndarray] | None = None,
    observed_feature_names: Sequence[str] | None = None,
) -> dict[str, object]:
    """Fit directions on training anchors without viewing other splits."""

    training = [record for record in records if record.get("split") == "train"]
    if not training:
        raise ValueError("at least one training anchor is required")
    for record in training:
        report = record.get("report")
        if not isinstance(report, Mapping) or report.get("success") is False:
            raise ValueError(f"training anchor {record.get('anchor_id')} failed")
    reports = [
        _smooth_report(record["report"], observed_feature_names)
        for record in training
    ]
    feature_names, parameter_names, first_matrix = matrix_from_importance(reports[0])
    if stability_scales is None:
        noise_models = [block_balanced_noise_proxy(feature_names) for _ in reports]
        noise_model_name = "block_balanced_stability_proxy_not_formal_covariance"
    else:
        noise_models = [
            np.asarray(stability_scales[str(record["anchor_id"])], dtype=float)
            for record in training
        ]
        noise_model_name = "diagonal_quantization_stability_floor"
    scales = coordinate_scales_from_schema(schema, parameter_names)
    scale_vector = np.asarray(list(scales.values()), dtype=float)
    training_matrices = [
        matrix_from_importance(report)[2] * scale_vector[None, :]
        for report in reports
    ]
    feature_names, parameter_names, result = decompose_importance_reports(
        reports,
        noise_models,
        column_scales_to_unit_coordinates=scales,
    )
    if first_matrix.shape[0] != len(feature_names):
        raise ValueError("training feature matrix shape drift")
    selection = [
        record for record in records if record.get("split") == "selection"
    ]
    selection_matrices = []
    for record in selection:
        report = record.get("report")
        if not isinstance(report, Mapping) or report.get("success") is False:
            raise ValueError(f"selection anchor {record.get('anchor_id')} failed")
        current_features, current_parameters, matrix = matrix_from_importance(
            _smooth_report(report, observed_feature_names)
        )
        if current_features != feature_names or current_parameters != parameter_names:
            raise ValueError(
                f"selection anchor {record.get('anchor_id')} contract drift"
            )
        selection_matrices.append(matrix * scale_vector[None, :])
    selection_noise_models = (
        [block_balanced_noise_proxy(feature_names) for _ in selection_matrices]
        if stability_scales is None
        else [
            np.asarray(stability_scales[str(record["anchor_id"])], dtype=float)
            for record in selection
        ]
    )
    selection_residuals = (
        subspace_residual_diagnostics(
            selection_matrices,
            selection_noise_models,
            result.directions,
        )
        if selection_matrices
        else []
    )
    dimension_selection = (
        select_candidate_dimension(
            selection_residuals,
            parameter_count=len(parameter_names),
        )
        if stability_scales is not None and selection_residuals
        else {"status": "not_run"}
    )

    def alignment_payload(anchor_ids, matrices, current_noise_models):
        if not matrices:
            return {"per_anchor": [], "rows": []}
        diagnostics = subspace_alignment_diagnostics(
            matrices,
            current_noise_models,
            result.directions,
        )
        per_anchor = []
        for anchor_id, rows, matrix, noise in zip(
            anchor_ids,
            diagnostics,
            matrices,
            current_noise_models,
        ):
            _, singular_values, right_transpose = np.linalg.svd(
                whiten_sensitivity(matrix, noise),
                full_matrices=True,
            )
            local_directions = right_transpose.T
            for column in range(local_directions.shape[1]):
                pivot = int(np.argmax(np.abs(local_directions[:, column])))
                if local_directions[pivot, column] < 0.0:
                    local_directions[:, column] *= -1.0
            per_anchor.append(
                {
                    "anchor_id": anchor_id,
                    "rows": rows,
                    "local_singular_values": singular_values.tolist(),
                    "local_directions": local_directions.tolist(),
                }
            )
        aggregate = []
        for dimension in range(1, len(parameter_names) + 1):
            current = [rows[dimension - 1] for rows in diagnostics]
            aggregate.append(
                {
                    "dimension": dimension,
                    "worst_maximum_principal_angle_degrees": float(
                        max(row["maximum_principal_angle_degrees"] for row in current)
                    ),
                    "worst_projector_frobenius": float(
                        max(row["projector_frobenius"] for row in current)
                    ),
                    "minimum_local_retained_singular_value": float(
                        min(row["local_retained_singular_value"] for row in current)
                    ),
                }
            )
        return {"per_anchor": per_anchor, "rows": aggregate}

    subspace_alignment = {
        "training": alignment_payload(
            [str(record["anchor_id"]) for record in training],
            training_matrices,
            noise_models,
        ),
        "selection": alignment_payload(
            [str(record["anchor_id"]) for record in selection],
            selection_matrices,
            selection_noise_models,
        ),
    }
    return {
        "training_anchor_ids": [str(record["anchor_id"]) for record in training],
        "selection_anchor_ids": [str(record["anchor_id"]) for record in selection],
        "parameter_names": parameter_names,
        "feature_names": feature_names,
        "feature_count": len(feature_names),
        "noise_model": noise_model_name,
        "excluded_nonsmooth_features": list(NONSMOOTH_EXCLUDED_FEATURES),
        "included_feature_blocks": list(SMOOTH_INCLUDED_FEATURES),
        "gramian": result.gramian.tolist(),
        "eigenvalues": result.eigenvalues.tolist(),
        "directions": result.directions.tolist(),
        "column_norms": result.column_norms.tolist(),
        "selection_residuals": selection_residuals,
        "subspace_alignment": subspace_alignment,
        "dimension_selection": dimension_selection,
        "dimension_selection_status": str(dimension_selection["status"]),
    }


def evaluate_holdout_inactive_probes(
    records: Sequence[Mapping[str, object]],
    schema: Mapping[str, object],
    decomposition: Mapping[str, object],
    *,
    config: object,
    forward_runner=_run_forward,
    stability_scales: Mapping[str, np.ndarray] | None = None,
) -> dict[str, object]:
    """Run nonlinear probes after directions are frozen, without selecting r."""

    holdout = [record for record in records if record.get("split") == "holdout"]
    if not holdout:
        raise ValueError("at least one holdout anchor is required")
    parameter_names = [str(name) for name in decomposition["parameter_names"]]
    feature_names = [str(name) for name in decomposition["feature_names"]]
    directions = np.asarray(decomposition["directions"], dtype=float)
    parameter_count = len(parameter_names)
    per_anchor: list[dict[str, object]] = []
    total_forward = 0

    for record in holdout:
        unit_anchor = np.asarray(record["unit_coordinates"], dtype=float)
        base = initialize_oer_parameters()
        base.update(
            unit_coordinates_to_parameters(
                schema,
                parameter_names,
                unit_anchor,
            )
        )
        baseline_features = forward_runner(base, config)
        total_forward += 1
        if baseline_features is None:
            raise ValueError(f"holdout anchor {record.get('anchor_id')} failed")
        baseline = feature_vector_from_rows(baseline_features, feature_names)
        scales = feature_scale_vector_from_rows(baseline_features, feature_names)
        noise_proxy = (
            block_balanced_noise_proxy(feature_names)
            if stability_scales is None
            else np.asarray(stability_scales[str(record["anchor_id"])], dtype=float)
        )
        probes = inactive_direction_probe_points(
            unit_anchor,
            directions,
            active_dimension=0,
            maximum_step=0.05,
        )
        direction_rows = []
        for probe in probes:
            deviations = []
            for side in ("plus", "minus"):
                params = initialize_oer_parameters()
                params.update(
                    unit_coordinates_to_parameters(
                        schema,
                        parameter_names,
                        probe[side],
                    )
                )
                features = forward_runner(params, config)
                total_forward += 1
                if features is None:
                    raise ValueError(
                        f"holdout {record.get('anchor_id')} direction "
                        f"{probe['direction_index']} {side} failed"
                    )
                vector = feature_vector_from_rows(features, feature_names)
                deviations.append(np.abs(vector - baseline) / scales / noise_proxy)
            combined = np.maximum(deviations[0], deviations[1])
            direction_rows.append(
                {
                    "direction_index": int(probe["direction_index"]),
                    "step": float(probe["step"]),
                    "max_normalized_feature_deviation": float(np.max(combined)),
                    "rms_normalized_feature_deviation": float(
                        np.sqrt(np.mean(combined**2))
                    ),
                }
            )
        per_anchor.append(
            {
                "anchor_id": str(record["anchor_id"]),
                "directions": direction_rows,
            }
        )

    rows = []
    for dimension in range(1, parameter_count + 1):
        inactive = [
            row
            for anchor in per_anchor
            for row in anchor["directions"]
            if row["direction_index"] >= dimension
        ]
        rows.append(
            {
                "dimension": dimension,
                "worst_normalized_feature_deviation": (
                    max(row["max_normalized_feature_deviation"] for row in inactive)
                    if inactive
                    else 0.0
                ),
                "worst_rms_normalized_feature_deviation": (
                    max(row["rms_normalized_feature_deviation"] for row in inactive)
                    if inactive
                    else 0.0
                ),
            }
        )
    return {
        "holdout_anchor_ids": [str(record["anchor_id"]) for record in holdout],
        "probe_maximum_step": 0.05,
        "normalization": (
            "block_balanced_proxy"
            if stability_scales is None
            else "frozen_diagonal_feature_stability"
        ),
        "forward_runs": total_forward,
        "per_anchor": per_anchor,
        "rows": rows,
        "dimension_selection_status": "not_selected_from_holdout",
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_noise_evidence(path: Path) -> dict[str, object]:
    """Validate and summarize the frozen time-domain noise evidence."""

    if not path.is_file():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("selection_rule") != "maximum_dataset_noise_floor":
        raise ValueError("noise evidence selection rule is unsupported")
    datasets = payload.get("datasets")
    if not isinstance(datasets, list) or not datasets:
        raise ValueError("noise evidence must contain datasets")
    fractions = [float(row["noise"]["noise_fraction"]) for row in datasets]
    if not all(np.isfinite(value) and value > 0.0 for value in fractions):
        raise ValueError("dataset noise fractions must be finite and positive")
    selected = float(payload.get("selected_noise_fraction"))
    if not np.isclose(selected, max(fractions), rtol=0.0, atol=1e-15):
        raise ValueError("selected noise fraction does not match dataset maximum")
    limitation = str(payload.get("limitation", "")).strip()
    if not limitation:
        raise ValueError("noise evidence limitation is required")
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "selection_rule": "maximum_dataset_noise_floor",
        "selected_noise_fraction": selected,
        "limitation": limitation,
        "source_commit": payload.get("source_commit"),
    }


def _git_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def _write_json(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--reports", type=Path)
    parser.add_argument("--noise-evidence", type=Path)
    parser.add_argument(
        "--noise-replicates",
        type=int,
        choices=(12, 24, 48),
        default=12,
    )
    parser.add_argument("--anchor-seed", type=int, default=DEFAULT_ANCHOR_SEED)
    parser.add_argument("--train-anchors", type=int, default=3)
    parser.add_argument("--selection-anchors", type=int, default=2)
    parser.add_argument("--holdout-anchors", type=int, default=1)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.output.exists() and any(args.output.iterdir()):
        raise RuntimeError(f"output directory is not empty: {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)
    split_counts = (
        ("train", int(args.train_anchors)),
        ("selection", int(args.selection_anchors)),
        ("holdout", int(args.holdout_anchors)),
    )
    if any(count <= 0 for _, count in split_counts):
        raise ValueError("all anchor split counts must be positive")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    config = InversionConfig(
        E_start=0.924097277474612,
        E_end=1.9229037265531128,
        f=5.0,
        dE=0.16,
        n_points=256,
        points_per_cycle=32,
        feature_grid_size=32,
        fit_harmonics=(1, 2, 3),
        feature_mode="hybrid",
        solver_backend="lsoda",
        seed=args.anchor_seed,
    )
    reports_source = None
    if args.reports is not None:
        if not args.reports.is_file():
            raise FileNotFoundError(args.reports)
        records = json.loads(args.reports.read_text(encoding="utf-8"))
        reports_source = {
            "path": str(args.reports),
            "sha256": _sha256(args.reports),
        }
    else:
        anchors = generate_parameter_anchors(
            schema,
            PARAMETER_NAMES,
            split_counts=split_counts,
            seed=args.anchor_seed,
        )
        records = []
        for anchor in anchors:
            base = initialize_oer_parameters()
            base.update(anchor.parameters)
            report = analyze_parameter_importance(
                base,
                config,
                fit_harmonics=[1, 2, 3],
                parameter_names=PARAMETER_NAMES,
            )
            records.append(
                {
                    "anchor_id": anchor.anchor_id,
                    "split": anchor.split,
                    "unit_coordinates": list(anchor.unit_coordinates),
                    "parameters": anchor.parameters,
                    "report": report,
                }
            )
            print(
                f"[effective-dimension] {anchor.anchor_id} "
                f"success={report.get('success')} "
                f"forward={report.get('metadata', {}).get('n_forward_runs')}",
                flush=True,
            )

    actual_split_counts = Counter(str(record.get("split")) for record in records)
    expected_split_counts = {name: count for name, count in split_counts}
    if dict(actual_split_counts) != expected_split_counts:
        raise ValueError(
            "anchor report split counts do not match requested design: "
            f"actual={dict(actual_split_counts)}, expected={expected_split_counts}"
        )

    _write_json(args.output / "anchor_reports.json", records)
    preliminary_decomposition = decompose_training_reports(records, schema)
    observed_feature_names, structurally_excluded_rows = (
        structurally_observed_feature_names(
            config,
            preliminary_decomposition["feature_names"],
        )
    )
    proxy_decomposition = decompose_training_reports(
        records,
        schema,
        observed_feature_names=observed_feature_names,
    )
    stability_scales = None
    stability_audit = None
    noise_evidence = None
    if args.noise_evidence is not None:
        noise_evidence = load_noise_evidence(args.noise_evidence)
        stability_scales, stability_audit = estimate_anchor_stability_scales(
            records,
            schema,
            parameter_names=proxy_decomposition["parameter_names"],
            feature_names=proxy_decomposition["feature_names"],
            config=config,
            noise_fraction=float(noise_evidence["selected_noise_fraction"]),
            noise_seeds=NOISE_SEED_POOL[: args.noise_replicates],
        )
        stability_payload = {
            **stability_audit,
            "feature_names": proxy_decomposition["feature_names"],
            "noise_evidence": noise_evidence,
            "standard_deviations_by_anchor": {
                anchor_id: values.tolist()
                for anchor_id, values in stability_scales.items()
            },
        }
        stability_path = args.output / "feature_stability.json"
        _write_json(stability_path, stability_payload)
        stability_audit = {
            **stability_audit,
            "artifact": {
                "path": str(stability_path),
                "sha256": _sha256(stability_path),
            },
        }
        decomposition = decompose_training_reports(
            records,
            schema,
            stability_scales=stability_scales,
            observed_feature_names=observed_feature_names,
        )
    else:
        decomposition = proxy_decomposition
    holdout_probes = evaluate_holdout_inactive_probes(
        records,
        schema,
        decomposition,
        config=config,
        stability_scales=stability_scales,
    )
    summary = {
        "status": "SUCCESS",
        "study_kind": "development_smoke",
        "eligible_for_formal_conclusions": False,
        "schema_path": str(SCHEMA_PATH.relative_to(ROOT)),
        "schema_sha256": _sha256(SCHEMA_PATH),
        "git_commit": _git_commit(),
        "dirty_worktree_expected": True,
        "forward_reports_source": reports_source,
        "seed": int(args.anchor_seed),
        "split_counts": expected_split_counts,
        "parameter_names": list(PARAMETER_NAMES),
        "config": {
            "E_start": config.E_start,
            "E_end": config.E_end,
            "f": config.f,
            "dE": config.dE,
            "n_points": config.n_points,
            "points_per_cycle": config.points_per_cycle,
            "fit_harmonics": list(config.fit_harmonics),
            "feature_mode": config.feature_mode,
            "solver_backend": config.solver_backend,
        },
        "noise_evidence": noise_evidence,
        "feature_stability": stability_audit,
        "structurally_excluded_feature_rows": structurally_excluded_rows,
        "decomposition": decomposition,
        "holdout_inactive_probes": holdout_probes,
        "prohibited_claims": [
            "effective_dimension_selected",
            "real_data_parameters_identifiable",
            "unit_noise_proxy_is_experimental_covariance",
            "quantization_floor_is_repeatability_covariance",
        ],
    }
    _write_json(args.output / "summary.json", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
