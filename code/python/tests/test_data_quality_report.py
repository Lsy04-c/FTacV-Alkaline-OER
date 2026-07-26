"""Tests for data-quality report summaries."""

import importlib.util
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[3] / "code" / "python" / "scripts" / "analyze_data_quality.py"
)
SPEC = importlib.util.spec_from_file_location("analyze_data_quality", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_harmonic_summary_distinguishes_common_and_optional_channels():
    results = [
        {"fit_harmonics": "[1, 2, 3, 4, 5]"},
        {"fit_harmonics": "[1, 2, 3]"},
        {"fit_harmonics": "[1, 2, 3, 4]"},
    ]

    summary = MODULE.summarize_fit_harmonics(results)

    assert summary["common"] == [1, 2, 3]
    assert summary["optional"] == [4, 5]
    assert summary["diagnostic_only"] == [6, 7]
