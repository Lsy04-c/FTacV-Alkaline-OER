"""Tests for experimental noise evidence used by Gate A6."""

import numpy as np

from scripts.estimate_recovery_noise import build_noise_evidence


def test_noise_evidence_selects_conservative_dataset_max(tmp_path):
    low = tmp_path / "low.txt"
    high = tmp_path / "high.txt"
    time = np.arange(2000, dtype=float) / 1000.0
    potential = np.sin(time)
    low_current = np.round(np.sin(time) / 0.01) * 0.01
    high_current = np.round(np.sin(time) / 0.02) * 0.02
    np.savetxt(low, np.column_stack([potential, low_current, time]))
    np.savetxt(high, np.column_stack([potential, high_current, time]))

    evidence = build_noise_evidence([low, high])

    fractions = [
        row["noise"]["noise_fraction"] for row in evidence["datasets"]
    ]
    assert evidence["selection_rule"] == "maximum_dataset_noise_floor"
    assert evidence["selected_noise_fraction"] == max(fractions)
    assert all(row["sha256"] for row in evidence["datasets"])
    assert all(row["noise"]["method"] == "quantization_floor"
               for row in evidence["datasets"])
