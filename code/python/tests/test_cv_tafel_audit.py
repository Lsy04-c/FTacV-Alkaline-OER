from __future__ import annotations

import json
import hashlib

import pytest


def test_audit_keeps_forward_and_reverse_branches_separate(tmp_path):
    from oer_aem.cv_tafel_audit import audit_chi_cv

    path = tmp_path / "cv.txt"
    path.write_text(
        "Cyclic Voltammetry\n"
        "Scan Rate (V/s) = 0.1\n"
        "Potential/V, Current/A\n"
        "0.0, 1e-5\n"
        "0.1\t4e-5\n"
        "0.2, 1e-4\n"
        "0.2\t2e-4\n"
        "0.1, 8e-5\n"
        "0.0\t2e-5\n"
    )

    report = audit_chi_cv(path, current_window_a=(3e-5, 3e-4))

    assert report["classification"] == "EXPLORATORY_ONLY"
    assert report["header"]["scan_rate_v_s"] == 0.1
    assert report["forward"]["n_points"] == 3
    assert report["reverse"]["n_points"] == 3
    assert report["hysteresis"]["median_abs_current_difference_a"] > 0.0
    assert report["input_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert "potential_reference_unresolved" in report["blockers"]
    assert "ir_correction_unresolved" in report["blockers"]


def test_cli_writes_hashed_exploratory_report(tmp_path):
    from scripts.audit_chi_cv_tafel import main

    source = tmp_path / "cv.txt"
    source.write_text(
        "Scan Rate (V/s) = 0.1\nPotential/V, Current/A\n"
        + "\n".join(
            f"{index / 100:.2f},{3e-5 * 10 ** (index / 19):.9g}"
            for index in range(20)
        )
        + "\n"
        + "\n".join(
            f"{0.19 - index / 100:.2f},{4e-5 * 10 ** (index / 19):.9g}"
            for index in range(20)
        )
    )
    output_dir = tmp_path / "audit"

    main(["--input", str(source), "--output-dir", str(output_dir)])

    report = json.loads((output_dir / "cv_audit.json").read_text())
    assert report["classification"] == "EXPLORATORY_ONLY"
    assert report["input_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert report["blockers"] == [
        "potential_reference_unresolved",
        "ir_correction_unresolved",
        "electrode_area_unresolved",
        "steady_state_unproven",
    ]
    assert report["forward"]["raw_current_candidate"]["available"] is True


def test_cli_refuses_to_overwrite_existing_audit(tmp_path):
    from scripts.audit_chi_cv_tafel import main

    source = tmp_path / "cv.txt"
    source.write_text(
        "Potential/V, Current/A\n"
        "0.0,1e-5\n0.1,4e-5\n0.2,1e-4\n0.1,8e-5\n0.0,2e-5\n"
    )
    output_dir = tmp_path / "audit"
    main(["--input", str(source), "--output-dir", str(output_dir)])

    with pytest.raises(FileExistsError, match="refusing to overwrite audit"):
        main(["--input", str(source), "--output-dir", str(output_dir)])


def test_audit_rejects_nonfinite_numeric_rows(tmp_path):
    from oer_aem.cv_tafel_audit import audit_chi_cv

    source = tmp_path / "cv.txt"
    source.write_text(
        "Potential/V, Current/A\n"
        "0.0,1e-5\n0.1,4e-5\n0.2,nan\n0.1,8e-5\n0.0,2e-5\n"
    )

    with pytest.raises(ValueError, match="non-finite"):
        audit_chi_cv(source)


def test_audit_rejects_ambiguous_turning_plateau(tmp_path):
    from oer_aem.cv_tafel_audit import audit_chi_cv

    source = tmp_path / "cv.txt"
    source.write_text(
        "Potential/V, Current/A\n"
        "0.0,1e-5\n0.1,4e-5\n0.2,1e-4\n0.2,1.2e-4\n0.2,1.4e-4\n"
        "0.1,8e-5\n0.0,2e-5\n"
    )

    with pytest.raises(ValueError, match="ambiguous turning plateau"):
        audit_chi_cv(source)


def test_audit_fits_distinct_slopes_for_each_scan_branch(tmp_path):
    from oer_aem.cv_tafel_audit import audit_chi_cv

    source = tmp_path / "cv.txt"
    forward = [
        (index / 100, 3.1e-5 * 10 ** ((index / 100) / 0.1))
        for index in range(21)
    ]
    reverse = [
        (index / 100, 4.0e-5 * 10 ** ((index / 100) / 0.2))
        for index in reversed(range(21))
    ]
    source.write_text(
        "Potential/V, Current/A\n"
        + "\n".join(f"{e:.3f},{i:.12g}" for e, i in forward + reverse)
        + "\n"
    )

    report = audit_chi_cv(source, current_window_a=(3e-5, 1e-2))

    forward_slope = report["forward"]["raw_current_candidate"]["slope_mv_per_dec_raw"]
    reverse_slope = report["reverse"]["raw_current_candidate"]["slope_mv_per_dec_raw"]
    assert forward_slope == pytest.approx(100.0)
    assert reverse_slope == pytest.approx(200.0)
    assert forward_slope != reverse_slope


def test_audit_rejects_current_window_that_reenters_after_a_gap(tmp_path):
    from oer_aem.cv_tafel_audit import audit_chi_cv

    source = tmp_path / "cv.txt"
    forward = [(index / 100, 1e-4) for index in range(5)]
    forward += [(index / 100, 1e-5) for index in range(5, 8)]
    forward += [(index / 100, 2e-4) for index in range(8, 13)]
    reverse = list(reversed(forward))
    source.write_text(
        "Potential/V, Current/A\n"
        + "\n".join(f"{e:.3f},{i:.12g}" for e, i in forward + reverse)
        + "\n"
    )

    report = audit_chi_cv(source)

    candidate = report["forward"]["raw_current_candidate"]
    assert candidate["available"] is False
    assert candidate["reason"] == "non_contiguous_current_window"
    assert candidate["n_contiguous_segments"] == 2


def test_audit_rejects_candidate_spanning_less_than_one_current_decade(tmp_path):
    from oer_aem.cv_tafel_audit import audit_chi_cv

    source = tmp_path / "cv.txt"
    forward = [(index / 100, 1e-4) for index in range(12)]
    reverse = list(reversed(forward))
    source.write_text(
        "Potential/V, Current/A\n"
        + "\n".join(f"{e:.3f},{i:.12g}" for e, i in forward + reverse)
        + "\n"
    )

    report = audit_chi_cv(source)

    candidate = report["forward"]["raw_current_candidate"]
    assert candidate["available"] is False
    assert candidate["reason"] == "less_than_one_current_decade"
    assert candidate["current_decade_span"] == pytest.approx(0.0)


def test_audit_rejects_nonmonotonic_current_in_an_otherwise_complete_window(tmp_path):
    from oer_aem.cv_tafel_audit import audit_chi_cv

    source = tmp_path / "cv.txt"
    forward = [
        (index / 100, 3e-5 if index % 2 == 0 else 3e-4)
        for index in range(12)
    ]
    source.write_text(
        "Potential/V, Current/A\n"
        + "\n".join(f"{e:.3f},{i:.12g}" for e, i in forward + list(reversed(forward)))
        + "\n"
    )

    report = audit_chi_cv(source)

    candidate = report["forward"]["raw_current_candidate"]
    assert candidate["available"] is False
    assert candidate["reason"] == "non_monotonic_current_vs_potential"


def test_audit_rejects_monotonic_but_poor_linear_tafel_fit(tmp_path):
    from oer_aem.cv_tafel_audit import audit_chi_cv

    source = tmp_path / "cv.txt"
    forward = [
        (index / 100, 3e-5 * 10 ** ((index / 11) ** 2))
        for index in range(12)
    ]
    source.write_text(
        "Potential/V, Current/A\n"
        + "\n".join(f"{e:.3f},{i:.12g}" for e, i in forward + list(reversed(forward)))
        + "\n"
    )

    report = audit_chi_cv(source)

    candidate = report["forward"]["raw_current_candidate"]
    assert candidate["available"] is False
    assert candidate["reason"] == "r_squared_below_threshold"
    assert candidate["r_squared"] < candidate["minimum_r_squared"]


def test_audit_rejects_finite_input_that_overflows_fit_quality_metrics(tmp_path):
    from oer_aem.cv_tafel_audit import audit_chi_cv

    source = tmp_path / "cv.txt"
    forward = [
        (index * 1e200, 3e-5 * 10 ** (index / 11))
        for index in range(12)
    ]
    source.write_text(
        "Potential/V, Current/A\n"
        + "\n".join(f"{e:.12g},{i:.12g}" for e, i in forward + list(reversed(forward)))
        + "\n"
    )

    report = audit_chi_cv(source)

    candidate = report["forward"]["raw_current_candidate"]
    assert candidate["available"] is False
    assert candidate["reason"] == "nonfinite_fit_metrics"
    assert "slope_mv_per_dec_raw" not in candidate
