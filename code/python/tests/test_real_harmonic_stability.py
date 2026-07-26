"""Tests for the Gate A4 real-data harmonic stability helpers."""

from types import SimpleNamespace

import numpy as np
import pytest


def test_build_variants_uses_antialiased_downsampling_and_one_sided_trims():
    from scripts import validate_real_harmonic_stability as validation

    time = np.arange(64, dtype=float) / 64.0
    potential = 1.0 + 0.2 * time + 0.05 * np.cos(2.0 * np.pi * time)
    current = np.sin(2.0 * np.pi * time)

    variants = validation.build_variants(time, potential, current)

    assert set(variants) == {
        "full",
        "downsample_2x",
        "downsample_4x",
        "trim_start_10pct",
        "trim_end_10pct",
    }
    assert len(variants["downsample_2x"]["time"]) == 32
    assert len(variants["downsample_4x"]["time"]) == 16
    assert np.all(np.diff(variants["downsample_4x"]["time"]) > 0)
    assert variants["trim_start_10pct"]["time"][0] > time[0]
    assert variants["trim_end_10pct"]["time"][-1] < time[-1]


def test_build_variants_accepts_timestamp_quantization_but_rejects_large_jitter():
    from scripts import validate_real_harmonic_stability as validation

    dt = np.tile([0.99, 1.01], 32)
    quantized_time = np.concatenate(([0.0], np.cumsum(dt)))
    values = np.sin(quantized_time)

    variants = validation.build_variants(quantized_time, values, values)

    assert len(variants["full"]["time"]) == quantized_time.size

    bad_time = quantized_time.copy()
    bad_time[20:] += 0.10
    with pytest.raises(ValueError, match="approximately equally spaced"):
        validation.build_variants(bad_time, values, values)


def test_compare_complex_envelopes_handles_wrapped_phase_and_peak():
    from scripts import validate_real_harmonic_stability as validation

    reference_e = np.linspace(1.0, 2.0, 101)
    reference_amp = 0.2 + np.exp(-0.5 * ((reference_e - 1.6) / 0.08) ** 2)
    reference_phase = np.full(reference_e.size, np.pi - 0.05)
    candidate_phase = np.full(reference_e.size, -np.pi + 0.05)
    reference_z = reference_amp * np.exp(1j * reference_phase)
    candidate_z = reference_amp * np.exp(1j * candidate_phase)

    metrics = validation.compare_complex_envelopes(
        reference_e,
        reference_z,
        np.ones(reference_e.size, dtype=bool),
        reference_e,
        candidate_z,
        np.ones(reference_e.size, dtype=bool),
        potential_resolution=0.025,
    )

    assert metrics["amplitude_nrmse"] == pytest.approx(0.0, abs=1e-12)
    assert metrics["phase_rmse_rad"] == pytest.approx(0.1)
    assert metrics["peak_shift_v"] == pytest.approx(0.0)
    assert metrics["common_valid_fraction"] == pytest.approx(1.0)
    assert metrics["independent_potential_intervals"] == 40


def test_gate_requires_low_order_stability_but_skips_unresolved_high_order():
    from scripts import validate_real_harmonic_stability as validation

    base = {
        "dataset": "FT2",
        "variant": "downsample_2x",
        "harmonic": 2,
        "resolved": True,
        "amplitude_nrmse": 0.01,
        "phase_rmse_rad": 0.11,
        "peak_shift_v": 0.0,
        "peak_comparable": True,
        "common_valid_fraction": 0.9,
        "independent_potential_intervals": 30,
    }

    failed = validation.assess_gate([base])
    skipped = validation.assess_gate(
        [{**base, "harmonic": 7, "resolved": False, "phase_rmse_rad": 3.0}]
    )

    assert failed["passed"] is False
    assert "phase_rmse_rad" in failed["failures"][0]
    assert skipped["passed"] is True


def test_collect_provenance_records_commit_time_and_thread_limits(monkeypatch):
    from scripts import validate_real_harmonic_stability as validation

    monkeypatch.setattr(
        validation.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="abc123\n"),
    )
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "1")
    monkeypatch.setenv("MKL_NUM_THREADS", "1")
    monkeypatch.setenv("NUMEXPR_NUM_THREADS", "1")

    provenance = validation.collect_provenance(validation.ROOT)

    assert provenance["source_commit"] == "abc123"
    assert provenance["started_at_cst"].endswith("+0800")
    assert provenance["thread_limits"] == {
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
    }
