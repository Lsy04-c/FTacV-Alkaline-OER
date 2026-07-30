# V4 Computational Experiment Design Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rank a small set of future FTacV acquisition protocols by robust, model-conditional parameter separability without requiring new experimental data.

**Architecture:** A pure `experiment_design` module owns block feature summaries, sensitivity metrics and deterministic ranking. A resumable runner evaluates 8 V3 parameter points across 4 existing and 5 candidate protocols with LSODA/BDF. An independent validator rebuilds all evidence and reruns the selected protocols in the frozen Legion environment.

**Tech Stack:** Python 3.11/3.13, NumPy, SciPy, existing `oer_aem` physics/features, pytest, oer-wf, systemd.

---

### Task 1: Make V3 archive verification portable and read-only

**Files:**
- Modify: `code/python/scripts/validate_v3_residual_attribution.py`
- Modify: `code/python/tests/test_v3_residual_attribution_validator.py`

- [ ] **Step 1: Add failing tests for semantic selection and read-only validation**

```python
from scripts.validate_v3_residual_attribution import compare_selection


def test_compare_selection_accepts_one_ulp_distance_difference():
    expected = {"FT2": [{
        "candidate_id": 1,
        "score": 2.0,
        "unit_params": [0.1] * 5,
        "selection_rank": 0,
        "selection_min_distance": 0.7846502642103816,
    }]}
    actual = json.loads(json.dumps(expected))
    actual["FT2"][0]["selection_min_distance"] = 0.7846502642103815
    compare_selection(actual, expected)


def test_compare_selection_rejects_changed_candidate():
    expected = selection_fixture()
    actual = copy.deepcopy(expected)
    actual["FT2"][0]["candidate_id"] = 2
    with pytest.raises(ValueError, match="candidate_id"):
        compare_selection(actual, expected)


def test_validate_archive_does_not_create_acceptance_file(tmp_path):
    result = validate_archive(
        tmp_path, tmp_path / "missing.json", tmp_path / "archive"
    )
    assert result["gate"] == "FAIL_STRUCTURE"
    assert not (tmp_path / "archive" / "acceptance.md").exists()
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:
`OER_SKIP_CPP_BUILD=1 .venv/bin/python code/python/scripts/run_tests.py code/python/tests/test_v3_residual_attribution_validator.py -q`

Expected: import failure for `compare_selection` and acceptance mutation failure.

- [ ] **Step 3: Implement semantic comparison and explicit CLI output**

```python
def compare_selection(actual, expected):
    if set(actual) != set(expected):
        raise ValueError("selection dataset mismatch")
    for dataset_id in sorted(expected):
        if len(actual[dataset_id]) != len(expected[dataset_id]):
            raise ValueError(f"selection length mismatch: {dataset_id}")
        for index, (left, right) in enumerate(
            zip(actual[dataset_id], expected[dataset_id])
        ):
            for key in ("candidate_id", "selection_rank"):
                if left[key] != right[key]:
                    raise ValueError(
                        f"selection {key} mismatch: {dataset_id}/{index}"
                    )
            if not np.allclose(
                left["unit_params"], right["unit_params"],
                rtol=0.0, atol=1e-15,
            ):
                raise ValueError(
                    f"selection unit_params mismatch: {dataset_id}/{index}"
                )
            for key in ("score", "selection_min_distance"):
                if left[key] is None or right[key] is None:
                    if left[key] is not right[key]:
                        raise ValueError(
                            f"selection {key} mismatch: {dataset_id}/{index}"
                        )
                elif not math.isclose(
                    float(left[key]), float(right[key]),
                    rel_tol=1e-15, abs_tol=1e-15,
                ):
                    raise ValueError(
                        f"selection {key} mismatch: {dataset_id}/{index}"
                    )
```

Replace canonical JSON selection equality with `compare_selection`. Move Markdown
formatting to `format_acceptance(result)`. Add CLI option
`--acceptance-output`; only `main` writes when this option is present.

- [ ] **Step 4: Run V3 focused tests and the frozen Mac verification**

Expected: focused tests pass; a detached `f82d391` worktree reaches the numerical
rerun stage instead of failing on selection. Do not change the historical V3
archive or scientific gate.

- [ ] **Step 5: Commit**

```bash
git add code/python/scripts/validate_v3_residual_attribution.py \
  code/python/tests/test_v3_residual_attribution_validator.py
git commit -m "fix(v3): make archive verification portable and read-only"
```

### Task 2: Pure V4 separability contracts

**Files:**
- Create: `code/python/src/oer_aem/experiment_design.py`
- Create: `code/python/tests/test_experiment_design.py`

- [ ] **Step 1: Write failing block-vector and metric tests**

```python
def test_block_feature_vector_has_27_rows():
    names, values, observable = block_feature_vector(feature_fixture())
    assert len(names) == len(values) == len(observable) == 27
    assert names[:3] == ["dc:low", "dc:mid", "dc:high"]


