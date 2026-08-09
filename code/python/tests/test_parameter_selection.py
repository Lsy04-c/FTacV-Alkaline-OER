import pytest

from oer_aem.inversion import DEFAULT_PARAM_SPECS, decode_vector
from oer_aem.recovery import build_parameter_selection


def _complete(free=("k0_2", "k0_3")):
    names = {name for name, *_ in DEFAULT_PARAM_SPECS}
    mid = decode_vector([(low + high) / 2 for _, _, low, high in DEFAULT_PARAM_SPECS])
    fixed = {name: mid[name] for name in names - set(free)}
    return build_parameter_selection(free_names=free, fixed_values=fixed)


def test_selection_explicitly_partitions_all_parameters():
    selected = _complete()
    assert tuple(name for name, *_ in selected.free_specs) == ("k0_2", "k0_3")
    assert selected.roles["k0_1"] == "fixed"
    assert selected.roles["k0_2"] == "free"
    assert selected.to_evidence()["free_parameters"] == ["k0_2", "k0_3"]


@pytest.mark.parametrize("kwargs, message", [
    ({"free_names": ("k0_2",), "fixed_values": {}}, "incomplete"),
    ({"free_names": ("gamma",), "fixed_values": {}}, "fixed role"),
    ({"free_names": ("k0_2",), "fixed_values": {"k0_2": 1.0, "k0_1": 1.0}}, "multiple roles"),
])
def test_selection_rejects_incomplete_or_conflicting_assignments(kwargs, message):
    with pytest.raises(ValueError, match=message):
        build_parameter_selection(**kwargs)


def test_fixed_role_can_be_reopened_only_as_explicit_override():
    mid = decode_vector([(low + high) / 2 for _, _, low, high in DEFAULT_PARAM_SPECS])
    fixed = {name: mid[name] for name, *_ in DEFAULT_PARAM_SPECS if name != "gamma"}
    with pytest.raises(ValueError, match="fixed role"):
        build_parameter_selection(free_names=("gamma",), fixed_values=fixed)
    selected = build_parameter_selection(
        free_names=("gamma",), fixed_values=fixed,
        allow_role_override=True,
    )
    assert selected.role_override is True


def test_external_runtime_parameters_can_be_fixed_without_being_search_specs():
    selected = _complete()
    # Runtime inputs such as area and uncompensated resistance are allowed in
    # the fixed side; making them free requires passing explicit ParamSpecs.
    selected = build_parameter_selection(
        free_names=("k0_2", "k0_3"),
        fixed_values={
            **dict(selected.fixed_params),
            "A": 1.0,
            "Ru": 25.0,
        },
    )
    assert dict(selected.fixed_params)["A"] == 1.0


def test_diagnostic_assignment_requires_an_explicit_fixed_value():
    names = {name for name, *_ in DEFAULT_PARAM_SPECS}
    mid = decode_vector([(low + high) / 2 for _, _, low, high in DEFAULT_PARAM_SPECS])
    fixed = {name: mid[name] for name in names - {"k0_1", "k0_2"}}
    with pytest.raises(ValueError, match="diagnostic"):
        build_parameter_selection(
            free_names=("k0_2",),
            fixed_values=fixed,
            diagnostic_names=("k0_1",),
        )


def test_diagnostic_assignment_is_fixed_but_retained_in_role_evidence():
    names = {name for name, *_ in DEFAULT_PARAM_SPECS}
    mid = decode_vector([(low + high) / 2 for _, _, low, high in DEFAULT_PARAM_SPECS])
    selected = build_parameter_selection(
        free_names=("k0_2",),
        fixed_values={name: mid[name] for name in names - {"k0_2"}},
        diagnostic_names=("k0_1",),
    )

    assert selected.roles["k0_1"] == "diagnostic"
    assert dict(selected.fixed_params)["k0_1"] == mid["k0_1"]
    assert selected.to_evidence()["diagnostic_parameters"] == ["k0_1"]


def test_selection_rejects_nonfinite_and_out_of_bounds_fixed_values():
    names = {name for name, *_ in DEFAULT_PARAM_SPECS}
    mid = decode_vector([(low + high) / 2 for _, _, low, high in DEFAULT_PARAM_SPECS])
    fixed = {name: mid[name] for name in names - {"k0_2"}}
    with pytest.raises(ValueError, match="outside"):
        build_parameter_selection(
            free_names=("k0_2",),
            fixed_values={**fixed, "k0_1": 1e-20},
        )
    with pytest.raises(ValueError, match="finite"):
        build_parameter_selection(
            free_names=("k0_2",),
            fixed_values={**fixed, "k0_1": float("nan")},
        )
