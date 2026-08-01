from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path

from scripts import run_synthetic_recovery as runner
from oer_aem.inversion import DEFAULT_PARAM_SPECS
from oer_aem.recovery import recovery_metrics


ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = ROOT / "config" / "recovery" / "pre-experiment-a6-v2.json"
VALIDATOR_PATH = (
    ROOT / "code" / "python" / "scripts" / "validate_pre_experiment_recovery.py"
)


def _load_validator():
    spec = importlib.util.spec_from_file_location("pre_experiment_validator", VALIDATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_s0_archive(monkeypatch, tmp_path: Path) -> Path:
    output = tmp_path / "s0"
    monkeypatch.setattr(
        runner,
        "git_state_full",
        lambda: {
            "source_commit": "deadbeef",
            "dirty": False,
            "dirty_paths": [],
            "ignored_workflow_paths": [],
        },
    )
    runner.main(
        [
            "--pre-experiment-spec",
            str(SPEC_PATH),
            "--portfolio-stage",
            "S0",
            "--backend",
            "lsoda",
            "--workers",
            "1",
            "--output",
            str(output),
        ]
    )
    return output


def test_validator_accepts_complete_s0_structure(monkeypatch, tmp_path: Path) -> None:
    archive = _make_s0_archive(monkeypatch, tmp_path)
    validator = _load_validator()

    result = validator.validate_archive(ROOT, SPEC_PATH, archive)

    assert result["gate"] == "PASS"
    assert result["stage"] == "S0"
    assert result["stage_status"] == "STRUCTURE_ONLY"
    assert result["errors"] == []


def test_validator_rejects_target_reuse_hash_conflict(monkeypatch, tmp_path: Path) -> None:
    archive = _make_s0_archive(monkeypatch, tmp_path)
    manifest_path = archive / "target_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    repeated_key = manifest["records"][0]["target_key"]
    repeated = next(
        item for item in manifest["records"][1:] if item["target_key"] == repeated_key
    )
    repeated["target_sha256"] = "f" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    validator = _load_validator()

    result = validator.validate_archive(ROOT, SPEC_PATH, archive)

    assert result["gate"] == "FAIL"
    assert any("target" in error.lower() for error in result["errors"])


def _make_synthetic_s1_archive(tmp_path: Path) -> Path:
    output = tmp_path / "s1"
    output.mkdir()
    args = runner.parse_args(
        [
            "--pre-experiment-spec",
            str(SPEC_PATH),
            "--portfolio-stage",
            "S1",
            "--output",
            str(output),
        ]
    )
    jobs = runner.build_jobs(args)
    provenance = {
        "source_commit": "deadbeef",
        "dirty": False,
        "dirty_paths": [],
        "ignored_workflow_paths": [],
    }
    resume = runner.build_resume_metadata(args, jobs, provenance, None)
    for job in jobs:
        job["job_input_hash"] = resume["job_input_hashes"][job["job_id"]]
    rows = []
    for job in jobs:
        specs = tuple(
            item
            for item in DEFAULT_PARAM_SPECS
            if item[0] in set(job["free_parameters"])
        )
        records = [
            {
                **identity,
                "target_sha256": hashlib.sha256(
                    identity["target_key"].encode("utf-8")
                ).hexdigest(),
                "channel_contract_sha256": "c" * 64,
            }
            for identity in job["target_identities"]
        ]
        rows.append(
            {
                **job,
                "success": True,
                "best_value": 0.0,
                "best_params": {
                    name: job["truth_params"][name]
                    for name in job["free_parameters"]
                },
                "parameter_metrics": recovery_metrics(
                    truth=job["truth_params"],
                    estimate=job["truth_params"],
                    specs=specs,
                ),
                "condition_best_losses": {
                    condition_id: 0.0 for condition_id in job["condition_ids"]
                },
                "target_records": records,
                "n_trials": 100,
                "n_forward": 100 * len(job["condition_ids"]),
                "n_ode_fail": 0,
                "n_feature_fail": 0,
                "n_tafel_fail": 0,
                "runtime_seconds": 1.0,
                "configuration": {
                    "feature_mode": "hybrid",
                    "fit_harmonics": [1, 2, 3],
                    "feature_grid_size": 128,
                    "solver_backend": "lsoda",
                    "conditions": {
                        condition_id: {
                            "n_points": (
                                32768
                                if condition_id != "candidate_10hz_matched_scan"
                                else 65536
                            ),
                            "points_per_cycle": 128,
                        }
                        for condition_id in job["condition_ids"]
                    },
                },
            }
        )
    plan = {
        "backend": "lsoda",
        "feature_modes": ["hybrid"],
        "phase": None,
        "portfolio_stage": "S1",
        "noise_fraction": None,
        "workers": 8,
        "free_parameters": jobs[0]["free_parameters"],
        "smoke": False,
        "job_count": len(jobs),
        "jobs": jobs,
        "noise_evidence": None,
        "provenance": provenance,
        "resume_schema_version": 2,
        "resume_fingerprint": resume["resume_fingerprint"],
    }
    runner.atomic_write_json(output / "job_plan.json", plan, prefix=".plan.")
    runner.atomic_write_checkpoint(
        output / "results.jsonl",
        {row["job_id"]: row for row in rows},
        [job["job_id"] for job in jobs],
    )
    runner.write_portfolio_evidence(output=output, args=args, jobs=jobs, rows=rows)
    summary = runner.build_summary(
        args=args,
        jobs=jobs,
        rows=rows,
        provenance=provenance,
        duration_seconds=81.0,
        resumed=False,
        reused_jobs=0,
        executed_jobs=81,
    )
    runner.atomic_write_json(output / "summary.json", summary, prefix=".summary.")
    runner.write_run_manifest(output, source_commit="deadbeef")
    return output


def test_validator_rebuilds_formal_s1_scientific_gate(tmp_path: Path) -> None:
    archive = _make_synthetic_s1_archive(tmp_path)
    validator = _load_validator()

    result = validator.validate_archive(ROOT, SPEC_PATH, archive)

    assert result["gate"] == "PASS"
    assert result["stage"] == "S1"
    assert result["stage_status"] == "S1_ELIGIBLE"
    assert len(result["eligible_parameter_pairs"]) == 3


def test_validator_rejects_summary_that_disagrees_with_raw_rows(tmp_path: Path) -> None:
    archive = _make_synthetic_s1_archive(tmp_path)
    summary_path = archive / "summary.json"
    summary = json.loads(summary_path.read_text())
    summary["eligible_parameter_pairs"] = []
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    validator = _load_validator()

    result = validator.validate_archive(ROOT, SPEC_PATH, archive)

    assert result["gate"] == "FAIL"
    assert any("eligible" in error.lower() for error in result["errors"])
