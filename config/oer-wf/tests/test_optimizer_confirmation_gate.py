"""Independent verification tests for A6 Sobol confirmation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oer_wf.validators import optimizer_confirmation_gate


GATE_CONFIG = {
    "gate_version": 1,
    "recovery_gate_version": 2,
    "optimizer": "sobol_pattern",
    "parameter_pairs": [
        ["k0_2", "k0_3"],
        ["k0_2", "G_O"],
        ["k0_3", "G_O"],
    ],
    "truth_ids": ["center", "mixed_a", "mixed_b"],
    "noise_fractions": [0.0, 0.001495726085983469],
    "seeds": [7, 17, 27],
    "optimization_budget": 100,
    "development_identity": ["center", 0.0, 7],
    "development_evidence_sha256": (
        "116099242f034c133f4895d068429673f0a12be611b76ea00cc3ebf415a83b8a"
    ),
    "development_source_results_sha256": (
        "e93ccab24c4a91d9d4d9a2b8e014826b6b1a07b7d0891c6e7dd944b78e17b432"
    ),
    "max_median_normalized_bound_error": 0.025,
    "max_normalized_bound_error": 0.05,
    "max_seed_normalized_bound_dispersion": 0.05,
    "max_boundary_hit_rate": 0.0,
}


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _job_matrix():
    pairs = [tuple(pair) for pair in GATE_CONFIG["parameter_pairs"]]
    identities = [
        (truth, noise, seed)
        for truth in GATE_CONFIG["truth_ids"]
        for noise in GATE_CONFIG["noise_fractions"]
        for seed in GATE_CONFIG["seeds"]
        if (truth, noise, seed) != ("center", 0.0, 7)
    ]
    return [
        (pair, truth, noise, seed)
        for pair in pairs
        for truth, noise, seed in identities
    ]


def _row(pair, truth, noise, seed, *, error):
    metrics = {
        name: {
            "truth": 1.0,
            "estimate": 1.0 + error,
            "normalized_bound_error": abs(error),
            "boundary_hit": False,
        }
        for name in pair
    }
    metrics["boundary_hits"] = []
    metrics["max_normalized_bound_error"] = abs(error)
    return {
        "job_id": (
            f"{'-'.join(pair)}__sobol_pattern__{truth}"
            f"__noise-{noise:g}__seed-{seed}__budget-100"
        ),
        "optimizer": "sobol_pattern",
        "free_parameters": list(pair),
        "truth_id": truth,
        "noise_fraction": noise,
        "seed": seed,
        "budget": 100,
        "feature_mode": "hybrid",
        "success": True,
        "optimization_calls": 100,
        "diagnostic_truth_calls": 1,
        "truth_diagnostic_sequence": 101,
        "n_ode_fail": 0,
        "n_tafel_fail": 0,
        "best_objective": abs(error),
        "truth_objective": 0.0,
        "parameter_metrics": metrics,
    }


def _write_archive(
    path: Path,
    *,
    failing_pairs=(),
) -> None:
    path.mkdir(parents=True)
    evidence_source = (
        _root()
        / "results"
        / "formal"
        / "identifiability"
        / "gate-a6-optimizer-development"
        / "development_evidence.json"
    )
    evidence = json.loads(evidence_source.read_text())
    confirmation = [
        _row(
            pair,
            truth,
            noise,
            seed,
            error=0.06 if pair in failing_pairs else 0.01,
        )
        for pair, truth, noise, seed in _job_matrix()
    ]
    gate = optimizer_confirmation_gate._recompute_gate(
        evidence["development_rows"],
        confirmation,
        GATE_CONFIG,
    )
    evaluations = [
        {
            "job_id": row["job_id"],
            "sequence": sequence,
            "kind": "optimization",
            "index": sequence,
            "unit": [0.5, 0.5],
            "loss": 0.01,
            "error": None,
        }
        for row in confirmation
        for sequence in range(1, 101)
    ]
    plan = {
        "schema_version": 1,
        "phase": "confirmation",
        "backend": "cn",
        "budget": 100,
        "is_smoke": False,
        "development_evidence": {
            "sha256": GATE_CONFIG[
                "development_evidence_sha256"
            ],
            "source_results_sha256": GATE_CONFIG[
                "development_source_results_sha256"
            ],
        },
        "jobs": [
            {
                "job_id": row["job_id"],
                "optimizer": row["optimizer"],
                "free_parameters": row["free_parameters"],
                "truth_id": row["truth_id"],
                "noise_fraction": row["noise_fraction"],
                "seed": row["seed"],
                "budget": row["budget"],
            }
            for row in confirmation
        ],
    }
    summary = {
        "execution_passed": True,
        "scientific_gate_passed": gate["scientific_gate_passed"],
        "job_count": 51,
        "completed_jobs": 51,
        "optimization_calls": 5100,
        "diagnostic_truth_calls": 51,
        "n_ode_fail": 0,
        "is_smoke": False,
    }
    (path / "development_evidence.snapshot.json").write_bytes(
        evidence_source.read_bytes()
    )
    (path / "benchmark_plan.json").write_text(json.dumps(plan))
    (path / "results.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in confirmation)
    )
    (path / "evaluations.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in evaluations)
    )
    (path / "summary.json").write_text(json.dumps(summary))
    (path / "confirmation_gate.json").write_text(json.dumps(gate))


def _failures(checks):
    return [check.name for check in checks if not check.passed]


def test_confirmation_gate_passes_exact_51_plus_3_archive(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "archive"
    _write_archive(archive)

    checks = optimizer_confirmation_gate.run(
        archive,
        validator_config=GATE_CONFIG,
    )

    assert _failures(checks) == []


def test_confirmation_gate_rejects_99_calls_as_structure(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "archive"
    _write_archive(archive)
    rows = [
        json.loads(line)
        for line in (archive / "results.jsonl").read_text().splitlines()
    ]
    rows[0]["optimization_calls"] = 99
    (archive / "results.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows)
    )

    checks = optimizer_confirmation_gate.run(
        archive,
        validator_config=GATE_CONFIG,
    )

    assert "structure:optimizer_confirmation_gate" in _failures(checks)


def test_confirmation_gate_rejects_development_hash_mismatch(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "archive"
    _write_archive(archive)
    snapshot = archive / "development_evidence.snapshot.json"
    snapshot.write_text(snapshot.read_text() + " ")

    checks = optimizer_confirmation_gate.run(
        archive,
        validator_config=GATE_CONFIG,
    )

    assert "structure:optimizer_confirmation_gate" in _failures(checks)


def test_confirmation_gate_classifies_nan_as_numerical(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "archive"
    _write_archive(archive)
    raw = (archive / "results.jsonl").read_text()
    (archive / "results.jsonl").write_text(
        raw.replace('"best_objective": 0.01', '"best_objective": NaN', 1)
    )

    checks = optimizer_confirmation_gate.run(
        archive,
        validator_config=GATE_CONFIG,
    )

    assert _failures(checks) == [
        "numerical:optimizer_confirmation_gate"
    ]


def test_confirmation_gate_all_pairs_fail_scientifically(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "archive"
    pairs = tuple(tuple(pair) for pair in GATE_CONFIG["parameter_pairs"])
    _write_archive(archive, failing_pairs=pairs)

    checks = optimizer_confirmation_gate.run(
        archive,
        validator_config=GATE_CONFIG,
    )

    assert _failures(checks) == [
        "scientific:optimizer_confirmation_gate"
    ]


def test_confirmation_gate_allows_only_passing_pair_to_lsoda(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "archive"
    failing = (("k0_2", "G_O"), ("k0_3", "G_O"))
    _write_archive(archive, failing_pairs=failing)

    checks = optimizer_confirmation_gate.run(
        archive,
        validator_config=GATE_CONFIG,
    )

    assert _failures(checks) == []
    scientific = next(
        check
        for check in checks
        if check.name == "scientific:optimizer_confirmation_gate"
    )
    assert "k0_2,k0_3" in scientific.detail
    assert "k0_2,G_O" not in scientific.detail
