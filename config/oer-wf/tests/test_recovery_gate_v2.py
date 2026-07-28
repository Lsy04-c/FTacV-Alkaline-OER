from __future__ import annotations

import json
from pathlib import Path

from oer_wf.validators.recovery_gate import run


MODES = ["complex_snr", "hybrid", "legacy", "lockin_only"]
TRUTHS = ["center", "mixed_a", "mixed_b"]
NOISES = [0.0, 0.0015]
SEEDS = [7, 17, 27]


def _config() -> dict:
    return {
        "gate_version": 2,
        "parameter_names": ["k0_3"],
        "feature_modes": MODES,
        "truth_ids": TRUTHS,
        "noise_fractions": NOISES,
        "seeds": SEEDS,
        "trials": 100,
        "require_all_studies_success": True,
        "max_boundary_hit_rate": 0.0,
        "max_median_normalized_bound_error": 0.025,
        "max_normalized_bound_error": 0.05,
        "max_seed_normalized_bound_dispersion": 0.05,
        "require_nonlegacy_mode": True,
        "legacy_mode": "legacy",
    }


def _write_archive(
    root: Path,
    *,
    mode_errors: dict[str, list[float]] | None = None,
    same_side: bool = False,
) -> None:
    mode_errors = mode_errors or {}
    rows = []
    groups = []
    for mode in MODES:
        errors = mode_errors.get(mode, [0.002, 0.003, 0.004])
        for truth_id in TRUTHS:
            for noise in NOISES:
                truth = 10.0
                estimates = [
                    truth * (10 ** (8.0 * error))
                    if same_side or index > 0
                    else truth * (10 ** (-8.0 * error))
                    for index, error in enumerate(errors)
                ]
                group_rows = []
                for seed, estimate, error in zip(SEEDS, estimates, errors):
                    row = {
                        "job_id": f"{mode}__{truth_id}__{noise}__{seed}",
                        "feature_mode": mode,
                        "truth_id": truth_id,
                        "noise_fraction": noise,
                        "trials": 100,
                        "seed": seed,
                        "success": True,
                        "free_parameters": ["k0_3"],
                        "best_params": {"k0_3": estimate},
                        "truth_params": {"k0_3": truth},
                        "parameter_metrics": {
                            "k0_3": {
                                "truth": truth,
                                "estimate": estimate,
                                "encoding": "log10",
                                "normalized_bound_error": error,
                                "boundary_hit": False,
                            }
                        },
                    }
                    rows.append(row)
                    group_rows.append(row)
                groups.append(
                    {
                        "feature_mode": mode,
                        "truth_id": truth_id,
                        "noise_fraction": noise,
                        "trials": 100,
                        "seeds": SEEDS,
                        "all_success": True,
                        "parameters": {
                            "k0_3": {
                                "truth": truth,
                                "seed_min": min(estimates),
                                "seed_max": max(estimates),
                                "truth_covered_by_seed_range": (
                                    min(estimates) <= truth <= max(estimates)
                                ),
                                "median_normalized_bound_error": sorted(errors)[1],
                                "max_normalized_bound_error": max(errors),
                                "boundary_hit_rate": 0.0,
                            }
                        },
                    }
                )
    summary = {
        "job_count": len(rows),
        "completed_jobs": len(rows),
        "recovery_summary": {"group_count": len(groups), "groups": groups},
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (root / "results.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_v2_accepts_precise_same_side_seed_estimates(tmp_path: Path) -> None:
    _write_archive(tmp_path, same_side=True)

    checks = run(tmp_path, validator_config=_config())

    assert len(checks) == 1
    assert checks[0].name == "scientific:recovery_gate_v2"
    assert checks[0].passed is True
    assert "eligible_modes=complex_snr,hybrid,lockin_only" in checks[0].detail


def test_v2_rejects_range_that_crosses_truth_but_is_too_wide(tmp_path: Path) -> None:
    bad = [0.049, 0.051, 0.049]
    _write_archive(
        tmp_path,
        mode_errors={mode: bad for mode in MODES},
    )

    checks = run(tmp_path, validator_config=_config())

    assert len(checks) == 1
    assert checks[0].name == "scientific:recovery_gate_v2"
    assert checks[0].passed is False
    assert "eligible_modes=none" in checks[0].detail
    assert "max_error=0.051" in checks[0].detail


def test_v2_selects_good_nonlegacy_mode_without_other_mode_veto(tmp_path: Path) -> None:
    _write_archive(
        tmp_path,
        mode_errors={
            "complex_snr": [0.10, 0.12, 0.11],
            "hybrid": [0.001, 0.002, 0.003],
            "legacy": [0.001, 0.001, 0.001],
            "lockin_only": [0.08, 0.09, 0.10],
        },
    )

    checks = run(tmp_path, validator_config=_config())

    assert checks[0].passed is True
    assert "eligible_modes=hybrid" in checks[0].detail
    assert "selected_mode=hybrid" in checks[0].detail
    assert "complex_snr:FAIL" in checks[0].detail


def test_v2_rejects_missing_expected_group(tmp_path: Path) -> None:
    _write_archive(tmp_path)
    summary_path = tmp_path / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["recovery_summary"]["groups"].pop()
    summary["recovery_summary"]["group_count"] -= 1
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    checks = run(tmp_path, validator_config=_config())

    assert checks[0].name == "structure:recovery_gate_v2"
    assert checks[0].passed is False
    assert "group coverage mismatch" in checks[0].detail


def test_v1_remains_default_when_gate_version_is_omitted(tmp_path: Path) -> None:
    _write_archive(
        tmp_path,
        mode_errors={mode: [0.001, 0.002, 0.003] for mode in MODES},
        same_side=True,
    )
    cfg = {
        "parameter_names": ["k0_3"],
        "require_all_studies_success": True,
        "require_truth_covered_by_seed_range": True,
        "max_boundary_hit_rate": 0.0,
    }

    checks = run(tmp_path, validator_config=cfg)

    assert checks[0].name == "scientific:recovery_gate"
    assert checks[0].passed is False
    assert "truth not covered" in checks[0].detail


def test_v2_rejects_threshold_drift(tmp_path: Path) -> None:
    _write_archive(tmp_path)
    cfg = _config()
    cfg["max_normalized_bound_error"] = 0.051

    checks = run(tmp_path, validator_config=cfg)

    assert checks[0].name == "structure:recovery_gate_v2_config"
    assert checks[0].passed is False
    assert "frozen value 0.05" in checks[0].detail


def test_v2_requires_all_studies_and_nonlegacy_mode(tmp_path: Path) -> None:
    _write_archive(tmp_path)
    cfg = _config()
    cfg["require_nonlegacy_mode"] = False

    checks = run(tmp_path, validator_config=cfg)

    assert checks[0].name == "structure:recovery_gate_v2_config"
    assert checks[0].passed is False
    assert "require_nonlegacy_mode must be true" in checks[0].detail
