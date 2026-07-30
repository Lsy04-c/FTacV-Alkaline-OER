# V3 Residual Attribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and formally validate a four-dataset, ensemble-based DC/H1–H3 residual attribution workflow from the frozen V2 evidence.

**Architecture:** A pure `oer_aem.residual_attribution` module owns deterministic candidate selection and residual aggregation. A resumable runner performs 48 LSODA/BDF forward jobs and writes atomic artifacts. A separate validator rebuilds selection, summaries, associations and four nearest-candidate reruns. `oer-wf` supplies the frozen Legion execution and archive contract.

**Tech Stack:** Python 3.11/3.13, NumPy, SciPy, existing `oer_aem` physics and feature pipeline, pytest, oer-wf, systemd.

---

### Task 1: Pure candidate-selection contract

**Files:**
- Create: `code/python/src/oer_aem/residual_attribution.py`
- Create: `code/python/tests/test_residual_attribution.py`

- [ ] **Step 1: Write failing deterministic-selection tests**

```python
def test_select_representative_candidates_keeps_best_and_is_deterministic():
    rows = make_success_rows(80, dimensions=5)
    first = select_representative_candidates(rows, pool_size=64, ensemble_size=12)
    second = select_representative_candidates(list(reversed(rows)), 64, 12)
    assert first == second
    assert first[0]["candidate_id"] == min(rows, key=lambda row: (row["score"], row["candidate_id"]))["candidate_id"]
    assert len({row["candidate_id"] for row in first}) == 12


def test_select_representative_candidates_rejects_small_success_pool():
    with pytest.raises(ValueError, match="at least 64 successful"):
        select_representative_candidates(make_success_rows(63, 5), 64, 12)
```

- [ ] **Step 2: Run the tests and confirm RED**

Run:
`OER_SKIP_CPP_BUILD=1 .venv/bin/python code/python/scripts/run_tests.py code/python/tests/test_residual_attribution.py -q`

Expected: import failure because `oer_aem.residual_attribution` does not exist.

- [ ] **Step 3: Implement deterministic greedy maximin**

```python
def select_representative_candidates(rows, pool_size=64, ensemble_size=12):
    successful = sorted(
        (row for row in rows if row.get("success") is True),
        key=lambda row: (float(row["score"]), int(row["candidate_id"])),
    )
    if len(successful) < pool_size:
        raise ValueError(f"need at least {pool_size} successful candidates")
    pool = successful[:pool_size]
    selected = [pool[0]]
    remaining = pool[1:]
    while len(selected) < ensemble_size:
        chosen = min(
            remaining,
            key=lambda row: (
                -min(
                    np.linalg.norm(
                        np.asarray(row["unit_params"], dtype=float)
                        - np.asarray(item["unit_params"], dtype=float)
                    )
                    for item in selected
                ),
                float(row["score"]),
                int(row["candidate_id"]),
            ),
        )
        selected.append(chosen)
        remaining.remove(chosen)
    return selected
```

- [ ] **Step 4: Run the tests and confirm GREEN**

Expected: all selection tests pass.

- [ ] **Step 5: Commit**

```bash
git add code/python/src/oer_aem/residual_attribution.py code/python/tests/test_residual_attribution.py
git commit -m "feat(v3): add representative candidate selection"
```

### Task 2: Signed residual and ensemble aggregation

**Files:**
- Modify: `code/python/src/oer_aem/residual_attribution.py`
- Modify: `code/python/tests/test_residual_attribution.py`

- [ ] **Step 1: Write failing residual tests**

```python
def test_signed_residuals_use_experiment_minus_simulation_and_wrapped_phase():
    target = feature_fixture(dc=[2.0, 4.0], amplitude=[2.0, 2.0], phase=[3.1, -3.1])
    simulated = feature_fixture(dc=[1.0, 6.0], amplitude=[1.0, 3.0], phase=[-3.1, 3.1])
    result = signed_feature_residuals(target, simulated, harmonics=(1,))
    np.testing.assert_allclose(result["dc"], [0.25, -0.5])
    assert np.all(np.abs(result["global_phase_h1"]) <= np.pi)


def test_segment_masks_are_26_76_26_for_128_points():
    masks = segment_masks(128)
    assert [int(mask.sum()) for mask in masks.values()] == [26, 76, 26]


def test_ensemble_direction_requires_nine_of_twelve_same_sign():
    assert classify_sign_consistency([1.0] * 9 + [-1.0] * 3) == "ensemble sign-consistent"
    assert classify_sign_consistency([1.0] * 8 + [-1.0] * 4) == "candidate-dependent"
```

- [ ] **Step 2: Run the tests and confirm RED**

Expected: missing residual functions.

- [ ] **Step 3: Implement the signed residual API**

Implement five public functions:

- `segment_masks(n_grid)` returns boolean `low/mid/high` masks using
  `ceil(0.2*n_grid)` and `floor(0.8*n_grid)`.
