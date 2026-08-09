import math

import pytest

from oer_aem.inversion import DEFAULT_PARAM_SPECS, decode_vector
from oer_aem.recovery import SYNTHETIC_GAMMA
from oer_aem.search_policy import (
    build_scientific_parameter_selection,
    derive_cma_sigma,
    load_profile_sigma_contract,
    selection_evidence_hash,
    validate_parameter_selection_evidence,
    validate_cma_sigma,
)


def _truth_parameters():
    midpoint = decode_vector(
        [(low + high) / 2 for _, _, low, high in DEFAULT_PARAM_SPECS]
    )
    midpoint["gamma"] = SYNTHETIC_GAMMA
    return midpoint


def test_scientific_selection_adapts_complete_assignment_and_rejects_conflicts():
    params = _truth_parameters()
    selected = build_scientific_parameter_selection(
        params,
        free_names=("k0_2", "k0_3"),
        fixed_override={"A": 1.0},
    )
    assert tuple(name for name, *_ in selected.free_specs) == ("k0_2", "k0_3")
    assert dict(selected.fixed_params)["gamma"] == pytest.approx(SYNTHETIC_GAMMA)
    assert dict(selected.fixed_params)["A"] == 1.0

    with pytest.raises(ValueError, match="multiple roles"):
        build_scientific_parameter_selection(
            params,
            free_names=("k0_2", "k0_3"),
            fixed_override={"k0_2": 1.0},
        )


def test_scientific_selection_requires_explicit_diagnostic_for_gamma():
    params = _truth_parameters()
    with pytest.raises(ValueError, match="fixed role"):
        build_scientific_parameter_selection(params, free_names=("gamma",))
    selected = build_scientific_parameter_selection(
        params, free_names=("gamma",), diagnostic=True
    )
    assert selected.role_override is True


def test_scientific_selection_requires_at_least_one_search_parameter():
    with pytest.raises(ValueError, match="at least one"):
        build_scientific_parameter_selection(_truth_parameters(), free_names=())


def test_formal_selection_evidence_has_explicit_role_groups_and_stable_hash():
    selected = build_scientific_parameter_selection(
        _truth_parameters(), free_names=("k0_2", "k0_3")
    )
    evidence = selected.to_evidence()
    validated = validate_parameter_selection_evidence(evidence, formal=True)
    assert set(validated["role_groups"]) == {"free", "fixed", "diagnostic"}
    assert validated["diagnostic_parameters"] == []
    assert validated["role_override"] is False
    assert len(selection_evidence_hash(evidence)) == 64

    incomplete = dict(evidence)
    del incomplete["role_groups"]
    with pytest.raises(ValueError, match="role evidence"):
        validate_parameter_selection_evidence(incomplete, formal=True)


def test_profile_half_width_derives_conservative_sigma():
    assert derive_cma_sigma(0.20) == pytest.approx(0.10)
    assert derive_cma_sigma(0.50) == pytest.approx(0.10)
    assert derive_cma_sigma(0.001) == pytest.approx(0.005)


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), 0.0, -0.1])
def test_sigma_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        if value is None:
            derive_cma_sigma(value)
        else:
            validate_cma_sigma(value)


def test_formal_sigma_rejects_unprofiled_large_step():
    with pytest.raises(ValueError, match="profile"):
        validate_cma_sigma(0.25)
    assert validate_cma_sigma(0.25, diagnostic=True) == pytest.approx(0.25)


