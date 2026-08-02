"""Contract tests for the development-only effective M0 parameter schema."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = (
    ROOT
    / "config"
    / "parameter-schemas"
    / "m0-total-current-effective-v1.json"
)


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_effective_parameter_schema_excludes_exact_legacy_redundancy():
    schema = _schema()

    assert schema["status"] == "development_only"
    assert schema["current_basis"] == "total"
    assert schema["legacy_mapping"]["CdlA"] == "A*Cdl"
    assert schema["legacy_mapping"]["GammaA"] == "A*gamma"
    assert not {"A", "Cdl", "gamma"}.issubset(
        schema["forward_parameters"]
    )
    assert schema["frozen_workflows"] == ["A6-v2-S1"]
    assert schema["eligible_for_real_inversion"] is False


def test_every_forward_parameter_has_units_role_and_transform():
    schema = _schema()

    assert set(schema["forward_parameters"]) == set(schema["parameters"])
    for name in schema["forward_parameters"]:
        parameter = schema["parameters"][name]
        assert parameter["unit"]
        assert parameter["role"]
        assert parameter["transform"] in {"linear", "log10"}


def test_reporting_area_is_not_a_forward_parameter():
    schema = _schema()

    area = schema["reporting_inputs"]["A"]
    assert "A" not in schema["forward_parameters"]
    assert area["unit"] == "cm^2"
    assert area["used_for"] == ["Cdl", "gamma"]


def test_schema_records_conditional_current_source_and_open_metadata_gap():
    schema = _schema()

    source = schema["current_basis_source"]
    assert source["kind"] == "externally_declared"
    assert source["value"] == "A"
    assert "Current/A" in source["supporting_evidence"]
    assert schema["unresolved_metadata"] == ["instrument_preprocessing"]


def test_every_parameter_has_bounds_or_an_explicit_unresolved_marker():
    schema = _schema()

    for name, parameter in schema["parameters"].items():
        assert "bounds" in parameter, name
        if parameter["bounds"] is None:
            assert parameter["bounds_status"] == "unresolved"
        else:
            lower, upper = parameter["bounds"]
            assert lower < upper
            assert parameter["bounds_source"]

    assert schema["parameters"]["CdlA"]["bounds"] is None
    assert schema["parameters"]["GammaA"]["bounds"] is None