def test_matrix_metrics_reward_orthogonal_columns():
    orthogonal = np.eye(5)
    coupled = np.column_stack([np.ones(5), np.ones(5), np.eye(5)[:, :3]])
    assert matrix_metrics(orthogonal)["max_abs_correlation"] < (
        matrix_metrics(coupled)["max_abs_correlation"]
    )


def test_rank_candidate_conditions_uses_frozen_lexicographic_order():
    rows = ranking_fixture()
    ranked = rank_candidate_conditions(rows, minimum_positive=6)
    assert ranked[0]["condition_id"] == "high_q25_logdet"
```

- [ ] **Step 2: Run tests and confirm RED**

Expected: `oer_aem.experiment_design` import failure.

- [ ] **Step 3: Implement pure functions**

Implement:

```python
def segment_masks(n_grid: int) -> dict[str, np.ndarray]: ...
def block_feature_vector(features, harmonics=(1, 2, 3)): ...
def central_sensitivity(plus, minus, baseline, parameter_span): ...
def matrix_metrics(matrix, ridge=1e-8): ...
def stack_observable_matrices(matrices): ...
def aggregate_condition_gain(rows): ...
def rank_candidate_conditions(rows, minimum_positive=6): ...
def column_direction_cosines(full, half): ...
```

`block_feature_vector` returns three DC means, six global complex components and
18 lock-in segment means. Empty lock-in segments are non-observable. Metric
functions reject non-finite inputs, duplicate feature names and shape mismatch.

- [ ] **Step 4: Run focused tests**

Expected: all pure contract tests pass.

- [ ] **Step 5: Commit**

```bash
git add code/python/src/oer_aem/experiment_design.py \
  code/python/tests/test_experiment_design.py
git commit -m "feat(v4): add experiment separability contracts"
```

### Task 3: Resumable V4 runner

**Files:**
- Create: `config/experiment-design/v4-computational-design.json`
- Create: `code/python/scripts/run_v4_experiment_design.py`
- Create: `code/python/tests/test_v4_experiment_design_runner.py`

- [ ] **Step 1: Write failing plan and resume tests**

```python
def test_build_job_plan_has_792_primary_jobs(v4_inputs):
    plan = build_job_plan(v4_inputs, smoke=False)
    assert len(plan["primary_jobs"]) == 8 * 9 * 11
    assert {row["condition_role"] for row in plan["primary_jobs"]} == {
        "existing", "candidate"
    }


def test_parameter_points_are_v3_ranks_zero_and_one(v4_inputs):
    points = select_parameter_points(v4_inputs)
    assert Counter(row["selection_rank"] for row in points) == {0: 4, 1: 4}


def test_resume_rejects_changed_job_hash(tmp_path, plan):
    write_jsonl(tmp_path / "forward_results.jsonl", [{
        "job_id": plan[0]["job_id"],
        "job_input_hash": "wrong",
    }])
    with pytest.raises(ValueError, match="job hash"):
        load_completed_jobs(tmp_path, plan)
```

- [ ] **Step 2: Run tests and confirm RED**

Expected: runner import failure.

- [ ] **Step 3: Implement frozen inputs and job execution**

The JSON spec freezes V2/V3 paths and SHA-256 values, 8 parameter points, five
diagnostic parameters, four existing protocols, five candidates, perturbation
rules, 128 points/cycle, 128 feature-grid points, LSODA and 8 workers.

The runner CLI:

```text
--task-spec config/experiment-design/v4-computational-design.json
--output <directory>
--workers 8
--resume
--smoke
```

`run_one_forward` decodes the V2 parameter vector, applies the exact full or
half perturbation in encoded space, solves with `solve_ode_system_detailed`,
extracts features and writes the 27-row block vector plus solver provenance.
Primary results use baseline and full-step plus/minus jobs. After deterministic
ranking, half-step jobs run only for the two selected conditions and four rank-0
points. Every completed job is atomically ordered by frozen plan.

- [ ] **Step 4: Implement evidence aggregation**

Write:

```text
v4_task_spec.json
condition_catalog.csv
job_plan.json
forward_results.jsonl
sensitivity_matrices.jsonl
portfolio_gain.csv
linearity_check.csv
recommendation.json
run_manifest.json
```

The recommendation status is one of `RECOMMEND_TWO`,
`NO_ROBUST_RECOMMENDATION`, `LOCAL_LINEARITY_UNSTABLE` or
`FAIL_NUMERICAL`. It always carries the experimental and parameter-estimation
disclaimers.

- [ ] **Step 5: Run a smoke fixture**

Smoke uses one rank-0 point, one existing condition and one candidate condition.
Expected: 22 primary jobs, finite matrices and a non-scientific smoke status.

- [ ] **Step 6: Commit**

```bash
git add config/experiment-design/v4-computational-design.json \
  code/python/scripts/run_v4_experiment_design.py \
  code/python/tests/test_v4_experiment_design_runner.py
