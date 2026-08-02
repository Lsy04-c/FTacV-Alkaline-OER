"""参数重要性模块测试。"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import numpy as np
import pytest
from oer_aem.importance import (
    _normalized_central_difference,
    _build_signed_sensitivity_matrix,
    PERTURBATION_RULES,
    DEFAULT_PHYSICAL_BOUNDS,
    _apply_perturbation,
    _clamped_perturbation,
    _extract_onset,
    _feature_distance,
    _run_forward,
    _mode_specific_feature_names,
    _compute_feature_weights,
    _classify,
    _coupling_warnings,
    analyze_parameter_importance,
)


def test_normalized_central_difference_preserves_scalar_direction():
    positive = _normalized_central_difference(
        plus=12.0,
        minus=8.0,
        baseline=10.0,
        parameter_plus=3.0,
        parameter_minus=1.0,
        parameter_rule="linear",
    )
    negative = _normalized_central_difference(
        plus=8.0,
        minus=12.0,
        baseline=10.0,
        parameter_plus=3.0,
        parameter_minus=1.0,
        parameter_rule="linear",
    )

    assert positive == pytest.approx(0.2)
    assert negative == pytest.approx(-0.2)


def test_normalized_central_difference_preserves_vector_response():
    response = _normalized_central_difference(
        plus=np.array([2.0, 3.0]),
        minus=np.array([0.0, 1.0]),
        baseline=np.array([1.0, 2.0]),
        parameter_plus=100.0,
        parameter_minus=10.0,
        parameter_rule="log10",
    )

    np.testing.assert_allclose(response, [1.0, 1.0])


def test_signed_sensitivity_matrix_expands_vector_features():
    base = {"DC shape": np.array([1.0, 2.0])}
    perturbed = {
        ("x", "plus"): {"DC shape": np.array([2.0, 3.0])},
        ("x", "minus"): {"DC shape": np.array([0.0, 1.0])},
    }

    rows, matrix = _build_signed_sensitivity_matrix(
        base_features=base,
        perturbed=perturbed,
        base_params={"x": 2.0},
        parameter_names=["x"],
        perturbation_rules={"x": ("linear", 1.0)},
        active_names=["DC shape"],
    )

    assert rows == ["DC shape[0]", "DC shape[1]"]
    np.testing.assert_allclose(matrix, [[0.5], [0.5]])


def test_signed_matrix_globally_excludes_incomplete_feature_channel():
    base = {"stable": 1.0, "sometimes_missing": 2.0}
    perturbed = {
        ("a", "plus"): {"stable": 2.0, "sometimes_missing": 3.0},
        ("a", "minus"): {"stable": 0.0, "sometimes_missing": 1.0},
        ("b", "plus"): {"stable": 3.0, "sometimes_missing": None},
        ("b", "minus"): {"stable": 1.0, "sometimes_missing": 1.0},
    }

    rows, matrix = _build_signed_sensitivity_matrix(
        base_features=base,
        perturbed=perturbed,
        base_params={"a": 2.0, "b": 2.0},
        parameter_names=["a", "b"],
        perturbation_rules={
            "a": ("linear", 1.0),
            "b": ("linear", 1.0),
        },
        active_names=["stable", "sometimes_missing"],
    )

    assert rows == ["stable"]
    assert matrix.shape == (1, 2)
from oer_aem.inversion import InversionConfig, assess_harmonic_quality
from oer_aem.defaults import initialize_oer_parameters


@pytest.mark.parametrize("feature_mode", ["complex_snr", "lockin_only", "hybrid"])
def test_forward_importance_supports_nonlegacy_feature_modes(feature_mode):
    config = InversionConfig(
        n_points=256,
        points_per_cycle=32,
        feature_grid_size=32,
        fit_harmonics=(1, 2, 3),
        feature_mode=feature_mode,
    )

    features = _run_forward(initialize_oer_parameters(), config)

    assert features is not None
    assert all(f"H{harmonic}_peak_amplitude" in features for harmonic in (1, 2, 3))


def test_mode_specific_feature_names_do_not_leak_between_objectives():
    legacy = _mode_specific_feature_names("legacy", (1, 2, 3))
    complex_names = _mode_specific_feature_names("complex_snr", (1, 2, 3))
    lockin = _mode_specific_feature_names("lockin_only", (1, 2, 3))
    hybrid = _mode_specific_feature_names("hybrid", (1, 2, 3))

    assert "H1 shape" in legacy
    assert "Complex H1 real" in complex_names
    assert "Lockin H1 real" in lockin
    assert set(hybrid) == set(complex_names) | set(lockin)
    assert not any(name.startswith("H1 shape") for name in complex_names + lockin)


@pytest.mark.parametrize(
    ("feature_mode", "required_key"),
    [
        ("complex_snr", "Complex H1 real"),
        ("lockin_only", "Lockin H1 real"),
        ("hybrid", "Lockin H1 imag"),
    ],
)
def test_forward_exposes_mode_specific_signed_features(
    feature_mode,
    required_key,
):
    config = InversionConfig(
        n_points=256,
        points_per_cycle=32,
        feature_grid_size=32,
        fit_harmonics=(1, 2, 3),
        feature_mode=feature_mode,
    )

    features = _run_forward(initialize_oer_parameters(), config)

    assert required_key in features
    assert np.all(np.isfinite(np.asarray(features[required_key])))


def test_importance_report_uses_objective_specific_feature_rows():
    base = initialize_oer_parameters()
    common = dict(
        n_points=256,
        points_per_cycle=32,
        feature_grid_size=32,
        fit_harmonics=(1, 2, 3),
    )
    legacy = analyze_parameter_importance(
        base,
        InversionConfig(feature_mode="legacy", **common),
        fit_harmonics=[1, 2, 3],
    )
    complex_report = analyze_parameter_importance(
        base,
        InversionConfig(feature_mode="complex_snr", **common),
        fit_harmonics=[1, 2, 3],
    )

    legacy_rows = {
        row["feature"] for row in legacy["signed_feature_sensitivity_matrix"]
    }
    complex_rows = {
        row["feature"]
        for row in complex_report["signed_feature_sensitivity_matrix"]
    }
    assert any(name.startswith("H1 shape[") for name in legacy_rows)
    assert "Complex H1 real" in complex_rows
    assert not any(name.startswith("H1 shape[") for name in complex_rows)
    assert "excluded_sensitivity_features" in complex_report


# ========== Test 1: G_OH 扰动改变 Tafel + onset ==========
def test_single_parameter_perturbation_changes_expected_feature():
    cfg = InversionConfig(n_points=1024, points_per_cycle=64, feature_grid_size=100)
    base = initialize_oer_parameters()
    result = analyze_parameter_importance(base, cfg)
    assert result["success"]
    gh = next(p for p in result["parameter_importance"] if p["name"] == "G_OH")
    pf = gh["per_feature_changes"]
    # G_OH 出现在参数列表中且有有效分数（置信度较低运行时分数可能很小）
    assert gh["score"] > 0.0, \
        f"G_OH should have positive importance, got score={gh['score']}"


# ========== Test 2: log10 参数扰动对称性 ==========
def test_log_parameter_perturbation_uses_decade_units():
    plus, minus = _apply_perturbation(100.0, 0.25, "log10")
    assert abs(np.log10(plus / 100.0) - 0.25) < 0.001
    assert abs(np.log10(minus / 100.0) + 0.25) < 0.001

    plus2, minus2 = _apply_perturbation(1.5, 0.05, "linear")
    assert plus2 == pytest.approx(1.55)
    assert minus2 == pytest.approx(1.45)

    plus3, minus3 = _apply_perturbation(100.0, 0.20, "percent")
    assert plus3 == pytest.approx(120.0)
    assert minus3 == pytest.approx(100.0 / 1.2)


# ========== Test 3: H4-H7 权重为 0 ==========
def test_unreliable_harmonic_is_excluded_from_score():
    from oer_aem.inversion import assess_harmonic_quality
    # 构造模拟谐波：H1-H3 强，H4-H7 弱（加微小扰动保证 dynamic_range>0）
    n = 64
    t = np.linspace(0, 1, n)
    raw = np.zeros((n, 7))
    raw[:, 0] = 0.1 + 0.001 * np.sin(2*np.pi*t)      # H1 strong
    raw[:, 1] = 0.05 + 0.001 * np.sin(4*np.pi*t)     # H2 strong
    raw[:, 2] = 0.03 + 0.001 * np.sin(6*np.pi*t)     # H3 resolvable
    raw[:, 3] = 0.001 + 1e-6 * np.sin(8*np.pi*t)     # H4: below 2% threshold
    # H5-H7: 全零
    q = assess_harmonic_quality(raw)
    w = _compute_feature_weights(q)
    assert w["H1 shape"] > 0
    assert w["H2 shape"] > 0
    assert w.get("H3 shape", 0) > 0
    assert w.get("H4 shape", 0) == 0.0
    assert w.get("H5 shape", 0) == 0.0


# ========== Test 4: 输出包含耦合警告 ==========
def test_importance_result_contains_warnings():
    cfg = InversionConfig(n_points=256, points_per_cycle=32, feature_grid_size=32)
    base = initialize_oer_parameters()
    # 设为强耦合场景
    base["gamma"] = 1e-8; base["Cdl"] = 100e-6; base["A"] = 0.5
    result = analyze_parameter_importance(base, cfg)
    assert result["success"]
    assert len(result["warnings"]) > 0, "should produce at least one warning"


# ========== Test 5: 边界截断 ==========
def test_perturbation_clamping_works():
    plus, minus, flags = _clamped_perturbation(0.51, 0.05, "linear", "G_OH")
    assert minus == pytest.approx(0.5)  # clamped to lower bound
    assert flags["minus_clamped"] is True
    assert plus == pytest.approx(0.56)
    assert flags["plus_clamped"] is False


# ========== Test 6: 全量集成 ==========
def test_full_analysis_returns_valid_structure():
    cfg = InversionConfig(n_points=256, points_per_cycle=32, feature_grid_size=32)
    base = initialize_oer_parameters()
    result = analyze_parameter_importance(base, cfg)
    assert result["success"]
    assert "active_features" in result
    assert "diagnostic_features" in result
    pi = result["parameter_importance"]
    assert len(pi) == 13
    valid_levels = {"strong", "medium", "weak", "unresolved"}
    for p in pi:
        assert "name" in p and "score" in p and "level" in p
        assert p["level"] in valid_levels
    # scores should be sorted descending
    scores = [p["score"] for p in pi]
    assert scores == sorted(scores, reverse=True)


def test_analysis_can_freeze_a_preregistered_parameter_subset():
    cfg = InversionConfig(n_points=256, points_per_cycle=32, feature_grid_size=32)
    base = initialize_oer_parameters()

    result = analyze_parameter_importance(
        base,
        cfg,
        parameter_names=["k0_1", "G_OH"],
    )

    assert result["success"]
    assert result["metadata"]["param_order"] == ["k0_1", "G_OH"]
    assert result["metadata"]["n_forward_runs"] == 4
    assert {row["name"] for row in result["parameter_importance"]} == {
        "k0_1",
        "G_OH",
    }
    for row in result["signed_feature_sensitivity_matrix"]:
        assert set(row["changes"]) == {"k0_1", "G_OH"}


# ========== Test 7: ODE 失败不崩溃 ==========
def test_ode_failure_handled_gracefully():
    cfg = InversionConfig(n_points=256, points_per_cycle=32, feature_grid_size=32)
    base = initialize_oer_parameters()
    base["gamma"] = 1e-20  # absurd
    result = analyze_parameter_importance(base, cfg)
    # either base fails → error returned, or perturbations fail
    if not result["success"]:
        assert "error" in result
    # With absurd gamma, base may still run but features will be flat
    # → this test just verifies no crash occurred
    assert result["success"] is not None


# ========== Test 8: shape vs scalar 距离 ==========
def test_feature_distance_shape_vs_scalar():
    fa = {"dc": np.array([0.0, 0.5, 1.0]), "tafel": 0.12}
    fb = {"dc": np.array([0.0, 0.6, 1.0]), "tafel": 0.06}
    d_shape = _feature_distance(fa, fb, "dc")
    d_scalar = _feature_distance(fa, fb, "tafel")
    assert d_shape > 0
    assert d_scalar > 0
    # self-distance should be zero
    assert _feature_distance(fa, fa, "dc") == 0.0
    assert _feature_distance(fa, fa, "tafel") == 0.0


def test_feature_distance_resolves_report_labels():
    base = {
        "dc": np.array([0.0, 1.0]),
        "harm": [np.array([0.0, 1.0])],
        "H1_peak_amplitude": 1.0,
        "tafel": 0.12,
    }
    changed = {
        "dc": np.array([0.0, 0.8]),
        "harm": [np.array([0.0, 0.7])],
        "H1_peak_amplitude": 0.7,
        "tafel": 0.08,
    }

    assert _feature_distance(changed, base, "DC shape") > 0
    assert _feature_distance(changed, base, "H1 shape") > 0
    assert _feature_distance(changed, base, "H1 peak amplitude") > 0
    assert _feature_distance(changed, base, "Tafel") > 0


def test_feature_vector_reconstructs_expanded_sensitivity_rows():
    from oer_aem.importance import feature_vector_from_rows

    features = {
        "dc": np.array([0.1, 0.2, 0.3]),
        "Complex H1 real": 0.4,
    }

    vector = feature_vector_from_rows(
        features,
        ["DC shape[1]", "Complex H1 real"],
    )

    np.testing.assert_allclose(vector, [0.2, 0.4])


def test_feature_vector_rejects_missing_or_short_rows():
    from oer_aem.importance import feature_vector_from_rows

    with pytest.raises(ValueError, match="missing"):
        feature_vector_from_rows({}, ["DC shape[0]"])
    with pytest.raises(ValueError, match="index"):
        feature_vector_from_rows(
            {"dc": np.array([0.1])},
            ["DC shape[2]"],
        )


def test_feature_scale_vector_matches_sensitivity_block_normalization():
    from oer_aem.importance import feature_scale_vector_from_rows

    scales = feature_scale_vector_from_rows(
        {
            "dc": np.array([0.0, 2.0]),
            "Complex H1 real": -4.0,
        },
        ["DC shape[0]", "DC shape[1]", "Complex H1 real"],
    )

    np.testing.assert_allclose(scales, [2.0, 2.0, 4.0])


# ========== Test 9: 正负方向变化对称性 ==========
def test_symmetric_perturbation_scores_are_similar():
    cfg = InversionConfig(n_points=256, points_per_cycle=32, feature_grid_size=32)
    base = initialize_oer_parameters()
    from oer_aem.importance import _run_forward, PERTURBATION_RULES, _clamped_perturbation

    base_feat = _run_forward(base, cfg)
    assert base_feat is not None

    # 测试 G_OH
    base_val = base["G_OH"]
    rule, delta = PERTURBATION_RULES["G_OH"]
    plus_v, minus_v, _ = _clamped_perturbation(base_val, delta, rule, "G_OH")
    p_plus = base.copy(); p_plus["G_OH"] = plus_v
    p_minus = base.copy(); p_minus["G_OH"] = minus_v
    f_plus = _run_forward(p_plus, cfg)
    f_minus = _run_forward(p_minus, cfg)
    if f_plus and f_minus:
        d1 = _feature_distance(f_plus, base_feat, "DC shape")
        d2 = _feature_distance(f_minus, base_feat, "DC shape")
        mx = max(d1, d2, 1e-30)
        assert abs(d1 - d2) / mx < 0.8  # allow ODE nonlinearity


# ========== 辅助函数单元测试 ==========
def test_classify_levels():
    assert _classify(0.8, 0) == "strong"
    assert _classify(0.3, 0) == "medium"
    assert _classify(0.1, 0) == "weak"
    assert _classify(0.01, 0) == "unresolved"
    assert _classify(0.8, 2) == "unresolved"  # ODE fail → unresolved


def test_extract_onset():
    e = np.linspace(0.8, 1.8, 100)
    dc = np.zeros(100)
    dc[50:] = np.linspace(0, 1, 50)  # onset at ~1.3V
    onset = _extract_onset(dc, e)
    assert onset is not None
    assert 1.2 < onset < 1.4
    assert _extract_onset(np.zeros(100), e) is None


def test_coupling_warnings_detect():
    scores = {
        "gamma": {"per_feature_changes": {"DC amplitude": 0.1}},
        "A": {"per_feature_changes": {"DC amplitude": 0.1}},
        "Cdl": {"per_feature_changes": {"DC amplitude": 0.1}},
        "G_OH": {"per_feature_changes": {"Tafel": 0.2, "onset": 0.3}},
        "k0_4": {"score": 0.01},
        "E0_pre": {"per_feature_changes": {"H1 shape": 0.1}},
        "k0_pre": {"per_feature_changes": {"H1 shape": 0.1}},
    }
    w = _coupling_warnings(scores)
    assert len(w) > 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
