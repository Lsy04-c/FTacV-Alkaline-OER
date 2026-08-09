from pathlib import Path

import numpy as np
import pytest

from oer_aem import cpp_bridge


def _params(n_points: int = 32) -> dict:
    params = {
        "E_start": 0.9, "E_end": 1.2, "f": 1.0, "dE": 0.05,
        "Ru": 25.0, "Cdl": 2e-5, "A": 1.0, "gamma": 10.0 ** -8.5,
        "k0_1": 100.0, "k0_2": 100.0, "k0_3": 20.0,
        "k0_4": 100.0, "k0_pre": 100.0, "G_OH": 1.1,
        "G_O": 2.7, "scaling_OOH_OH": 3.2, "a": 0.5,
        "E01": 1.4, "E02": 1.5, "E03": 1.6, "E04": 1.7,
        "E0_pre": 1.4, "RTF": 96485.0 / (8.314 * 298.15),
        "invRC": 1.0 / (25.0 * 2e-5), "gammaF_Cdl": (10.0 ** -8.5) * 96485.0 / 2e-5,
        "total_time": 1.0, "v": 0.3, "omega": 2.0 * np.pi,
        "beta_recon": 0.0, "E_recon": 1.55, "w_recon": 0.05,
        "F": 96485.0, "n_points": n_points,
    }
    return params


def test_cpp_library_path_uses_classified_build_directory():
    path = Path(cpp_bridge.library_path())
    assert path.parent.as_posix().endswith("code/cpp/build")


def test_cpp_batch_preserves_status_and_matches_single_case():
    if not cpp_bridge.is_available():
        pytest.skip("compiled CN library unavailable")
    params = _params()
    currents, statuses = cpp_bridge.solve_cn_batch([params, params])
    assert currents.shape == (2, 32)
    assert statuses.tolist() == [0, 0]
    np.testing.assert_allclose(currents[0], cpp_bridge.solve_cn(params), rtol=0.0, atol=0.0)
    np.testing.assert_allclose(currents[0], currents[1], rtol=0.0, atol=0.0)


def test_cpp_batch_rejects_mixed_resolution():
    if not cpp_bridge.is_available():
        pytest.skip("compiled CN library unavailable")
    with pytest.raises(ValueError, match="same n_points"):
        cpp_bridge.solve_cn_batch([_params(32), _params(64)])


def test_cpp_single_case_status_is_preserved():
    if not cpp_bridge.is_available():
        pytest.skip("compiled CN library unavailable")
    current, status = cpp_bridge.solve_cn_with_status(_params())
    assert status == 0
    assert current is not None

    invalid = _params()
    invalid["Ru"] = 0.0
    current, status = cpp_bridge.solve_cn_with_status(invalid)
    assert current is None
    assert status == -1
