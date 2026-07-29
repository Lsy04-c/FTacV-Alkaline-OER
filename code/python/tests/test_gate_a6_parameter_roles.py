"""Gate A6 parameter-role registry and closure archive tests."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT
    / "code"
    / "python"
    / "scripts"
    / "validate_gate_a6_parameter_roles.py"
)
REGISTRY = (
    ROOT
    / "config"
    / "parameter-roles"
    / "gate-a6-parameter-roles.json"
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
FIXED = {
    "A": "external_input",
    "Cdl": "calibrated_input",
    "Ru": "calibrated_input",
    "E0_pre": "calibrated_input",
    "k0_pre": "calibrated_input",
    "gamma": "coupling_control",
    "k0_4": "low_sensitivity",
    "scaling_OOH_OH": "coupling_control",
}
DIAGNOSTIC = {"k0_1", "k0_2", "k0_3", "G_OH", "G_O"}
SENSITIVITY_EVIDENCE = {
    "sensitivity_legacy",
    "sensitivity_complex",
    "sensitivity_lockin",
    "sensitivity_hybrid",
}
DIAGNOSTIC_EVIDENCE = {
    "k0_1": {"single_profiles", "reduced_recovery"},
    "k0_2": {"stage2_recovery", "optimizer_development", "sobol_confirmation"},
    "k0_3": {"stage2_recovery", "optimizer_development", "sobol_confirmation"},
    "G_OH": {"single_profiles", "reduced_recovery"},
    "G_O": {"stage2_recovery", "optimizer_development", "sobol_confirmation"},
}


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "validate_gate_a6_parameter_roles", SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _fixed_record(name: str, basis: str) -> dict:
    return {
        "name": name,
        "role": "fixed",
        "fixing_basis": basis,
        "evidence_ids": sorted(SENSITIVITY_EVIDENCE),
        "fixed_value_known_accurate": False,
        "inversion_point_estimate_reportable": False,
        "structurally_unidentifiable": False,
        "allowed_use": [
            "forward_input",
            "fixed_parameter_stress_test",
        ],
        "prohibited_claims": [
            "fixed_value_is_known_accurate",
            "fixed_value_has_no_uncertainty",
            "credible_inversion_point_estimate",
        ],
        "reason": f"{name} is fixed operationally.",
    }


def _diagnostic_record(name: str) -> dict:
    return {
        "name": name,
        "role": "diagnostic_only",
        "fixing_basis": None,
        "evidence_ids": sorted(DIAGNOSTIC_EVIDENCE[name]),
        "fixed_value_known_accurate": False,
        "inversion_point_estimate_reportable": False,
        "structurally_unidentifiable": False,
        "allowed_use": [
            "profile",
            "sensitivity",
            "experimental_design",
        ],
        "prohibited_claims": [
            "credible_inversion_point_estimate",
            "mathematically_structurally_unidentifiable",
        ],
        "reason": f"{name} did not pass the frozen recovery route.",
    }


def _passing_registry(project_root: Path) -> dict:
    evidence = []
    evidence_ids = SENSITIVITY_EVIDENCE | set().union(
        *DIAGNOSTIC_EVIDENCE.values()
    )
    for evidence_id in sorted(evidence_ids):
        evidence_path = project_root / f"{evidence_id}.txt"
        evidence_path.write_text(
            f"{evidence_id} frozen evidence\n", encoding="utf-8"
        )
        evidence.append(
            {
                "id": evidence_id,
                "path": evidence_path.name,
                "sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
            }
        )
    parameters = [
        _fixed_record(name, basis)
        for name, basis in FIXED.items()
    ]
    parameters.extend(
        _diagnostic_record(name) for name in sorted(DIAGNOSTIC)
    )
    return {
        "schema_version": 1,
        "gate": "A6",
        "status": "FAIL_RECOVERY",
        "eligible_for_real_inversion": False,
        "free_parameters": [],
        "narrow_prior_parameters": [],
        "eligible_pairs": [],
        "evidence": evidence,
        "parameters": parameters,
    }


def test_validator_accepts_complete_13_parameter_role_registry(tmp_path):
    module = _load_script()
    registry = _passing_registry(tmp_path)

    report = module.validate_registry(tmp_path, registry)

    assert report["gate"] == "PASS"
    assert report["parameter_count"] == 13
    assert report["role_counts"] == {
        "fixed": 8,
        "narrow_prior": 0,
        "free": 0,
        "diagnostic_only": 5,
    }
    source = SCRIPT.read_text(encoding="utf-8")
    assert "oer_aem" not in source
    assert "run_synthetic_recovery" not in source
    assert "run_optimizer_benchmark" not in source


@pytest.mark.parametrize(
    ("mutation", "expected_gate"),
    [
        ("missing_parameter", "FAIL_STRUCTURE"),
        ("duplicate_parameter", "FAIL_STRUCTURE"),
        ("unknown_parameter", "FAIL_STRUCTURE"),
        ("invalid_role", "FAIL_ROLE_CONTRACT"),
        ("invalid_fixing_basis", "FAIL_ROLE_CONTRACT"),
        ("missing_evidence", "FAIL_STRUCTURE"),
        ("evidence_hash", "FAIL_STRUCTURE"),
        ("nonempty_free_parameters", "FAIL_ROLE_CONTRACT"),
        ("nonempty_narrow_prior", "FAIL_ROLE_CONTRACT"),
        ("fixed_claimed_accurate", "FAIL_ROLE_CONTRACT"),
        ("diagnostic_point_estimate", "FAIL_ROLE_CONTRACT"),
        ("structurally_unidentifiable", "FAIL_ROLE_CONTRACT"),
        ("eligible_pair", "FAIL_ROLE_CONTRACT"),
    ],
)
def test_validator_rejects_role_registry_drift(
    tmp_path,
    mutation,
    expected_gate,
):
    module = _load_script()
    registry = _passing_registry(tmp_path)
    if mutation == "missing_parameter":
        registry["parameters"].pop()
    elif mutation == "duplicate_parameter":
        registry["parameters"][-1] = copy.deepcopy(
            registry["parameters"][0]
        )
    elif mutation == "unknown_parameter":
        registry["parameters"][-1]["name"] = "unknown"
    elif mutation == "invalid_role":
        registry["parameters"][0]["role"] = "estimated"
    elif mutation == "invalid_fixing_basis":
        registry["parameters"][0]["fixing_basis"] = "guess"
    elif mutation == "missing_evidence":
        (tmp_path / registry["evidence"][0]["path"]).unlink()
    elif mutation == "evidence_hash":
        registry["evidence"][0]["sha256"] = "0" * 64
    elif mutation == "nonempty_free_parameters":
        registry["free_parameters"] = ["k0_2"]
    elif mutation == "nonempty_narrow_prior":
        registry["narrow_prior_parameters"] = ["G_O"]
    elif mutation == "fixed_claimed_accurate":
        registry["parameters"][0]["fixed_value_known_accurate"] = True
    elif mutation == "diagnostic_point_estimate":
        diagnostic = next(
            item
            for item in registry["parameters"]
            if item["role"] == "diagnostic_only"
        )
        diagnostic["inversion_point_estimate_reportable"] = True
    elif mutation == "structurally_unidentifiable":
        registry["parameters"][0]["structurally_unidentifiable"] = True
    elif mutation == "eligible_pair":
        registry["eligible_pairs"] = [["k0_2", "G_O"]]

    report = module.validate_registry(tmp_path, registry)

    assert report["gate"] == expected_gate


def test_strict_loader_classifies_nonfinite_json_as_numerical_failure(
    tmp_path,
):
    module = _load_script()
    path = tmp_path / "registry.json"
    path.write_text('{"schema_version": NaN}\n', encoding="utf-8")

    report = module.validate_registry_file(tmp_path, path)

    assert report["gate"] == "FAIL_NUMERICAL"


def test_formal_archive_records_hashes_and_revalidates(tmp_path):
    module = _load_script()
    project_root = tmp_path / "project"
    project_root.mkdir()
    registry = _passing_registry(project_root)
    report = module.validate_registry(project_root, registry)
    output = tmp_path / "archive"

    module.write_formal_archive(
        output,
        registry=registry,
        report=report,
        manifest={
            "schema_version": 1,
            "gate_version": "A6-roles",
            "commit": "1" * 40,
            "dirty": False,
            "dirty_paths": [],
            "registry_path": "registry.json",
            "registry_sha256": "2" * 64,
            "python_version": "3.13.3",
            "command": ["validator"],
            "runs_numerical_calculation": False,
        },
    )

    assert set(path.name for path in output.iterdir()) == {
        "parameter_roles.snapshot.json",
        "validation_report.json",
        "run_manifest.json",
    }
    manifest = json.loads(
        (output / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["commit"] == "1" * 40
    assert manifest["dirty"] is False
    assert manifest["runs_numerical_calculation"] is False
    assert set(manifest["artifact_sha256"]) == {
        "parameter_roles.snapshot.json",
        "validation_report.json",
    }
    for name, digest in manifest["artifact_sha256"].items():
        assert digest == hashlib.sha256((output / name).read_bytes()).hexdigest()
    archive_report = module.validate_archive(
        output, project_root=project_root
    )
    assert archive_report["gate"] == "PASS"

    with pytest.raises(FileExistsError, match="new or empty"):
        module.write_formal_archive(
            output,
            registry=registry,
            report=report,
            manifest={"schema_version": 1},
        )


@pytest.mark.parametrize(
    "artifact",
    [
        "parameter_roles.snapshot.json",
        "validation_report.json",
    ],
)
def test_archive_validator_rejects_artifact_tampering(tmp_path, artifact):
    module = _load_script()
    project_root = tmp_path / "project"
    project_root.mkdir()
    registry = _passing_registry(project_root)
    report = module.validate_registry(project_root, registry)
    output = tmp_path / "archive"
    module.write_formal_archive(
        output,
        registry=registry,
        report=report,
        manifest={
            "schema_version": 1,
            "gate_version": "A6-roles",
            "commit": "1" * 40,
            "dirty": False,
            "dirty_paths": [],
            "registry_path": "registry.json",
            "registry_sha256": "2" * 64,
            "python_version": "3.13.3",
            "command": ["validator"],
            "runs_numerical_calculation": False,
        },
    )
    (output / artifact).write_bytes((output / artifact).read_bytes() + b" ")

    archive_report = module.validate_archive(
        output, project_root=project_root
    )

    assert archive_report["gate"] == "FAIL_STRUCTURE"


def test_real_registry_freezes_exact_evidence_backed_parameter_roles():
    module = _load_script()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    report = module.validate_registry(ROOT, registry)
    mapping = {
        item["name"]: (item["role"], item["fixing_basis"])
        for item in registry["parameters"]
    }

    assert report["gate"] == "PASS"
    assert report["parameter_count"] == 13
    assert report["role_counts"] == {
        "fixed": 8,
        "narrow_prior": 0,
        "free": 0,
        "diagnostic_only": 5,
    }
    assert mapping == {
        **{
            name: ("fixed", basis)
            for name, basis in FIXED.items()
        },
        **{
            name: ("diagnostic_only", None)
            for name in DIAGNOSTIC
        },
    }


def test_validator_rejects_parameter_role_mapping_drift(tmp_path):
    module = _load_script()
    registry = _passing_registry(tmp_path)
    fixed = next(item for item in registry["parameters"] if item["name"] == "A")
    diagnostic = next(
        item for item in registry["parameters"] if item["name"] == "k0_1"
    )
    fixed.update(_diagnostic_record("k0_1"))
    fixed["name"] = "A"
    diagnostic.update(_fixed_record("k0_1", "external_input"))

    report = module.validate_registry(tmp_path, registry)

    assert report["gate"] == "FAIL_ROLE_CONTRACT"


def test_real_registry_rejects_missing_required_evidence():
    module = _load_script()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    parameter = next(
        item for item in registry["parameters"] if item["name"] == "A"
    )
    parameter["evidence_ids"].remove("sensitivity_hybrid")

    report = module.validate_registry(ROOT, registry)

    assert report["gate"] == "FAIL_ROLE_CONTRACT"
