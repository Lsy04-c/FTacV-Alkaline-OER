"""Tests for the exact M0 electrode-scale reparameterization."""

import sys
from pathlib import Path

import pytest


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from oer_aem.electrode_scale import canonicalize_electrode_scale


def test_legacy_scale_is_converted_to_total_quantities():
    result = canonicalize_electrode_scale(
        {"A": 2.0, "Cdl": 1e-5, "gamma": 2.5e-8}
    )

    assert result["current_basis"] == "total"
    assert result["CdlA"] == pytest.approx(2e-5)
    assert result["GammaA"] == pytest.approx(5e-8)


def test_canonical_totals_expand_to_an_equivalent_legacy_tuple():
    result = canonicalize_electrode_scale(
        {"current_basis": "total", "CdlA": 2e-5, "GammaA": 5e-8}
    )

    assert result["A"] == pytest.approx(1.0)
    assert result["Cdl"] == pytest.approx(2e-5)
    assert result["gamma"] == pytest.approx(5e-8)


def test_canonical_totals_use_reporting_area_only_for_legacy_conversion():
    result = canonicalize_electrode_scale(
        {
            "current_basis": "total",
            "A": 2.0,
            "CdlA": 2e-5,
            "GammaA": 5e-8,
        }
    )

    assert result["Cdl"] == pytest.approx(1e-5)
    assert result["gamma"] == pytest.approx(2.5e-8)


def test_inconsistent_redundant_scale_is_rejected():
    with pytest.raises(ValueError, match="CdlA"):
        canonicalize_electrode_scale(
            {
                "A": 2.0,
                "Cdl": 1e-5,
                "gamma": 2.5e-8,
                "CdlA": 3e-5,
                "GammaA": 5e-8,
            }
        )


def test_recanonicalizing_legacy_source_refreshes_stale_derived_totals():
    first = canonicalize_electrode_scale(
        {"A": 2.0, "Cdl": 1e-5, "gamma": 2.5e-8}
    )
    first["gamma"] = 3e-9

    refreshed = canonicalize_electrode_scale(first)

    assert refreshed["GammaA"] == pytest.approx(6e-9)


def test_recanonicalizing_canonical_source_refreshes_legacy_fields():
    first = canonicalize_electrode_scale(
        {"current_basis": "total", "CdlA": 2e-5, "GammaA": 5e-8}
    )
    first["GammaA"] = 6e-8

    refreshed = canonicalize_electrode_scale(first)

    assert refreshed["gamma"] == pytest.approx(6e-8)


def test_partial_canonical_pair_is_rejected():
    with pytest.raises(ValueError, match="CdlA.*GammaA"):
        canonicalize_electrode_scale({"CdlA": 2e-5})


def test_density_basis_is_not_silently_interpreted_as_total_current():
    with pytest.raises(ValueError, match="current_basis"):
        canonicalize_electrode_scale(
            {
                "current_basis": "density",
                "Cdl": 1e-5,
                "gamma": 2.5e-8,
            }
        )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("A", 0.0),
        ("Cdl", -1e-5),
        ("gamma", float("nan")),
        ("CdlA", float("inf")),
        ("GammaA", 0.0),
    ],
)
def test_scale_values_must_be_finite_and_positive(name, value):
    params = {"A": 2.0, "Cdl": 1e-5, "gamma": 2.5e-8}
    if name in {"CdlA", "GammaA"}:
        params.update({"CdlA": 2e-5, "GammaA": 5e-8})
    params[name] = value

    with pytest.raises(ValueError, match=name):
        canonicalize_electrode_scale(params)
