"""Shared validator lookup and local invocation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from oer_wf.models import CheckResult
from oer_wf.validators import (
    conditional_reachability_gate,
    finite_check,
    manifest_hash,
    optimizer_benchmark_gate,
    optimizer_confirmation_gate,
    provenance,
    recovery_gate,
    schema_check,
    v3_residual_attribution_gate,
    v4_experiment_design_gate,
)


VALIDATOR_MAP = {
    "conditional_reachability_gate": conditional_reachability_gate.run,
    "schema_check": schema_check.run,
    "finite_check": finite_check.run,
    "provenance": provenance.run,
    "manifest_hash": manifest_hash.run,
    "optimizer_benchmark_gate": optimizer_benchmark_gate.run,
    "optimizer_confirmation_gate": optimizer_confirmation_gate.run,
    "recovery_gate": recovery_gate.run,
    "v3_residual_attribution_gate": v3_residual_attribution_gate.run,
    "v4_experiment_design_gate": v4_experiment_design_gate.run,
}

_CONFIGURED_VALIDATORS = {
    "conditional_reachability_gate",
    "recovery_gate",
    "optimizer_benchmark_gate",
    "optimizer_confirmation_gate",
    "v3_residual_attribution_gate",
    "v4_experiment_design_gate",
}
_ORCHESTRATION_KEYS = {"execution", "timeout_sec"}


def split_runtime_config(
    raw: dict[str, Any] | None,
) -> tuple[str, int, dict[str, Any]]:
    config = dict(raw or {})
    execution = str(config.pop("execution", "local"))
    timeout = int(config.pop("timeout_sec", 600))
    return execution, timeout, config


def run_validator(
    name: str,
    archive: Path,
    expected_files: list[str],
    validator_config: dict[str, Any] | None,
) -> tuple[str, int, list[CheckResult]]:
    """Run one validator and return its requested runtime plus checks."""
    execution, timeout, clean_config = split_runtime_config(validator_config)
    fn = VALIDATOR_MAP.get(name)
    if fn is None:
        return execution, timeout, [
            CheckResult(
                name=f"structure:{name}",
                passed=False,
                detail="unknown validator",
            )
        ]
    try:
        if name in _CONFIGURED_VALIDATORS or clean_config:
            checks = fn(
                archive,
                expected_files,
                validator_config=clean_config,
            )
        else:
            try:
                checks = fn(archive, expected_files)
            except TypeError:
                checks = fn(archive)
    except Exception as exc:
        checks = [
            CheckResult(
                name=f"structure:{name}",
                passed=False,
                detail=f"validator error: {exc}",
            )
        ]
    return execution, timeout, checks