git commit -m "feat(v4): add resumable experiment design runner"
```

### Task 4: Independent V4 validator

**Files:**
- Create: `code/python/scripts/validate_v4_experiment_design.py`
- Create: `code/python/tests/test_v4_experiment_design_validator.py`

- [ ] **Step 1: Write failing corruption tests**

```python
def test_validator_rejects_changed_condition(valid_archive):
    valid_archive.catalog[0]["frequency_hz"] = 7.0
    result = validate_archive(ROOT, SPEC, valid_archive.path)
    assert result["gate"] == "FAIL_STRUCTURE"


def test_validator_rejects_changed_recommendation(valid_archive):
    valid_archive.recommendation["selected"][0] = "wrong"
    result = validate_archive(ROOT, SPEC, valid_archive.path)
    assert result["gate"] == "FAIL_STRUCTURE"


def test_formal_validator_requires_eight_selected_reruns(valid_archive):
    result = validate_archive(ROOT, SPEC, valid_archive.path, rerun_selected=True)
    assert len(result["rerun_evidence"]) == 8
```

- [ ] **Step 2: Run tests and confirm RED**

Expected: validator import failure.

- [ ] **Step 3: Implement independent reconstruction**

`validate_archive` independently checks input hashes, 792 primary jobs, optional
80 half-step jobs, exact job membership, finite block vectors, sensitivity
matrices, portfolio gains, ranking, linearity status and manifest hashes. Formal
rerun repeats two selected conditions for four rank-0 points and compares block
vectors at `rtol=1e-8`, `atol=1e-10` in the frozen Legion environment.

The validator returns JSON and never writes into the archive. The CLI accepts
an optional `--acceptance-output` outside the archive.

- [ ] **Step 4: Run validator tests**

Expected: valid fixtures pass and all corruption fixtures fail.

- [ ] **Step 5: Commit**

```bash
git add code/python/scripts/validate_v4_experiment_design.py \
  code/python/tests/test_v4_experiment_design_validator.py
git commit -m "feat(v4): add independent experiment design validator"
```

### Task 5: oer-wf integration

**Files:**
- Create: `config/oer-wf/oer_wf/validators/v4_experiment_design_gate.py`
- Create: `config/oer-wf/tests/test_v4_experiment_design_gate.py`
- Modify: `config/oer-wf/oer_wf/validators/__init__.py`
- Modify: `config/oer-wf/oer_wf/commands/verify.py`
- Create: `config/oer-wf/examples/v4_experiment_design_lsoda.yaml`
- Modify: `config/oer-wf/pyproject.toml`
- Modify: `config/oer-wf/oer_wf/__init__.py`

- [ ] **Step 1: Write failing bridge tests**

Test smoke without reruns, formal with exactly eight reruns, relative-path
rejection, single-thread environment variables, resume files and 8 workers.

- [ ] **Step 2: Run tests and confirm RED**

Expected: unknown V4 validator.

- [ ] **Step 3: Register V4 and bump oer-wf to 0.6.9**

The TaskSpec expects all runner files plus STATUS and snapshot. Freeze the exact
compute commit only after all local tests and smoke pass.

- [ ] **Step 4: Run all oer-wf tests**

Run:
`(cd config/oer-wf && ../../.venv/bin/python -m pytest -q)`

Expected: zero failures.

- [ ] **Step 5: Commit**

```bash
git add config/oer-wf
git commit -m "feat(oer-wf): add V4 experiment design gate"
```

### Task 6: Smoke, formal execution and project update

**Files:**
- Modify: `documents/project/PROJECT_SUMMARY.md`
- Modify: `documents/project/WORK_STATUS.md`
- Modify: `documents/corrections/项目纠错.md`
- Create after PASS: `results/formal/experiment_design/v4-<commit>/`

- [ ] **Step 1: Run complete local regression**

```bash
.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q
(cd config/oer-wf && ../../.venv/bin/python -m pytest -q)
.venv/bin/python -m pytest -q code/web/tests
git diff --check
```

- [ ] **Step 2: Run local smoke and independent validation**

Expected: 22/22 primary jobs, finite evidence and validator PASS without formal
rerun.

- [ ] **Step 3: Freeze, commit and push compute code**

Bind the V4 TaskSpec to the clean compute commit in a separate deploy commit.

- [ ] **Step 4: Deploy and run Legion workflow**

Run `wf doctor`, `wf prepare`, `wf smoke`, direct independent smoke validation,
then `wf run`. Do not create an automatic timer.

- [ ] **Step 5: Validate and archive formal output**

Require complete job counts, 8 parameter points, 9 primary protocols, finite
metrics, deterministic recommendation status, linearity check and eight
selected-protocol reruns. A failure stops documentation and publication of a
unique recommendation.

- [ ] **Step 6: Update project state and push**

Record the selected protocol pair or the frozen failure status, limitations,
runtime, commit, TaskSpec hash and evidence path. Re-run all tests, commit only
project files and push `codex/reclassify-project`.
