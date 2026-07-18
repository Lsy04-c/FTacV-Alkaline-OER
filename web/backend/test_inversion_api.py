"""API smoke test for the TPE inversion endpoint."""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "web", "backend"))
sys.path.insert(0, os.path.join(ROOT, "python"))

from fastapi.testclient import TestClient

from main import app
from oer_aem.inversion import InversionConfig, make_synthetic_target


client = TestClient(app)


def test_tpe_inversion_endpoint_returns_fit_quality():
    config = InversionConfig(n_points=256, points_per_cycle=32, feature_grid_size=32)
    truth = {
        "k0_1": 100.0,
        "k0_2": 50.0,
        "k0_3": 20.0,
        "k0_4": 80.0,
        "G_OH": 1.23,
        "G_O": 2.80,
        "scaling_OOH_OH": 3.2,
        "gamma": 1e-9,
    }
    target = make_synthetic_target(truth, config=config, noise_fraction=0.0)
    payload = {
        "target": {
            "tdc": target["e_grid"].tolist(),
            "dc": target["dc"].tolist(),
            "harmonics": [h.tolist() for h in target["harm"]],
            "tafel": target["tafel"],
        },
        "config": {
            "E_start": config.E_start,
            "E_end": config.E_end,
            "f": config.f,
            "dE": config.dE,
            "n_points": config.n_points,
            "points_per_cycle": config.points_per_cycle,
            "feature_grid_size": config.feature_grid_size,
        },
        "n_trials": 1,
    }

    response = client.post("/api/inversion/tpe", json=payload)
    data = response.json()

    assert response.status_code == 200
    assert data["success"] is True
    assert "best_params" in data
    assert "fit_quality" in data
    assert data["fit_quality"]["level"] in {"excellent", "acceptable", "rough", "poor"}
