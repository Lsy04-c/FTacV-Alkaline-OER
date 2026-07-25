"""Tests for complex FTacV harmonic features."""

import numpy as np
import pytest

from oer_aem.features import complex_harmonic_metrics
from oer_aem.signal import extract_complex_harmonics


def test_complex_harmonics_recover_amplitude_and_relative_phase():
    fs, f0, duration = 512.0, 4.0, 8.0
    time = np.arange(0.0, duration, 1.0 / fs)
    signal = 2.0 * np.cos(2 * np.pi * f0 * time + 0.30)
    signal += 0.5 * np.cos(2 * np.pi * 2 * f0 * time - 0.40)

    metrics = complex_harmonic_metrics(
        signal,
        fs=fs,
        f0=f0,
        n_harmonics=2,
    )

    assert metrics["amplitude"] == pytest.approx(
        [2.0, 0.5],
        rel=0.03,
    )
    first_error = np.angle(
        np.exp(1j * (metrics["phase"][0] - 0.30))
    )
    second_error = np.angle(
        np.exp(1j * (metrics["phase"][1] + 0.40))
    )
    assert first_error == pytest.approx(0.0, abs=0.04)
    assert second_error == pytest.approx(0.0, abs=0.04)


def test_snr_rejects_noise_dominated_harmonic():
    rng = np.random.default_rng(7)
    fs, f0 = 512.0, 4.0
    time = np.arange(0.0, 8.0, 1.0 / fs)
    signal = np.cos(2 * np.pi * f0 * time)
    signal += 0.02 * rng.normal(size=time.size)

    metrics = complex_harmonic_metrics(
        signal,
        fs=fs,
        f0=f0,
        n_harmonics=3,
    )

    assert metrics["snr"][0] > 10.0
    assert metrics["snr"][2] < metrics["snr"][0]


def test_complex_harmonics_require_nyquist_headroom():
    signal = np.ones(128)

    with pytest.raises(ValueError, match="Nyquist"):
        complex_harmonic_metrics(
            signal,
            fs=16.0,
            f0=4.0,
            n_harmonics=3,
        )


@pytest.mark.parametrize("points_per_cycle", [32, 64])
@pytest.mark.parametrize("n_cycles", [16, 32])
def test_h1_h7_recovery_is_stable_across_sampling_and_record_length(
    points_per_cycle,
    n_cycles,
):
    f0 = 5.0
    fs = points_per_cycle * f0
    time = np.arange(n_cycles * points_per_cycle) / fs
    expected_amplitude = np.linspace(1.0, 0.25, 7)
    expected_phase = np.linspace(-0.6, 0.6, 7)
    signal = sum(
        amplitude
        * np.cos(2 * np.pi * harmonic * f0 * time + phase)
        for harmonic, (amplitude, phase) in enumerate(
            zip(expected_amplitude, expected_phase),
            start=1,
        )
    )

    metrics = complex_harmonic_metrics(
        signal,
        fs=fs,
        f0=f0,
        n_harmonics=7,
    )

    assert metrics["amplitude"] == pytest.approx(
        expected_amplitude,
        rel=0.01,
    )
    phase_error = np.angle(
        np.exp(1j * (metrics["phase"] - expected_phase))
    )
    assert phase_error == pytest.approx(np.zeros(7), abs=0.01)


def test_h1_h7_coefficients_are_stable_to_noise_window_width():
    points_per_cycle, n_cycles, f0 = 32, 24, 5.0
    fs = points_per_cycle * f0
    time = np.arange(n_cycles * points_per_cycle) / fs
    signal = sum(
        np.cos(2 * np.pi * harmonic * f0 * time + 0.1 * harmonic)
        / harmonic
        for harmonic in range(1, 8)
    )

    narrow, _ = extract_complex_harmonics(
        signal,
        fs=fs,
        f0=f0,
        n_harmonics=7,
        side_bins=2,
    )
    wide, _ = extract_complex_harmonics(
        signal,
        fs=fs,
        f0=f0,
        n_harmonics=7,
        side_bins=8,
    )

    assert wide == pytest.approx(narrow, rel=1e-12, abs=1e-12)
