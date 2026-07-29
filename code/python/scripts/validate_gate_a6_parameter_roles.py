#!/usr/bin/env python3
"""Validate the evidence-backed Gate A6 parameter-role registry."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
ARCHIVE_ARTIFACTS = (
    "parameter_roles.snapshot.json",
    "validation_report.json",
)
EXPECTED_PARAMETERS = {
    "k0_1",
    "k0_2",
    "k0_3",
    "k0_4",
    "k0_pre",
    "gamma",
    "G_OH",
    "G_O",
    "scaling_OOH_OH",
    "E0_pre",
    "Cdl",
    "Ru",
    "A",
}
TOP_LEVEL_FIELDS = {
    "schema_version",
    "gate",
    "status",
    "eligible_for_real_inversion",
    "free_parameters",
    "narrow_prior_parameters",
    "eligible_pairs",
    "evidence",
    "parameters",
}
PARAMETER_FIELDS = {
    "name",
    "role",
    "fixing_basis",
    "evidence_ids",
    "fixed_value_known_accurate",
    "inversion_point_estimate_reportable",
    "structurally_unidentifiable",
    "allowed_use",
    "prohibited_claims",
    "reason",
}
ROLES = {"fixed", "narrow_prior", "free", "diagnostic_only"}
FIXING_BASES = {
    "external_input",
    "calibrated_input",
    "model_assumption",
    "low_sensitivity",
    "coupling_control",
}
EXPECTED_ROLES = {
    "A": ("fixed", "external_input"),
    "Cdl": ("fixed", "calibrated_input"),
    "Ru": ("fixed", "calibrated_input"),
    "E0_pre": ("fixed", "calibrated_input"),
    "k0_pre": ("fixed", "calibrated_input"),
    "gamma": ("fixed", "coupling_control"),
    "k0_4": ("fixed", "low_sensitivity"),
    "scaling_OOH_OH": ("fixed", "coupling_control"),
    "k0_1": ("diagnostic_only", None),
    "k0_2": ("diagnostic_only", None),
    "k0_3": ("diagnostic_only", None),
    "G_OH": ("diagnostic_only", None),
    "G_O": ("diagnostic_only", None),
}
SENSITIVITY_EVIDENCE = {
    "sensitivity_legacy",
    "sensitivity_complex",
    "sensitivity_lockin",
    "sensitivity_hybrid",
}
REQUIRED_EVIDENCE = {
    **{
        name: SENSITIVITY_EVIDENCE
        for name, (role, _) in EXPECTED_ROLES.items()
        if role == "fixed"
    },
    "k0_1": {"single_profiles", "reduced_recovery"},
    "k0_2": {"stage2_recovery", "optimizer_development", "sobol_confirmation"},
    "k0_3": {"stage2_recovery", "optimizer_development", "sobol_confirmation"},
    "G_OH": {"single_profiles", "reduced_recovery"},
    "G_O": {"stage2_recovery", "optimizer_development", "sobol_confirmation"},
}
EXIT_CODES = {
    "PASS": 0,
    "FAIL_ROLE_CONTRACT": 2,
    "FAIL_NUMERICAL": 3,
    "FAIL_STRUCTURE": 4,
}


class NumericalRegistryError(ValueError):
    """Raised when strict JSON parsing encounters a non-finite number."""


def _reject_constant(value: str) -> None:
    raise NumericalRegistryError(f"non-finite JSON constant: {value}")


def _empty_report(gate: str = "FAIL_STRUCTURE") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "gate_version": "A6-roles",
        "gate": gate,
        "parameter_count": 0,
        "role_counts": {
            "fixed": 0,
            "narrow_prior": 0,
            "free": 0,
            "diagnostic_only": 0,
        },
        "structure_errors": [],
        "numerical_errors": [],
        "role_contract_errors": [],
    }


def _valid_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def _validate_evidence(
    project_root: Path,
    evidence: Any,
) -> tuple[set[str], list[str]]:
    errors: list[str] = []
    if not isinstance(evidence, list) or not evidence:
        return set(), ["evidence must be a non-empty list"]
    evidence_ids: list[Any] = []
    for item in evidence:
        if not isinstance(item, dict) or set(item) != {
            "id",
            "path",
            "sha256",
        }:
            errors.append("evidence record fields mismatch")
            continue
        evidence_id = item.get("id")
        evidence_ids.append(evidence_id)
        if not isinstance(evidence_id, str) or not evidence_id:
            errors.append("evidence ID must be a non-empty string")
        if not _valid_relative_path(item.get("path")):
            errors.append("evidence path must be project-relative")
            continue
        source = project_root / item["path"]
        if not source.is_file():
            errors.append(f"evidence file is missing: {item['path']}")
            continue
        observed = hashlib.sha256(source.read_bytes()).hexdigest()
        if item.get("sha256") != observed:
            errors.append(f"evidence hash mismatch: {item['path']}")
    if len(evidence_ids) != len(set(evidence_ids)):
        errors.append("evidence IDs must be unique")
    return {
        value for value in evidence_ids if isinstance(value, str)
    }, errors


def _validate_fixed(item: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if item.get("fixing_basis") not in FIXING_BASES:
        errors.append(f"{item.get('name')}: invalid fixing basis")
    if item.get("fixed_value_known_accurate") is not False:
        errors.append(f"{item.get('name')}: fixed value claimed accurate")
    if item.get("inversion_point_estimate_reportable") is not False:
        errors.append(f"{item.get('name')}: fixed point estimate reportable")
    prohibited = item.get("prohibited_claims")
    if not isinstance(prohibited, list) or not {
        "fixed_value_is_known_accurate",
        "fixed_value_has_no_uncertainty",
        "credible_inversion_point_estimate",
    }.issubset(prohibited):
        errors.append(f"{item.get('name')}: fixed claim guard missing")
    return errors


def _validate_diagnostic(item: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if item.get("fixing_basis") is not None:
        errors.append(f"{item.get('name')}: diagnostic fixing basis set")
    if item.get("fixed_value_known_accurate") is not False:
        errors.append(f"{item.get('name')}: diagnostic value claimed accurate")
    if item.get("inversion_point_estimate_reportable") is not False:
        errors.append(f"{item.get('name')}: diagnostic estimate reportable")
    prohibited = item.get("prohibited_claims")
    if not isinstance(prohibited, list) or not {
        "credible_inversion_point_estimate",
        "mathematically_structurally_unidentifiable",
    }.issubset(prohibited):
        errors.append(f"{item.get('name')}: diagnostic claim guard missing")
    return errors


def validate_registry(
    project_root: Path,
    registry: dict[str, Any],
) -> dict[str, Any]:
    """Validate structure, cited evidence bytes and role semantics."""
    report = _empty_report()
    if not isinstance(registry, dict) or set(registry) != TOP_LEVEL_FIELDS:
        report["structure_errors"].append("top-level fields mismatch")
        return report
    evidence_ids, evidence_errors = _validate_evidence(
        project_root, registry.get("evidence")
    )
    report["structure_errors"].extend(evidence_errors)
    parameters = registry.get("parameters")
    if not isinstance(parameters, list):
        report["structure_errors"].append("parameters must be a list")
        return report
    report["parameter_count"] = len(parameters)
    names = [
        item.get("name") if isinstance(item, dict) else None
        for item in parameters
    ]
    if (
        len(names) != 13
        or len(set(names)) != 13
        or set(names) != EXPECTED_PARAMETERS
    ):
        report["structure_errors"].append("parameter set mismatch")

    for item in parameters:
        if not isinstance(item, dict) or set(item) != PARAMETER_FIELDS:
            report["structure_errors"].append(
                "parameter record fields mismatch"
            )
            continue
        references = item.get("evidence_ids")
        if (
            not isinstance(references, list)
            or not references
            or any(value not in evidence_ids for value in references)
        ):
            report["structure_errors"].append(
                f"{item.get('name')}: invalid evidence references"
            )
        if not isinstance(item.get("reason"), str) or not item["reason"]:
            report["structure_errors"].append(
                f"{item.get('name')}: reason is missing"
            )
        if not isinstance(item.get("allowed_use"), list):
            report["structure_errors"].append(
                f"{item.get('name')}: allowed_use must be a list"
            )

    if report["structure_errors"]:
        return report

    if (
        registry.get("schema_version") != 1
        or registry.get("gate") != "A6"
        or registry.get("status") != "FAIL_RECOVERY"
        or registry.get("eligible_for_real_inversion") is not False
    ):
        report["role_contract_errors"].append(
            "Gate A6 closure fields mismatch"
        )
    for field in (
        "free_parameters",
        "narrow_prior_parameters",
        "eligible_pairs",
    ):
        if registry.get(field) != []:
            report["role_contract_errors"].append(f"{field} must be empty")

    for item in parameters:
        role = item["role"]
        if role not in ROLES:
            report["role_contract_errors"].append(
                f"{item['name']}: invalid role"
            )
            continue
        if (role, item.get("fixing_basis")) != EXPECTED_ROLES[item["name"]]:
            report["role_contract_errors"].append(
                f"{item['name']}: role mapping mismatch"
            )
        if not REQUIRED_EVIDENCE[item["name"]].issubset(
            item["evidence_ids"]
        ):
            report["role_contract_errors"].append(
                f"{item['name']}: required evidence missing"
            )
        report["role_counts"][role] += 1
        if item.get("structurally_unidentifiable") is not False:
            report["role_contract_errors"].append(
                f"{item['name']}: structural unidentifiability overclaimed"
            )
        if role == "fixed":
            report["role_contract_errors"].extend(_validate_fixed(item))
        elif role == "diagnostic_only":
            report["role_contract_errors"].extend(
                _validate_diagnostic(item)
            )
        else:
            report["role_contract_errors"].append(
                f"{item['name']}: role is not allowed in current closure"
            )
    if report["role_counts"] != {
        "fixed": 8,
        "narrow_prior": 0,
        "free": 0,
        "diagnostic_only": 5,
    }:
        report["role_contract_errors"].append("role counts mismatch")

    report["gate"] = (
        "FAIL_ROLE_CONTRACT"
        if report["role_contract_errors"]
        else "PASS"
    )
    return report


def validate_registry_file(
    project_root: Path,
    registry_path: Path,
) -> dict[str, Any]:
    """Strictly load and validate one registry file."""
    try:
        value = json.loads(
            registry_path.read_text(encoding="utf-8"),
            parse_constant=_reject_constant,
        )
    except NumericalRegistryError as exc:
        report = _empty_report("FAIL_NUMERICAL")
        report["numerical_errors"].append(str(exc))
        return report
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        report = _empty_report()
        report["structure_errors"].append(str(exc))
        return report
    return validate_registry(project_root, value)


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode()


def _atomic_write(path: Path, payload: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        temporary = Path(temporary_name)
        if temporary.exists():
            temporary.unlink()


def write_formal_archive(
    output: Path,
    *,
    registry: dict[str, Any],
    report: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    """Atomically write a new Gate A6 role-closure archive."""
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("output directory must be new or empty")
    if report.get("gate") != "PASS":
        raise ValueError("refusing to archive a failing role registry")
    output.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "parameter_roles.snapshot.json": _json_bytes(registry),
        "validation_report.json": _json_bytes(report),
    }
    written_manifest = dict(manifest)
    written_manifest["artifact_sha256"] = {
        name: hashlib.sha256(payload).hexdigest()
        for name, payload in artifacts.items()
    }
    for name, payload in artifacts.items():
        _atomic_write(output / name, payload)
    _atomic_write(
        output / "run_manifest.json", _json_bytes(written_manifest)
    )


def _strict_load(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=_reject_constant,
    )


def validate_archive(
    archive: Path,
    *,
    project_root: Path = ROOT,
) -> dict[str, Any]:
    """Revalidate frozen bytes without reading the source registry."""
    required = [
        archive / name
        for name in (*ARCHIVE_ARTIFACTS, "run_manifest.json")
    ]
    missing = [path.name for path in required if not path.is_file()]
    if missing:
        report = _empty_report()
        report["structure_errors"].append(
            f"missing archive artifacts: {sorted(missing)}"
        )
        return report
    try:
        manifest = _strict_load(archive / "run_manifest.json")
    except NumericalRegistryError as exc:
        report = _empty_report("FAIL_NUMERICAL")
        report["numerical_errors"].append(str(exc))
        return report
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        report = _empty_report()
        report["structure_errors"].append(str(exc))
        return report
    if not isinstance(manifest, dict):
        report = _empty_report()
        report["structure_errors"].append("manifest must be an object")
        return report
    hashes = manifest.get("artifact_sha256")
    if not isinstance(hashes, dict) or set(hashes) != set(ARCHIVE_ARTIFACTS):
        report = _empty_report()
        report["structure_errors"].append("manifest artifact hashes mismatch")
        return report
    for name in ARCHIVE_ARTIFACTS:
        observed = hashlib.sha256((archive / name).read_bytes()).hexdigest()
        if hashes.get(name) != observed:
            report = _empty_report()
            report["structure_errors"].append(f"{name} hash mismatch")
            return report
    if (
        manifest.get("schema_version") != 1
        or manifest.get("gate_version") != "A6-roles"
        or manifest.get("dirty") is not False
        or manifest.get("dirty_paths") != []
        or manifest.get("runs_numerical_calculation") is not False
        or not isinstance(manifest.get("commit"), str)
        or re.fullmatch(r"[0-9a-f]{40}", manifest["commit"]) is None
    ):
        report = _empty_report()
        report["structure_errors"].append("manifest provenance mismatch")
        return report
    try:
        registry = _strict_load(
            archive / "parameter_roles.snapshot.json"
        )
        stored_report = _strict_load(archive / "validation_report.json")
    except NumericalRegistryError as exc:
        report = _empty_report("FAIL_NUMERICAL")
        report["numerical_errors"].append(str(exc))
        return report
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        report = _empty_report()
        report["structure_errors"].append(str(exc))
        return report
    report = validate_registry(project_root, registry)
    if stored_report != report:
        mismatch = _empty_report()
        mismatch["structure_errors"].append(
            "stored validation report mismatch"
        )
        return mismatch
    return report


def _git_value(project_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _build_manifest(
    project_root: Path,
    registry_path: Path,
    argv: list[str],
) -> dict[str, Any]:
    status = _git_value(project_root, "status", "--porcelain=v1")
    absolute_registry = (
        registry_path
        if registry_path.is_absolute()
        else project_root / registry_path
    )
    return {
        "schema_version": 1,
        "gate_version": "A6-roles",
        "commit": _git_value(project_root, "rev-parse", "HEAD"),
        "dirty": bool(status),
        "dirty_paths": status.splitlines(),
        "registry_path": absolute_registry.relative_to(
            project_root
        ).as_posix(),
        "registry_sha256": hashlib.sha256(
            absolute_registry.read_bytes()
        ).hexdigest(),
        "python_version": platform.python_version(),
        "command": argv,
        "runs_numerical_calculation": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args(argv)
    if args.archive is not None:
        if args.registry is not None or args.output is not None:
            parser.error("--archive is mutually exclusive with registry output")
        report = validate_archive(args.archive)
    else:
        if args.registry is None or args.output is None:
            parser.error("--registry and --output are required together")
        report = validate_registry_file(ROOT, args.registry)
        if report["gate"] == "PASS":
            manifest = _build_manifest(
                ROOT,
                args.registry,
                sys.argv if argv is None else [__file__, *argv],
            )
            if manifest["dirty"]:
                report = _empty_report()
                report["structure_errors"].append(
                    "formal archive requires a clean worktree"
                )
            else:
                registry = _strict_load(args.registry)
                write_formal_archive(
                    args.output,
                    registry=registry,
                    report=report,
                    manifest=manifest,
                )
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return EXIT_CODES[report["gate"]]


if __name__ == "__main__":
    raise SystemExit(main())
