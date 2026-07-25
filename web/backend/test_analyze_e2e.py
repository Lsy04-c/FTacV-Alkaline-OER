"""End-to-end tests for experimental analysis and forward simulation."""

from pathlib import Path
import sys

import numpy as np
import pytest
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "web" / "backend"))
sys.path.insert(0, str(ROOT / "python"))

from main import app


client = TestClient(app)
DATA_FILE = ROOT / "data" / "raw" / "ftacv4-ref-1hz.txt"


def test_analyze_real_ftacv_data_returns_consistent_metadata():
    rows = np.loadtxt(DATA_FILE)

    response = client.post("/api/data/analyze", json={"rows": rows.tolist()})
    data = response.json()

    assert response.status_code == 200
    assert data["success"] is True
    assert data["meta"]["n_points"] == rows.shape[0]
    assert data["meta"]["f"] == pytest.approx(1.0, rel=0.01)
    assert data["meta"]["E_start"] == pytest.approx(0.924, abs=0.02)
    assert data["meta"]["E_end"] == pytest.approx(1.923, abs=0.02)
    assert len(data["dc"]) == len(data["tdc"])
    assert len(data["harmonics"]) == 7
    assert all(len(harmonic) == len(data["tdc"]) for harmonic in data["harmonics"])


def test_simulation_uses_analyzed_scan_bounds():
    rows = np.loadtxt(DATA_FILE)
    analyzed = client.post(
        "/api/data/analyze", json={"rows": rows.tolist()}
    ).json()
    meta = analyzed["meta"]
    payload = {
        "E_start": meta["E_start"],
        "E_end": meta["E_end"],
        "f": meta["f"],
        "dE": meta["dE"],
        "n_points": 2048,
        "points_per_cycle": 128,
    }

    response = client.post("/api/simulate", json=payload)
    data = response.json()

    assert response.status_code == 200
    assert data["success"] is True
    tdc = np.asarray(data["tdc"])
    actual = np.asarray(data["E_actual"])
    assert tdc[0] == pytest.approx(meta["E_start"], abs=0.02)
    assert tdc[-1] == pytest.approx(meta["E_end"], abs=0.02)
    assert actual.max() < meta["E_end"] + 2 * meta["dE"] + 0.5
