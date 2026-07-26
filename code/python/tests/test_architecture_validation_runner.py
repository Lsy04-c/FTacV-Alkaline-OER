"""Tests for the Gate A6 evidence runner contract."""

from pathlib import Path

import pytest

from scripts.run_architecture_validation import (
    build_config,
    build_run_manifest,
    parse_args,
    prepare_output_directory,
    validate_source_state,
)


def test_formal_defaults_freeze_grid_solver_and_mode(tmp_path):
    args = parse_args(["--output", str(tmp_path / "evidence")])
    config = build_config(args)

    assert config.feature_grid_size == 128
    assert config.solver_backend == "lsoda"
    assert config.feature_mode == "legacy"
    assert config.seed == 42


def test_runner_accepts_each_frozen_feature_mode(tmp_path):
    for mode in ("legacy", "complex_snr", "lockin_only", "hybrid"):
        args = parse_args(
            ["--output", str(tmp_path / mode), "--feature-mode", mode]
        )
        assert build_config(args).feature_mode == mode


def test_output_directory_must_not_contain_existing_evidence(tmp_path):
    output = tmp_path / "evidence"
    output.mkdir()
    (output / "old.csv").write_text("old")

    with pytest.raises(FileExistsError, match="not empty"):
        prepare_output_directory(output)


def test_output_directory_is_created_when_absent(tmp_path):
    output = tmp_path / "evidence"

    prepare_output_directory(output)

    assert output == Path(output)
    assert output.is_dir()


def test_manifest_records_configuration_and_output_hashes(tmp_path):
    output = tmp_path / "evidence"
    output.mkdir()
    artifact = output / "signed_sensitivity.csv"
    artifact.write_text("feature,parameter,sensitivity\n")
    args = parse_args(["--output", str(output), "--feature-mode", "hybrid"])
    config = build_config(args)

    manifest = build_run_manifest(
        output=output,
        args=args,
        config=config,
        source_commit="abc123",
        dirty=False,
        command=["python", "runner.py"],
        baseline_params={"k0_1": 100.0},
    )

    assert manifest["source_commit"] == "abc123"
    assert manifest["dirty"] is False
    assert manifest["configuration"]["feature_grid_size"] == 128
    assert manifest["configuration"]["feature_mode"] == "hybrid"
    assert manifest["configuration"]["solver_backend"] == "lsoda"
    assert manifest["baseline_parameters"]["k0_1"] == 100.0
    assert manifest["perturbation_rules"]["k0_1"] == ["log10", 0.25]
    assert manifest["physical_bounds"]["k0_1"] == [0.001, 1_000_000.0]
    assert manifest["sha256"]["signed_sensitivity.csv"]


def test_formal_run_rejects_dirty_source(tmp_path):
    args = parse_args(["--output", str(tmp_path / "formal")])

    with pytest.raises(RuntimeError, match="clean Git worktree"):
        validate_source_state(args, dirty=True)


def test_smoke_run_allows_dirty_source(tmp_path):
    args = parse_args(["--smoke", "--output", str(tmp_path / "smoke")])

    validate_source_state(args, dirty=True)
