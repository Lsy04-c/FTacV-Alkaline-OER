"""CLI contracts for post-experiment intake validation."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.validate_post_experiment_intake import main
from .test_experiment_intake import collected_manifest


ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = (
    ROOT
    / "config"
    / "data-contracts"
    / "post-experiment-intake-v1.template.json"
)
VALIDATOR = ROOT / "code" / "python" / "scripts" / "validate_post_experiment_intake.py"


def _complete_fixture(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "project"
    root.mkdir()
    manifest = collected_manifest(root)
    manifest_path = root / "intake.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return root, manifest_path


def test_template_cli_waits_without_writing_a1_seed(tmp_path):
    output = tmp_path / "out"
    code = main(
        [
            "--project-root",
            str(ROOT),
            "--manifest",
            str(TEMPLATE),
            "--output",
            str(output),
        ]
    )
    assert code == 2
    summary = json.loads((output / "intake_summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "WAITING_FOR_DATA"
    assert summary["source_manifest"] == (
        "config/data-contracts/post-experiment-intake-v1.template.json"
    )
    assert not (output / "a1_seed.json").exists()
    acceptance = (output / "acceptance.md").read_text(encoding="utf-8")
    assert "不代表 Gate A1 PASS" in acceptance
    assert "不授权 A6-v2、真实反演或参数点估计" in acceptance


def test_ready_cli_writes_nonformal_a1_seed(tmp_path):
    root, manifest_path = _complete_fixture(tmp_path)
    output = tmp_path / "out"
    assert (
        main(
            [
                "--project-root",
                str(root),
                "--manifest",
                str(manifest_path),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    seed = json.loads((output / "a1_seed.json").read_text(encoding="utf-8"))
    assert seed["status"] == "UNVALIDATED_SEED"
    assert seed["requires_new_batch_a1_validator"] is True
    assert seed["source_intake_id"] == "test-intake-v1"
    assert len(seed["source_manifest_sha256"]) == 64
    assert [row["analysis_role"] for row in seed["datasets"]] == [
        "training",
        "selection",
        "holdout",
    ]


def test_cli_refuses_nonempty_output_directory(tmp_path):
    output = tmp_path / "out"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    try:
        main(
            [
                "--project-root",
                str(ROOT),
                "--manifest",
                str(TEMPLATE),
                "--output",
                str(output),
            ]
        )
    except ValueError as exc:
        assert "non-empty output" in str(exc)
    else:
        raise AssertionError("non-empty output must be rejected")
    assert marker.read_text(encoding="utf-8") == "keep"


def test_cli_rejects_nonfinite_json(tmp_path):
    manifest_path = tmp_path / "invalid.json"
    manifest_path.write_text('{"schema_version": NaN}\n', encoding="utf-8")
    try:
        main(
            [
                "--project-root",
                str(tmp_path),
                "--manifest",
                str(manifest_path),
                "--output",
                str(tmp_path / "out"),
            ]
        )
    except ValueError as exc:
        assert "non-finite" in str(exc)
    else:
        raise AssertionError("NaN input must be rejected")


def test_intake_validator_does_not_import_scientific_runtime():
    source = VALIDATOR.read_text(encoding="utf-8")
    for forbidden in (
        "oer_aem.physics",
        "scipy",
        "numpy",
        "optuna",
        "code.web",
    ):
        assert forbidden not in source
