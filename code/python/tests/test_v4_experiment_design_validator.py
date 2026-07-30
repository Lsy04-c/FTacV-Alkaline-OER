"""Contracts for the independent V4 experiment-design validator."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import shutil

import pytest

import scripts.run_v4_experiment_design as runner
from scripts.validate_v4_experiment_design import validate_archive


ROOT = Path(__file__).resolve().parents[3]
SPEC = ROOT / "config" / "experiment-design" / "v4-computational-design.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _refresh_manifest(archive: Path, name: str) -> None:
    path = archive / "run_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["artifact_sha256"][name] = _sha256(archive / name)
    path.write_text(
        json.dumps(manifest, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


@pytest.fixture(scope="module")
def valid_smoke(tmp_path_factory):
    output = tmp_path_factory.mktemp("v4-validator") / "archive"
    original = runner._git_provenance
    runner._git_provenance = lambda: {
        "source_commit": "test-commit",
        "dirty": True,
        "dirty_paths": ["test-fixture"],
        "ignored_workflow_paths": [],
        "dirty_content_sha256": "fixture",
    }
    try:
        exit_code = runner.main(
            [
                "--task-spec",
                str(SPEC),
                "--output",
                str(output),
                "--workers",
                "2",
                "--smoke",
            ]
        )
    finally:
        runner._git_provenance = original
    assert exit_code == 0
    return output


def test_validator_accepts_complete_smoke_without_scientific_recommendation(
    valid_smoke,
):
    result = validate_archive(ROOT, SPEC, valid_smoke)

    assert result["gate"] == "PASS"
    assert result["run_mode"] == "smoke"
    assert result["primary_job_count"] == 22
    assert result["sensitivity_matrix_count"] == 2
    assert result["recommendation_status"] == "NO_ROBUST_RECOMMENDATION"


def test_validator_rejects_changed_condition_after_manifest_rehash(
    valid_smoke,
    tmp_path,
):
    archive = tmp_path / "archive"
    shutil.copytree(valid_smoke, archive)
    path = archive / "condition_catalog.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0])
    rows[0]["frequency_hz"] = "7.0"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    _refresh_manifest(archive, "condition_catalog.csv")

    result = validate_archive(ROOT, SPEC, archive)

    assert result["gate"] == "FAIL_STRUCTURE"
    assert any("condition catalog" in error.lower() for error in result["errors"])


def test_validator_rejects_changed_recommendation_after_manifest_rehash(
    valid_smoke,
    tmp_path,
):
    archive = tmp_path / "archive"
    shutil.copytree(valid_smoke, archive)
    path = archive / "recommendation.json"
    recommendation = json.loads(path.read_text(encoding="utf-8"))
    recommendation["status"] = "RECOMMEND_TWO"
    recommendation["selected"] = ["wrong-1", "wrong-2"]
    path.write_text(
        json.dumps(recommendation, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    _refresh_manifest(archive, "recommendation.json")

    result = validate_archive(ROOT, SPEC, archive)

    assert result["gate"] == "FAIL_STRUCTURE"
    assert any("recommendation" in error.lower() for error in result["errors"])


def test_validator_is_read_only_on_missing_archive(tmp_path):
    archive = tmp_path / "archive"

    result = validate_archive(ROOT, SPEC, archive)

    assert result["gate"] == "FAIL_STRUCTURE"
    assert not archive.exists()
