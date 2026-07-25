"""Tests for complex FTacV harmonic features."""

import numpy as np
import pytest

from oer_aem.features import complex_harmonic_metrics


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
