"""Contracts for recommended-protocol joint recovery."""

from scripts.run_multicondition_recovery_smoke import build_condition_configs


def test_high_frequency_condition_preserves_baseline_scan_rate():
    configs = build_condition_configs("cn")

    baseline = configs["baseline_5hz_amp_016"]
    high_frequency = configs["candidate_10hz_matched_scan"]
    assert high_frequency.n_points == 2 * baseline.n_points
    assert high_frequency.scan_rate == baseline.scan_rate
