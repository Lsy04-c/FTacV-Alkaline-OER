"""Tests for complex FTacV harmonic features."""

import numpy as np
import pytest

from oer_aem.features import complex_harmonic_metrics
from oer_aem import signal as signal_module
from oer_aem.signal import extract_complex_harmonics, lockin_harmonics


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


# --- lock-in amplifier tests ---

def test_lockin_recovers_steady_state_amplitude_and_phase():
    """Lock-in should recover constant A and φ for a pure multi-harmonic signal."""
    f0, fs, duration = 5.0, 500.0, 4.0
    t = np.arange(0.0, duration, 1.0 / fs)
    # Two harmonics with known amplitude and phase, plus small DC offset
    signal = (
        1.0 * np.cos(2 * np.pi * 1 * f0 * t + 0.30)
        + 0.4 * np.cos(2 * np.pi * 2 * f0 * t - 0.50)
        + 0.1  # DC offset — should be rejected by the lock-in
    )
    result = lockin_harmonics(signal, t, f0, harmonics=[1, 2],
                              potential_resolution=0.1, scan_rate=1.0)

    # Trim filter transients: discard first/last 2/(fc) seconds
    fc = result["fc_used"]
    transient = int(2.0 / fc * fs)
    mid = slice(transient, -transient)

    amp1_mid = result["amplitude"][0][mid]
    amp2_mid = result["amplitude"][1][mid]
    phase1_mid = result["phase"][0][mid]
    phase2_mid = result["phase"][1][mid]

    # Amplitude should be near the true values in the steady mid-section
    assert float(np.mean(amp1_mid)) == pytest.approx(1.0, rel=0.05)
    assert float(np.mean(amp2_mid)) == pytest.approx(0.4, rel=0.05)

    # Phase should be near the true values
    mean_phase1 = float(np.mean(phase1_mid))
    mean_phase2 = float(np.mean(phase2_mid))
    assert np.angle(np.exp(1j * (mean_phase1 - 0.30))) == pytest.approx(0.0, abs=0.06)
    assert np.angle(np.exp(1j * (mean_phase2 + 0.50))) == pytest.approx(0.0, abs=0.06)


def test_lockin_amplitude_tracks_linear_ramp():
    """Lock-in amplitude should track a linearly increasing harmonic envelope."""
    f0, fs, duration = 5.0, 500.0, 4.0
    t = np.arange(0.0, duration, 1.0 / fs)
    ramp = np.linspace(0.5, 2.0, len(t))
    signal = ramp * np.cos(2 * np.pi * f0 * t + 0.30)
    result = lockin_harmonics(signal, t, f0, harmonics=[1],
                              potential_resolution=0.1, scan_rate=1.0)

    fc = result["fc_used"]
    transient = int(2.0 / fc * fs)
    mid = slice(transient, -transient)

    amp_mid = result["amplitude"][0][mid]
    ramp_mid = ramp[mid]

    # Linear correlation between recovered amp and true ramp should be strong
    corr = np.corrcoef(amp_mid, ramp_mid)[0, 1]
    assert corr > 0.90


def test_lockin_rejects_low_f0_request():
    """Lock-in should raise for f0 <= 0."""
    t = np.arange(0.0, 1.0, 0.01)
    signal = np.cos(2 * np.pi * 5.0 * t)
    with pytest.raises(ValueError, match="positive"):
        lockin_harmonics(signal, t, f0=0.0)


def test_lockin_nyquist_check():
    """Lock-in should raise when requested harmonics exceed Nyquist."""
    fs = 100.0
    t = np.arange(0.0, 1.0, 1.0 / fs)
    signal = np.cos(2 * np.pi * 10.0 * t)
    with pytest.raises(ValueError, match="Nyquist"):
        lockin_harmonics(signal, t, f0=10.0, harmonics=[6])  # 6*10=60 > 50 Nyquist


def test_lockin_complex_matches_reported_amplitude_and_phase():
    f0, fs = 5.0, 500.0
    t = np.arange(0.0, 4.0, 1.0 / fs)
    signal = 0.8 * np.cos(2.0 * np.pi * f0 * t + 0.7)

    result = lockin_harmonics(
        signal,
        t,
        f0,
        harmonics=[1],
        potential_resolution=0.1,
        scan_rate=1.0,
    )

    valid = result["valid_mask"]
    complex_values = np.asarray(result["complex"][0])[valid]
    amplitude = np.asarray(result["amplitude"][0])[valid]
    phase = np.asarray(result["phase"][0])[valid]

    assert amplitude == pytest.approx(np.abs(complex_values), rel=1e-12, abs=1e-12)
    phase_error = np.angle(np.exp(1j * (phase - np.angle(complex_values))))
    assert phase_error == pytest.approx(np.zeros_like(phase_error), abs=1e-12)


def test_lockin_uses_explicit_applied_potential_phase_reference():
    f0, fs = 5.0, 500.0
    t = np.arange(0.0, 4.0, 1.0 / fs)
    applied_phase = 2.0 * np.pi * f0 * t + 0.85
    signal = np.cos(applied_phase + 0.30)

    result = lockin_harmonics(
        signal,
        t,
        f0,
        harmonics=[1],
        potential_resolution=0.1,
        scan_rate=1.0,
        reference_phase=applied_phase,
    )

    valid_phase = np.asarray(result["phase"][0])[result["valid_mask"]]
    recovered = signal_module.circular_mean_phase(valid_phase)
    assert np.angle(np.exp(1j * (recovered - 0.30))) == pytest.approx(0.0, abs=0.04)


def test_circular_mean_phase_preserves_values_across_wrap_boundary():
    phases = np.array([np.pi - 0.05, -np.pi + 0.05])

    mean_phase = signal_module.circular_mean_phase(phases)

    assert abs(abs(mean_phase) - np.pi) < 0.06


def test_estimate_reference_phase_recovers_applied_potential_fundamental():
    f0, fs = 5.0, 500.0
    t = np.arange(0.0, 4.0, 1.0 / fs)
    expected = 2.0 * np.pi * f0 * t + 0.60
    potential = 1.0 + 0.01 * t + 0.16 * np.cos(expected)

    recovered = signal_module.estimate_reference_phase(potential, t, f0)

    phase_error = np.angle(np.exp(1j * (recovered - expected)))
    assert phase_error == pytest.approx(np.zeros_like(phase_error), abs=1e-3)


@pytest.mark.parametrize(
    ("points_per_cycle", "n_cycles"),
    [(32, 24), (32, 40), (64, 24), (64, 40)],
)
def test_lockin_peak_is_stable_across_sampling_and_record_length(
    points_per_cycle,
    n_cycles,
):
    f0 = 5.0
    fs = points_per_cycle * f0
    t = np.arange(n_cycles * points_per_cycle) / fs
    e_dc = np.linspace(1.0, 2.0, t.size)
    expected_peak = 1.60
    envelope = 0.2 + np.exp(-0.5 * ((e_dc - expected_peak) / 0.08) ** 2)
    reference_phase = 2.0 * np.pi * f0 * t - np.pi / 2.0
    current = envelope * np.cos(reference_phase + 0.35)

    result = lockin_harmonics(
        current,
        t,
        f0,
        harmonics=[1],
        potential_resolution=0.025,
        scan_rate=1.0 / (t[-1] - t[0]),
        reference_phase=reference_phase,
    )

    valid = result["valid_mask"]
    recovered_peak = float(e_dc[valid][np.argmax(result["amplitude"][0][valid])])
    assert abs(recovered_peak - expected_peak) < 0.005
