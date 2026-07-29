# Gate A2-R Conservative Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the non-conservative boundary projection, apply state-aware
ODE tolerances and add an explicit LSODA-to-BDF fallback with independently
validated provenance.

**Architecture:** Keep the five-step rate kernel unchanged. Add one structured
dynamic-solver result beneath the compatible tuple API, then make the A2-R
runner and validator consume its backend attempts. Preserve the failed A2
archive and execute A2-R once from a clean commit.

**Tech Stack:** Python 3.13, NumPy, SciPy LSODA/BDF/Radau, JSON/JSONL, pytest.

---

## Fixed decisions

- Delete component-wise derivative projection; never crop output coverages.
- Use dynamic `atol=[3e-11]*5+[1e-8]` and `rtol=1e-6`.
- LSODA remains primary; BDF restarts from the original initial state only
  after an explicit LSODA failure or incomplete grid.
- The 11 non-`thermo-edge` cases must not use fallback.
- BDF and Radau must independently agree for `thermo-edge`.
- Existing A2 thresholds and the failed `gate-a2-6486d69` archive do not
  change.

## File map

| File | Responsibility |
|---|---|
| `code/python/src/oer_aem/physics.py` | Conservative RHS, dynamic tolerances and structured backend policy |
| `code/python/tests/test_physics.py` | Unit, fallback and compatibility regression tests |
| `code/python/scripts/audit_physics_invariants.py` | Preserve historical A2 behavior only |
| `code/python/scripts/audit_gate_a2r.py` | Fixed A2-R runner and implicit cross-check |
| `code/python/tests/test_gate_a2r_audit.py` | Runner classification tests |
| `code/python/scripts/validate_gate_a2r.py` | Independent A2-R archive validator |
| `code/python/tests/test_gate_a2r_validator.py` | Tamper and threshold tests |
| `results/formal/physics_invariants/gate-a2r-<commit>/` | One formal A2-R archive |

## Task 1: Make the RHS strictly conservative

**Files:**

- Modify: `code/python/src/oer_aem/physics.py`
- Modify: `code/python/tests/test_physics.py`

- [ ] **Step 1: Add a failing boundary-state test**

Create a legal finite state with one zero coverage and an outward raw
derivative. Require:

```python
actual = OERPhysics.oer_model(t, state, params)
rates = elementary_rates(t, state, params)
assert actual[:5] == pytest.approx(
    STOICHIOMETRIC_MATRIX @ rates.net, rel=0.0, abs=0.0
)
assert np.sum(actual[:5]) == pytest.approx(0.0, abs=1e-12)
```

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/pytest -q code/python/tests/test_physics.py \
  -k "boundary_rhs_remains_stoichiometric"
```

Expected: the projected derivative differs from the matrix product.

- [ ] **Step 3: Delete only the projection loop**

`_oer_model_rhs` must return `np.concatenate([dtheta, [dphi_s]])` directly.
Do not change rate normalization, stoichiometry or current equations.

- [ ] **Step 4: Verify focused and baseline tests**

```bash
.venv/bin/pytest -q code/python/tests/test_physics.py \
  code/python/tests/test_physics_baseline.py
```

The frozen 72 legal-state RHS baseline must remain within `1e-12`.

- [ ] **Step 5: Commit**

```bash
git add code/python/src/oer_aem/physics.py code/python/tests/test_physics.py
git commit -m "fix(physics): preserve stoichiometric coverage derivatives"
```

## Task 2: Add state-aware tolerances and explicit fallback

**Files:**

- Modify: `code/python/src/oer_aem/physics.py`
- Modify: `code/python/tests/test_physics.py`

- [ ] **Step 1: Add failing solver-policy tests**

Require:

```python
assert np.array_equal(
    DYNAMIC_ATOL,
    np.array([3e-11, 3e-11, 3e-11, 3e-11, 3e-11, 1e-8]),
)
result = OERPhysics.solve_ode_system_detailed(params)
assert result.backend_used == "LSODA"
assert result.fallback_used is False
assert [item.backend for item in result.attempts] == ["LSODA"]
```

Monkeypatch LSODA to fail and BDF to return a complete finite grid. Require
the BDF call to receive the original `y0`, not the failed LSODA final state.
Add a second test in which both fail and require `RuntimeError`.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest -q code/python/tests/test_physics.py \
  -k "dynamic_atol or detailed_solver or fallback"
```

Expected: structured API and constants do not exist.

- [ ] **Step 3: Implement the structured result**

Add frozen records:

```python
@dataclass(frozen=True)
class SolverAttempt:
    backend: str
    success: bool
    message: str
    nfev: int
    returned_points: int

@dataclass(frozen=True)
class ODESolution:
    t: np.ndarray
    y: np.ndarray
    E_actual: np.ndarray
    i_total: np.ndarray
    backend_used: str
    fallback_used: bool
    attempts: tuple[SolverAttempt, ...]
```

Implement `solve_ode_system_detailed` with fixed backend order
`LSODA → BDF`. Pass `first_step=1e-8` only to LSODA. Both calls receive
`DYNAMIC_ATOL`; BDF receives a copy of the original initial state.

- [ ] **Step 4: Preserve the tuple API**

`solve_ode_system` calls the detailed method and returns its four arrays.
If both backends fail, retain the existing warning and NaN tuple behavior.
It must never label a BDF result as LSODA.

- [ ] **Step 5: Verify related suites**

