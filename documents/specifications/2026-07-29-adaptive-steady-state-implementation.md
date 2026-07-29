# V2 Adaptive Steady-State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed five-second steady-state warm-up with a traced,
bounded adaptive relaxation while preserving the frozen `1e-8` RHS gate.

**Architecture:** Add a detailed steady-state result beside the compatibility
wrapper, propagate its provenance through `ODESolution`, and record it in V2
JSONL rows. Keep the dynamic LSODA/BDF path and scientific thresholds
unchanged.

**Tech Stack:** Python 3.13, NumPy, SciPy Radau/LSODA/BDF, pytest, JSONL.

---

### Task 1: Freeze adaptive relaxation behavior

**Files:**

- Modify: `code/python/tests/test_physics.py`
- Modify: `code/python/src/oer_aem/physics.py`

- [x] **Step 1: Write failing tests**

Add tests that require:

```python
solution = OERPhysics.calculate_steady_state_detailed(params)
assert solution.elapsed_s == 5.0
assert solution.rhs_norm <= 1e-8
assert len(solution.attempts) == 1
```

For the frozen FT2 candidate 2 parameters, require:

```python
assert solution.elapsed_s == 5000.0
assert solution.rhs_norm <= 1e-8
assert [row.elapsed_s for row in solution.attempts] == [
    5.0, 50.0, 500.0, 5000.0
]
```

Monkeypatch Radau to return finite but unrelaxed states and require a failure
containing `50000` and `RHS`.

- [x] **Step 2: Verify RED**

Run:

```bash
.venv/bin/python -m pytest code/python/tests/test_physics.py \
  -k 'adaptive_steady_state or slow_v2_candidate' -q
```

Expected: missing `calculate_steady_state_detailed` or fixed-five-second
failure.

- [x] **Step 3: Implement the detailed solver**

Add `SteadyStateAttempt`, `SteadyStateSolution`, and cumulative endpoints:

```python
STEADY_STATE_ENDPOINTS = (5.0, 50.0, 500.0, 5000.0, 50000.0)
STEADY_STATE_RHS_MAX = 1e-8
```

Integrate each interval with the previous terminal state. Compute RHS after
each successful stage. Return immediately when the frozen gate passes.
Keep `calculate_steady_state` as:

```python
return OERPhysics.calculate_steady_state_detailed(params).state
```

- [x] **Step 4: Verify GREEN**

Run the new tests plus all `test_physics.py`. Expected: all pass.

### Task 2: Propagate steady-state provenance

**Files:**

- Modify: `code/python/src/oer_aem/physics.py`
- Modify: `code/python/tests/test_physics.py`
- Modify: `code/python/scripts/run_conditional_reachability.py`
- Modify: `code/python/tests/test_conditional_reachability_runner.py`

- [x] **Step 1: Write failing provenance tests**

Require `solve_ode_system_detailed` to expose:

```python
result.steady_state_elapsed_s
result.steady_state_rhs_norm
result.steady_state_attempts
```

Require V2 `evaluate_job` rows to contain the same three fields.

- [x] **Step 2: Verify RED**

Run the two named test files. Expected: missing provenance fields.

- [x] **Step 3: Add minimal propagation**

Call the detailed initializer inside `solve_ode_system_detailed`. Add optional
steady-state fields to `ODESolution`; use `None`, `None`, and `()` when
`use_steady_state=false`. Serialize the fields in every V2 result row.

- [x] **Step 4: Verify GREEN**

Run the two named test files. Expected: all pass.

### Task 3: Tighten independent archive validation

**Files:**

- Modify: `code/python/scripts/validate_conditional_reachability.py`
- Modify: `code/python/tests/test_conditional_reachability_validator.py`

- [x] **Step 1: Write failing tamper tests**

Create a successful synthetic row and require validation failure when:

- `steady_state_rhs_norm > 1e-8`;
- elapsed time is outside the frozen endpoint set;
- attempts do not end at the recorded elapsed time.

- [x] **Step 2: Verify RED**

Run the validator test file. Expected: tampered provenance is accepted.

- [x] **Step 3: Add independent checks**

Validate successful base and stress rows against
`(5, 50, 500, 5000, 50000)` and `1e-8`. Keep smoke classification null.

- [x] **Step 4: Verify GREEN**

Run validator tests. Expected: all pass.

### Task 4: Re-run the V2 smoke

**Files:**

- Create:
  `results/smoke/conditional_reachability/v2-adaptive-steady-state-smoke/`
- Modify: `documents/project/PROJECT_SUMMARY.md`
- Modify: `documents/project/WORK_STATUS.md`
- Modify: `documents/corrections/项目纠错.md`

- [x] **Step 1: Run focused and full verification**

```bash
.venv/bin/python -m pytest \
  code/python/tests/test_physics.py \
  code/python/tests/test_conditional_reachability_runner.py \
  code/python/tests/test_conditional_reachability_validator.py -q
.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q
.venv/bin/python -m pytest code/web/tests/backend -q
```

- [x] **Step 2: Run 4×8 LSODA smoke with eight workers**

```bash
.venv/bin/python code/python/scripts/run_conditional_reachability.py \
  --task-spec config/reachability/v2-conditional-reachability.json \
  --smoke --workers 8 \
  --output results/smoke/conditional_reachability/v2-adaptive-steady-state-smoke
```

- [x] **Step 3: Validate independently**

```bash
.venv/bin/python code/python/scripts/validate_conditional_reachability.py \
  --root . \
  --task-spec config/reachability/v2-conditional-reachability.json \
  --archive \
  results/smoke/conditional_reachability/v2-adaptive-steady-state-smoke
```

Require 32 unique jobs, validator `PASS`, null scientific classifications and
ODE success fraction at least 0.95.

- [x] **Step 4: Apply the decision**

If the numerical gate fails, stop and preserve evidence. If it passes, update
project documents and continue only with formal validator/workflow completion.
Do not commit or push; the user explicitly requested no submission.
