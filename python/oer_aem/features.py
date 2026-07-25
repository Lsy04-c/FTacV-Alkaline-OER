"""Complex harmonic features for FTacV inversion and diagnostics."""

from __future__ import annotations

import numpy as np

from .signal import extract_complex_harmonics


def complex_harmonic_metrics(
    signal,
    fs: float,
    f0: float,
    n_harmonics: int = 7,
):
    """Return complex coefficients, amplitude, phase, local noise, and SNR."""
    coefficients, noise = extract_complex_harmonics(
        signal,
        fs=fs,
        f0=f0,
        n_harmonics=n_harmonics,
    )
    amplitude = np.abs(coefficients)
    snr = amplitude / np.maximum(noise, np.finfo(float).eps)
    return {
        "complex": coefficients,
        "amplitude": amplitude,
        "phase": np.angle(coefficients),
        "noise": noise,
        "snr": snr,
    }
