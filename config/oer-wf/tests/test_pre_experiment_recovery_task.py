from pathlib import Path

import yaml

from oer_wf.models import TaskSpec


COMPUTE_COMMIT = "21284b53c0221f103a9248a9b794bc2d8fdda022"


def test_pre_experiment_s1_task_freezes_runtime_contract() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "pre_experiment_a6_v2_s1_lsoda.yaml"
    )
    spec = TaskSpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

    assert spec.commit == COMPUTE_COMMIT
    assert spec.workers == 8
    assert spec.supports_resume is True
    assert spec.smoke.args == ["--smoke"]
    assert spec.env["OMP_NUM_THREADS"] == "1"
    assert spec.env["OPENBLAS_NUM_THREADS"] == "1"
    assert spec.env["MKL_NUM_THREADS"] == "1"
    assert spec.env["NUMEXPR_NUM_THREADS"] == "1"
    assert spec.args == [
        "--pre-experiment-spec",
        "config/recovery/pre-experiment-a6-v2.json",
        "--portfolio-stage",
        "S1",
    ]
    assert spec.validators[-1] == "pre_experiment_recovery_gate"
    assert "target_manifest.json" in spec.expected_files
    assert "results.jsonl" in spec.resume_required_files
