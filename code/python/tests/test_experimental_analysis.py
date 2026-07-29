from pathlib import Path

import numpy as np
import pytest

from oer_aem.data_contract import read_strict_experimental_trace
from oer_aem.inversion import InversionConfig


ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data" / "raw"


def test_analyze_ftacv_trace_is_available_without_fastapi():
    from oer_aem.experimental import analyze_ftacv_trace

    trace = read_strict_experimental_trace(
        RAW / "ftacv4-ref-1hz.txt"
    )[0]
    result = analyze_ftacv_trace(trace)

    assert result["meta"]["f"] == pytest.approx(1.0, rel=1e-3)
    assert result["meta"]["dE"] == pytest.approx(0.16, rel=5e-3)
    assert len(result["harmonics"]) == 7


def test_build_experimental_target_adds_hybrid_feature_blocks():
    from oer_aem.experimental import (
        analyze_ftacv_trace,
        build_experimental_target,
    )

    trace = read_strict_experimental_trace(
        RAW / "ftacv4-ref-1hz.txt"
    )[0]
    analysis = analyze_ftacv_trace(trace)
    config = InversionConfig(
        E_start=float(analysis["meta"]["E_start"]),
        E_end=float(analysis["meta"]["E_end"]),
        f=float(analysis["meta"]["f"]),
        dE=float(analysis["meta"]["dE"]),
        n_points=2048,
        points_per_cycle=128,
        feature_grid_size=64,
        fit_harmonics=(1, 2, 3),
        feature_mode="hybrid",
    )

    target = build_experimental_target(trace, analysis, config)

    assert np.asarray(target["dc"]).shape == (64,)
    assert len(target["harm"]) == 7
    assert len(target["complex_harmonics"]["complex"]) == 3
    assert len(target["lockin"]["complex"]) == 3
    assert np.asarray(target["lockin"]["valid_mask"]).shape == (64,)
