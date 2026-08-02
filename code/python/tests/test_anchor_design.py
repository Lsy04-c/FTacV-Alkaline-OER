"""Tests for preregistered train/selection/holdout parameter anchors."""

import sys
from pathlib import Path

import numpy as np
import pytest


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from oer_aem.anchor_design import (
    generate_parameter_anchors,
    inactive_direction_probe_points,
    unit_coordinates_to_parameters,
)


SCHEMA = {
    "parameters": {
        "rate": {"transform": "log10", "bounds": [1e-2, 1e2]},
        "energy": {"transform": "linear", "bounds": [0.0, 2.0]},
    }
}


def test_anchor_design_is_seeded_split_and_schema_transformed():
    splits = (("train", 3), ("selection", 2), ("holdout", 1))

    first = generate_parameter_anchors(
        SCHEMA,
        ["rate", "energy"],
        split_counts=splits,
        seed=17,
    )
    second = generate_parameter_anchors(
        SCHEMA,
        ["rate", "energy"],
        split_counts=splits,
        seed=17,
    )

    assert first == second
    assert [anchor.split for anchor in first] == [
        "train",
        "train",
        "train",
        "selection",
        "selection",
        "holdout",
    ]
    assert len({anchor.anchor_id for anchor in first}) == 6
    for anchor in first:
        unit = np.asarray(anchor.unit_coordinates)
        assert np.all((unit >= 0.0) & (unit <= 1.0))
        assert anchor.parameters["rate"] == pytest.approx(
            10.0 ** (-2.0 + 4.0 * unit[0])
        )
        assert anchor.parameters["energy"] == pytest.approx(2.0 * unit[1])


def test_anchor_design_rejects_unresolved_schema_bounds():
    schema = {
        "parameters": {
            "GammaA": {
                "transform": "log10",
                "bounds": None,
                "bounds_status": "unresolved",
            }
        }
    }

    with pytest.raises(ValueError, match="GammaA.*bounds"):
        generate_parameter_anchors(
            schema,
            ["GammaA"],
            split_counts=(("train", 1),),
            seed=17,
        )


def test_arbitrary_unit_coordinate_uses_same_schema_mapping():
    physical = unit_coordinates_to_parameters(
        SCHEMA,
        ["rate", "energy"],
        [0.5, 0.25],
    )

    assert physical == pytest.approx({"rate": 1.0, "energy": 0.5})


def test_arbitrary_unit_coordinate_rejects_out_of_box_point():
    with pytest.raises(ValueError, match="unit coordinates"):
        unit_coordinates_to_parameters(
            SCHEMA,
            ["rate", "energy"],
            [1.01, 0.5],
        )


def test_inactive_probe_points_are_symmetric_and_remain_inside_unit_box():
    probes = inactive_direction_probe_points(
        [0.01, 0.5],
        np.eye(2),
        active_dimension=0,
        maximum_step=0.05,
    )

    assert len(probes) == 2
    first = probes[0]
    assert first["step"] == pytest.approx(0.005)
    np.testing.assert_allclose(
        (np.asarray(first["plus"]) + np.asarray(first["minus"])) / 2.0,
        [0.01, 0.5],
    )
    for probe in probes:
        assert np.all(np.asarray(probe["plus"]) >= 0.0)
        assert np.all(np.asarray(probe["plus"]) <= 1.0)
        assert np.all(np.asarray(probe["minus"]) >= 0.0)
        assert np.all(np.asarray(probe["minus"]) <= 1.0)


@pytest.mark.parametrize(
    "splits",
    [(), (("train", 0),), (("train", 1), ("train", 1))],
)
def test_anchor_design_rejects_invalid_split_contract(splits):
    with pytest.raises(ValueError, match="split"):
        generate_parameter_anchors(
            SCHEMA,
            ["rate", "energy"],
            split_counts=splits,
            seed=17,
        )