def test_profile_summary_contract_hashes_and_uses_narrowest_width(tmp_path):
    path = tmp_path / "profile_summary.json"
    path.write_text(
        '{"infrastructure_passed":true,"dirty":false,"source_commit":"abc",'
        '"configuration":{"solver_backend":"lsoda","smoke":false,"truth_id":"mixed_b",'
        '"feature_modes":["hybrid"],"n_points":8192,"points_per_cycle":32,'
        '"feature_grid_size":128,"fit_harmonics":[1,2,3],"grid_points":41,'
        '"noise_fraction":0.0},"profiles": ['
        '{"profile_id":"hybrid__k0_2","feature_mode":"hybrid","truth_id":"mixed_b",'
        '"parameter":"k0_2",'
        '"delta_1_width":0.20,"interval_semantics":"objective diagnostic, not confidence interval"},'
        '{"profile_id":"hybrid__k0_3","feature_mode":"hybrid","truth_id":"mixed_b",'
        '"parameter":"k0_3",'
        '"delta_1_width":0.08,"interval_semantics":"objective diagnostic, not confidence interval"}'
        ']}'
    )
    contract = load_profile_sigma_contract(path, ("k0_2", "k0_3"))
    assert contract["selected_half_width"] == pytest.approx(0.04)
    assert contract["half_width_by_parameter"]["k0_2"] == pytest.approx(0.10)
    assert len(contract["source_sha256"]) == 64
    matched = load_profile_sigma_contract(
        path, ("k0_2", "k0_3"), expected_source_commit="abc"
    )
    assert matched["source_commit"] == "abc"
    with pytest.raises(ValueError, match="source_commit"):
        load_profile_sigma_contract(
            path, ("k0_2", "k0_3"), expected_source_commit="different"
        )
    with pytest.raises(ValueError, match="configuration mismatch: n_points"):
        load_profile_sigma_contract(
            path,
            ("k0_2", "k0_3"),
            feature_mode="hybrid",
            expected_truth_id="mixed_b",
            expected_configuration={"n_points": 256},
        )
    with pytest.raises(ValueError, match="global minimum"):
        load_profile_sigma_contract(
            path,
            ("k0_2", "k0_3"),
            feature_mode="hybrid",
            expected_truth_id="mixed_b",
        )


def test_profile_summary_contract_rejects_missing_or_ambiguous_width(tmp_path):
    missing = tmp_path / "missing.json"
    missing.write_text(
        '{"infrastructure_passed":true,"dirty":false,"source_commit":"abc",'
        '"configuration":{"solver_backend":"lsoda","smoke":false,"truth_id":"mixed_b",'
        '"feature_modes":["hybrid"],"n_points":8192,"points_per_cycle":32,'
        '"feature_grid_size":128,"fit_harmonics":[1,2,3],"grid_points":41,'
        '"noise_fraction":0.0},"profiles":[{"feature_mode":"hybrid",'
        '"truth_id":"mixed_b","parameter":"k0_2","delta_1_width":0.2,'
        '"interval_semantics":"objective diagnostic, not confidence interval"}]}'
    )
    with pytest.raises(ValueError, match="missing free parameters"):
        load_profile_sigma_contract(missing, ("k0_2", "k0_3"))

    invalid = tmp_path / "invalid.json"
    invalid.write_text(
        '{"infrastructure_passed":true,"dirty":false,"source_commit":"abc",'
        '"configuration":{"solver_backend":"lsoda","smoke":false,"truth_id":"mixed_b",'
        '"feature_modes":["hybrid"],"n_points":8192,"points_per_cycle":32,'
        '"feature_grid_size":128,"fit_harmonics":[1,2,3],"grid_points":41,'
        '"noise_fraction":0.0},"profiles":[{"feature_mode":"hybrid",'
        '"truth_id":"mixed_b","parameter":"k0_2","delta_1_width":0.0,'
        '"interval_semantics":"objective diagnostic, not confidence interval"}]}'
    )
    with pytest.raises(ValueError, match="must be positive"):
        load_profile_sigma_contract(invalid, ("k0_2",))


def test_profile_summary_contract_requires_feature_mode_when_profiles_repeat(tmp_path):
    path = tmp_path / "multi_mode.json"
    path.write_text(
        '{"infrastructure_passed":true,"dirty":false,"source_commit":"abc",'
        '"configuration":{"solver_backend":"lsoda","smoke":false,"truth_id":"mixed_b",'
        '"feature_modes":["legacy","hybrid"],"n_points":8192,"points_per_cycle":32,'
        '"feature_grid_size":128,"fit_harmonics":[1,2,3],"grid_points":41,'
        '"noise_fraction":0.0},"profiles":['
        '{"feature_mode":"legacy","truth_id":"mixed_b","parameter":"k0_2","delta_1_width":0.2,'
        '"interval_semantics":"objective diagnostic, not confidence interval"},'
        '{"feature_mode":"hybrid","truth_id":"mixed_b","parameter":"k0_2","delta_1_width":0.1,'
        '"interval_semantics":"objective diagnostic, not confidence interval"}]}'
    )
    with pytest.raises(ValueError, match="duplicate profile"):
        load_profile_sigma_contract(path, ("k0_2",))
    selected = load_profile_sigma_contract(path, ("k0_2",), feature_mode="hybrid")
    assert selected["feature_mode"] == "hybrid"
    assert selected["selected_half_width"] == pytest.approx(0.05)