- `signed_feature_residuals(target, simulated, harmonics)` returns DC, global
  amplitude/phase and lock-in amplitude/phase arrays. It normalizes DC and
  amplitudes with the frozen experimental channel scale and computes phase as
  `np.angle(np.exp(1j * (target_phase - simulated_phase)))`.
- `summarize_candidate_residuals(residuals, masks)` returns signed mean, median,
  RMSE, median absolute error and positive fraction for every channel/segment.
- `summarize_ensemble(rows, ensemble_size)` validates exactly 12 candidates and
  returns median, quartiles, sign count, nearest value and quartile membership.
- `classify_sign_consistency(values, required)` returns
  `ensemble sign-consistent` only when at least nine nonzero values share a sign.

Every function rejects non-finite arrays and shape mismatches.

- [ ] **Step 4: Run focused and full module tests**

Expected: the new tests pass without warnings.

- [ ] **Step 5: Commit**

```bash
git add code/python/src/oer_aem/residual_attribution.py code/python/tests/test_residual_attribution.py
git commit -m "feat(v3): add signed residual aggregation"
```

### Task 3: Resumable V3 runner

**Files:**
- Create: `config/residual/v3-residual-attribution.json`
- Create: `code/python/scripts/run_v3_residual_attribution.py`
- Create: `code/python/tests/test_v3_residual_attribution_runner.py`

- [ ] **Step 1: Write failing runner contract tests**

```python
def test_build_job_plan_has_four_datasets_and_twelve_candidates(v2_fixture):
    plan = build_job_plan(v2_fixture, pool_size=64, ensemble_size=12)
    assert len(plan) == 48
    assert Counter(row["dataset_id"] for row in plan) == {
        "FT2": 12, "FT3": 12, "FT4": 12, "FT8": 12,
    }


def test_resume_rejects_changed_input_hash(tmp_path, completed_output):
    completed_output["run_manifest.json"]["v2_input_hash"] = "wrong"
    with pytest.raises(ValueError, match="V2 input hash"):
        load_resume_state(tmp_path, expected_manifest())


def test_atomic_jsonl_recovery_rejects_duplicate_job(tmp_path):
    write_jsonl(tmp_path / "residual_curves.jsonl", [job("FT2", 1), job("FT2", 1)])
    with pytest.raises(ValueError, match="duplicate job"):
        load_completed_jobs(tmp_path)
```

- [ ] **Step 2: Run tests and confirm RED**

Expected: runner module import failure.

- [ ] **Step 3: Implement runner**

The CLI must accept:

```text
--task-spec config/residual/v3-residual-attribution.json
--v2-archive results/formal/conditional_reachability/v2-fbda4cf
--output <directory>
--workers 8
--resume
--smoke
```

Implement these exact boundaries:

- `load_and_hash_v2_inputs` reads the seven frozen V2 inputs, compares every
  declared SHA-256 and enriches each base row with the matching five unit
  coordinates from `parameter_library.csv`.
- `build_job_plan` calls the pure selector per dataset and emits 48 ordered job
  dictionaries with deterministic `job_id` and input hash.
- `run_one_job` reconstructs the V2 `InversionConfig`, runs the detailed solver,
  extracts hybrid features and returns arrays plus candidate summaries.
- `load_completed_jobs` accepts only unique, finite rows whose task, input and job
  hashes match the current manifest.
- `write_atomic_json` and `write_atomic_jsonl` write sibling `.tmp` files,
  `fsync`, then replace the destination.
- `build_scalar_evidence` writes residual matrices, base Spearman associations,
  paired stress directions, five-category evidence and summary.
- `main` validates arguments, owns resume policy, uses
  `ProcessPoolExecutor(max_workers=workers)` and returns 0 only after all required
  runner artifacts are durable.

The runner writes every output in the design except `acceptance.md`, which belongs
to the independent validator, and `STATUS.json`, which belongs to the workflow
wrapper. JSONL order must match the frozen plan.

- [ ] **Step 4: Run runner tests and a 4-job smoke fixture**

Expected: all runner tests pass; smoke output contains one candidate per dataset.

- [ ] **Step 5: Commit**

```bash
git add config/residual/v3-residual-attribution.json code/python/scripts/run_v3_residual_attribution.py code/python/tests/test_v3_residual_attribution_runner.py
git commit -m "feat(v3): add resumable residual attribution runner"
```

### Task 4: Independent validator

**Files:**
- Create: `code/python/scripts/validate_v3_residual_attribution.py`
- Create: `code/python/tests/test_v3_residual_attribution_validator.py`

- [ ] **Step 1: Write failing corruption tests**