```bash
.venv/bin/pytest -q code/python/tests/test_physics.py \
  code/python/tests/test_inversion.py \
  code/python/tests/test_importance.py
```

- [ ] **Step 6: Commit**

```bash
git add code/python/src/oer_aem/physics.py code/python/tests/test_physics.py
git commit -m "feat(physics): record explicit stiff solver fallback"
```

## Task 3: Build the A2-R runner

**Files:**

- Create: `code/python/scripts/audit_gate_a2r.py`
- Create: `code/python/tests/test_gate_a2r_audit.py`

- [ ] **Step 1: Write failing summary tests**

Require exact case IDs and the original A2 thresholds plus:

```python
assert summary["gate"] == "PASS"
assert summary["fallback_cases"] == ["thermo-edge"]
```

Mutate one item at a time: projection count, coverage range, unexpected
fallback, absent LSODA failure evidence, BDF–Radau mismatch and baseline
failure. Require `FAIL_NUMERICAL`; malformed case sets require
`FAIL_STRUCTURE`.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest -q code/python/tests/test_gate_a2r_audit.py
```

Expected: runner file does not exist.

- [ ] **Step 3: Implement the fixed runner**

Reuse the 12 case definitions and baseline comparison logic, but call
`solve_ode_system_detailed`. Record raw backend attempts. Compute the
`thermo-edge` Radau trajectory from the same initial state and calculate:

```text
coverage_max_abs_error
surface_potential_max_abs_error
current_nrmse
current_max_scaled_error
```

Write the seven artifacts listed in the design. Refuse non-empty output.

- [ ] **Step 4: Verify runner tests**

```bash
.venv/bin/pytest -q code/python/tests/test_gate_a2r_audit.py
```

- [ ] **Step 5: Commit**

```bash
git add code/python/scripts/audit_gate_a2r.py \
  code/python/tests/test_gate_a2r_audit.py
git commit -m "feat(a2r): audit conservative integration"
```

## Task 4: Add independent A2-R validation

**Files:**

- Create: `code/python/scripts/validate_gate_a2r.py`
- Create: `code/python/tests/test_gate_a2r_validator.py`

- [ ] **Step 1: Write failing tamper tests**

Cover exact PASS, missing/duplicate cases, artifact hash mismatch, altered
dynamic tolerances, nonzero projection count, unexpected fallback, missing
LSODA failure message, altered implicit cross-check, baseline mismatch and
runner-summary tampering.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest -q code/python/tests/test_gate_a2r_validator.py
```

- [ ] **Step 3: Implement independent validation**

Do not import either audit runner or `oer_aem.physics`. Reload all artifacts,
verify hashes and frozen constants, recompute every A2 and A2-R threshold and
compare the recomputed Gate to `gate_a2r_summary.json`.

Exit codes:

```text
0 PASS
2 FAIL_PHYSICS
3 FAIL_NUMERICAL
4 FAIL_STRUCTURE
```

- [ ] **Step 4: Verify all tests**

```bash
.venv/bin/pytest -q code/python/tests/test_gate_a2r_validator.py
.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q
```

- [ ] **Step 5: Commit**

```bash
git add code/python/scripts/validate_gate_a2r.py \
  code/python/tests/test_gate_a2r_validator.py
git commit -m "feat(a2r): independently validate integration gate"
```

## Task 5: Run A2-R once and publish

**Files:**

- Create: `results/formal/physics_invariants/gate-a2r-<commit>/`
- Modify: `documents/project/WORK_STATUS.md`
- Modify: `documents/project/PROJECT_SUMMARY.md`
- Modify: `documents/corrections/项目纠错.md` only for a new reusable issue

- [ ] **Step 1: Run clean preflight**

```bash
.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q
.venv/bin/python code/python/scripts/audit_repository_layout.py
git diff --check
git status --short
```

- [ ] **Step 2: Execute formal A2-R once**

```bash
commit=$(git rev-parse --short=7 HEAD)
output="results/formal/physics_invariants/gate-a2r-${commit}"
PYTHONPATH=code/python/src .venv/bin/python \
  code/python/scripts/audit_gate_a2r.py \
  --baseline results/formal/physics_invariants/gate-a2-baseline-727ed64/physics_baseline.json \
  --output "$output"
PYTHONPATH=code/python/src .venv/bin/python \
  code/python/scripts/validate_gate_a2r.py --archive "$output"
```

- [ ] **Step 3: Enforce the result**

PASS closes A2-R only. Any failure preserves the archive and stops dependent
work. Do not rerun with changed cases, tolerances or thresholds.

- [ ] **Step 4: Update acceptance and project state**

Record all worst metrics, backend attempts, fallback cases, BDF–Radau
cross-check, baseline hash, source commit and allowed/prohibited claims.

- [ ] **Step 5: Verify, commit and push**

```bash
.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q
.venv/bin/python code/python/scripts/audit_repository_layout.py
git diff --check
git add results/formal/physics_invariants/gate-a2r-* \
  documents/project/WORK_STATUS.md \
  documents/project/PROJECT_SUMMARY.md \
  documents/corrections/项目纠错.md
git commit -m "docs(a2r): record conservative integration gate"
git push origin codex/reclassify-project
```

## Plan self-review

- Every design requirement maps to a task.
- The historical A2 runner and archive remain unchanged.
- Tests precede each production change.
- Backend provenance cannot be inferred from a successful tuple alone.
- The fallback restarts from the original state.
- Formal thresholds are frozen before implementation.
- No placeholder or unresolved branch remains.
