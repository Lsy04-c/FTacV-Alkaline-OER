"""Canonical electrode-scale parameters for the M0 total-current model.

The M0 equations depend on ``A``, ``Cdl`` and ``gamma`` only through
``CdlA = A*Cdl`` and ``GammaA = A*gamma``.  This module converts either
representation to a single, checked parameter dictionary while preserving
legacy fields for existing solver bridges.
"""

from __future__ import annotations

import math
from typing import Any, Mapping


def _positive(name: str, value: Any) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(f"{name} must be finite and strictly positive")
    return number


def _require_close(name: str, actual: float, expected: float) -> None:
    if not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=0.0):
        raise ValueError(
            f"{name} conflicts with the legacy A/Cdl/gamma representation"
        )


def canonicalize_electrode_scale(
    params: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a checked total-current electrode-scale representation.

    Legacy ``A/Cdl/gamma`` inputs remain accepted.  Canonical
    ``CdlA/GammaA`` inputs may omit ``A``; in that case an internal area of
    one is used only to construct equivalent legacy fields.  A density-current
    observation contract is deliberately unsupported until it receives its
    own model and data schema.
    """

    result = dict(params)
    basis = str(result.get("current_basis", "total"))
    if basis not in {"total", "total_current"}:
        raise ValueError(
            "current_basis must be 'total' for the M0 total-current model"
        )

    source = result.get("_electrode_scale_source")
    if source not in {None, "legacy", "canonical", "redundant_checked"}:
        raise ValueError("_electrode_scale_source is invalid")

    has_cdl_a = "CdlA" in result
    has_gamma_a = "GammaA" in result
    if source != "legacy" and has_cdl_a != has_gamma_a:
        raise ValueError("CdlA and GammaA must be provided together")
    canonical_present = has_cdl_a and has_gamma_a

    has_cdl = "Cdl" in result
    has_gamma = "gamma" in result
    if source != "canonical" and has_cdl != has_gamma:
        raise ValueError("Cdl and gamma must be provided together")
    legacy_pair_present = has_cdl and has_gamma
    if source != "canonical" and legacy_pair_present and "A" not in result:
        raise ValueError("A is required with legacy Cdl and gamma")

    if source == "legacy" and not legacy_pair_present:
        raise ValueError("legacy electrode scale requires A/Cdl/gamma")
    if source == "canonical" and not canonical_present:
        raise ValueError("canonical electrode scale requires CdlA/GammaA")
    if source is None and not canonical_present and not legacy_pair_present:
        raise ValueError("provide A/Cdl/gamma or CdlA/GammaA")

    area = _positive("A", result.get("A", 1.0))

    if legacy_pair_present and source != "canonical":
        cdl_a_legacy = area * _positive("Cdl", result["Cdl"])
        gamma_a_legacy = area * _positive("gamma", result["gamma"])

    if canonical_present and source != "legacy":
        cdl_a = _positive("CdlA", result["CdlA"])
        gamma_a = _positive("GammaA", result["GammaA"])
        if legacy_pair_present and source in {None, "redundant_checked"}:
            _require_close("CdlA", cdl_a, cdl_a_legacy)
            _require_close("GammaA", gamma_a, gamma_a_legacy)
    else:
        cdl_a = cdl_a_legacy
        gamma_a = gamma_a_legacy

    if source is None:
        if canonical_present and legacy_pair_present:
            source = "redundant_checked"
        elif canonical_present:
            source = "canonical"
        else:
            source = "legacy"

    result.update(
        current_basis="total",
        A=area,
        Cdl=cdl_a / area,
        gamma=gamma_a / area,
        CdlA=cdl_a,
        GammaA=gamma_a,
        _electrode_scale_source=source,
    )
    return result