```python
def test_validator_rejects_changed_selection(valid_archive):
    valid_archive.selection["FT2"]["selected"][0]["candidate_id"] += 1
    result = validate_archive(ROOT, SPEC, valid_archive.path, rerun_nearest=False)
    assert result["gate"] == "FAIL_STRUCTURE"
    assert "selection mismatch" in result["errors"][0]


def test_validator_rejects_phase_outside_wrapped_range(valid_archive):
    valid_archive.first_curve["residuals"]["global_phase_h1"][0] = 3.2
    result = validate_archive(ROOT, SPEC, valid_archive.path, rerun_nearest=False)
    assert result["gate"] == "FAIL_STRUCTURE"


def test_validator_requires_four_rerun_rows_for_formal(valid_archive, monkeypatch):
    monkeypatch.setattr(module, "rerun_nearest_candidates", lambda *args: [{}, {}, {}])
    result = validate_archive(ROOT, SPEC, valid_archive.path, rerun_nearest=True)
    assert result["gate"] == "FAIL_STRUCTURE"
```

- [ ] **Step 2: Run tests and confirm RED**

Expected: validator import failure.

- [ ] **Step 3: Implement independent reconstruction**

Expose `validate_archive(root, spec_path, archive, rerun_nearest=False)` and
`rerun_nearest_candidates(root, spec, archive_inputs, selection)`.

The validator independently recomputes hashes, selection, 48-job membership,
residual arrays, matrix summaries, Spearman rows, stress directions and evidence
schema. Formal rerun compares four nearest-candidate curves with relative and
absolute tolerance `1e-8` under the frozen Legion single-thread environment.

- [ ] **Step 4: Run validator tests and fixture acceptance**

Expected: valid fixture PASS; each corruption fixture FAIL_STRUCTURE.

- [ ] **Step 5: Commit**

```bash
git add code/python/scripts/validate_v3_residual_attribution.py code/python/tests/test_v3_residual_attribution_validator.py
git commit -m "feat(v3): add independent residual validator"
```

### Task 5: oer-wf integration

**Files:**
- Create: `config/oer-wf/oer_wf/validators/v3_residual_attribution_gate.py`
- Create: `config/oer-wf/tests/test_v3_residual_attribution_gate.py`
- Modify: `config/oer-wf/oer_wf/validators/__init__.py`
- Modify: `config/oer-wf/oer_wf/commands/verify.py`
- Create: `config/oer-wf/examples/v3_residual_attribution_lsoda.yaml`
- Modify: `config/oer-wf/pyproject.toml`
- Modify: `config/oer-wf/oer_wf/__init__.py`

- [ ] **Step 1: Write failing bridge tests**

Test that smoke disables rerun, formal enables exactly four reruns, malformed
relative paths fail before import, and TaskSpec injects all four single-thread
variables.

- [ ] **Step 2: Run tests and confirm RED**

Expected: unknown validator or missing module.

- [ ] **Step 3: Implement bridge and TaskSpec**

Register `v3_residual_attribution_gate` in `_VALIDATOR_MAP`. The TaskSpec must
freeze the compute commit, V3 input archive, 8 workers, expected files, resume
files and validator configuration. Bump oer-wf from 0.6.7 to 0.6.8.

- [ ] **Step 4: Run all oer-wf tests**

Run:
`cd config/oer-wf && ../../.venv/bin/python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add config/oer-wf
git commit -m "feat(oer-wf): add V3 residual gate"
```

### Task 6: Smoke, freeze and formal execution

**Files:**
- Modify: `documents/project/WORK_STATUS.md`
- Modify: `documents/corrections/项目纠错.md`
- Create after PASS: `results/formal/residual_attribution/v3-<commit>/`

- [ ] **Step 1: Run local focused and full regression**

Run:

```bash
.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q
(cd config/oer-wf && ../../.venv/bin/python -m pytest -q)
.venv/bin/python -m pytest -q code/web/tests
```

Expected: zero failures; only the known Starlette warning is allowed.

- [ ] **Step 2: Run a local four-job smoke**

Expected: one successful LSODA/BDF job per dataset, valid residual shapes and
validator PASS without formal rerun.

- [ ] **Step 3: Freeze and push compute commit**

Bind `config/oer-wf/examples/v3_residual_attribution_lsoda.yaml` to the exact
clean compute commit and update its spec hash.

- [ ] **Step 4: Deploy through oer-wf**

Run `wf doctor`, `wf prepare`, `wf smoke`, `wf verify`, then `wf run`. Do not
create an automatic timer. Use 8 workers and one numerical-library thread per
worker.

- [ ] **Step 5: Validate formal output**

Require 48/48 successful jobs, four datasets, 12 candidates each, finite curves,
all independent reconstruction checks and four frozen-environment nearest
reruns. A scientific or infrastructure FAIL stops the phase without threshold
changes.

- [ ] **Step 6: Archive, document and push**

Copy only validated formal evidence into
`results/formal/residual_attribution/v3-<commit>/`. Update project summary,
progress and corrections. Re-run full verification, commit and push the project
branch.
