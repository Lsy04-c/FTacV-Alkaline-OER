# Gate A2 Physics Invariants Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the five-step M0 kinetics into explicit rates and
stoichiometry, then formally prove coverage, current, thermodynamic,
steady-state, parameter-domain and M0 fallback invariants.

**Architecture:** Freeze the current legal-state RHS behavior before changing
physics code. Introduce pure rate and current-component interfaces while
retaining the public solver API. Audit a fixed 12-case LSODA library and verify
the compact archive with an independent validator.

**Tech Stack:** Python 3.13, NumPy, SciPy LSODA/Radau, JSON/JSONL, pytest.

---

## Fixed decisions

- Baseline physics source is commit `727ed64`; its `physics.py` blob hash must
  equal the pre-refactor working copy.
- Reaction mechanism, E0 construction and solver tolerances do not change.
- Stoichiometric order is
  `pre,1,2,3,4` and `star,ox,OH,O,OOH`.
- `Ru=0` is rejected; the supported numerical domain begins at `0.1 ohm`.
- Total-current monotonicity with `k0` is not a Gate.
- Boundary projection must trigger zero times in the formal legal-state library.
- A1 remains `FAIL_METADATA`; A2 cannot authorize real-data inversion.

## File map

| File | Responsibility |
|---|---|
| `code/python/src/oer_aem/physics.py` | Parameter validation, rates, stoichiometry, current components and strict steady state |
| `code/python/src/oer_aem/defaults.py` | Remove invalid zero from legacy `Ru_range` |
| `code/python/tests/test_physics.py` | Unit and regression tests |
| `code/python/scripts/freeze_physics_baseline.py` | One-time legal-state baseline generator |
| `results/formal/physics_invariants/gate-a2-baseline-727ed64/physics_baseline.json` | Pre-refactor behavior |
| `code/python/scripts/audit_physics_invariants.py` | Fixed 12-case formal runner |
| `code/python/tests/test_physics_invariant_audit.py` | Runner and failure tests |
| `code/python/scripts/validate_gate_a2_physics.py` | Independent archive validator |
| `code/python/tests/test_gate_a2_physics_validator.py` | Tamper and classification tests |
| `results/formal/physics_invariants/gate-a2-<commit>/` | Formal compact evidence |

## Task 1: Freeze the pre-refactor legal-state baseline

**Files:**

- Create: `code/python/scripts/freeze_physics_baseline.py`
- Create:
  `results/formal/physics_invariants/gate-a2-baseline-727ed64/physics_baseline.json`
- Create: `code/python/tests/test_physics_baseline.py`

- [ ] **Step 1: Verify the source blob has not changed**

Run:

```bash
git rev-parse 727ed64:code/python/src/oer_aem/physics.py
git rev-parse HEAD:code/python/src/oer_aem/physics.py
```

Expected: identical Git blob IDs. Stop if they differ.

- [ ] **Step 2: Write a failing baseline-integrity test**

Require:

```python
assert baseline["schema_version"] == 1
assert baseline["source_commit"] == (
    "727ed64"
)
assert len(baseline["rhs_records"]) == 72
assert all(len(row["dydt"]) == 6 for row in baseline["rhs_records"])
assert all(np.isfinite(row["dydt"]).all() for row in records)
```

Also recompute the file SHA-256 stored in
`baseline["contract"]["payload_sha256"]`.

- [ ] **Step 3: Verify RED**

```bash
.venv/bin/pytest -q code/python/tests/test_physics_baseline.py
```

Expected: baseline file does not exist.

- [ ] **Step 4: Implement the generator**

The generator must:

- assert the current `physics.py` Git blob equals the `727ed64` blob;
- create 12 deterministic normalized positive coverage vectors;
- combine each vector with six times
  `[0, 0.013, 0.071, 0.19, 0.53, 0.91]`;
- cycle the 12 parameter cases defined in the design;
- call only the existing `OERPhysics.oer_model`;
- serialize 72 records with sorted keys and no NaN;
- hash the payload before adding the contract block;
- refuse to overwrite.

Parameter cases use:

```python
[
    ("default", {}),
    ("rates-low", {all k0: 0.1 * default}),
    ("rates-high", {all k0: 10.0 * default}),
    ("ru-low", {"Ru": 0.1}),
    ("ru-high", {"Ru": 500.0}),
    ("cdl-low", {"Cdl": 5e-6}),
    ("cdl-high", {"Cdl": 80e-6}),
    ("gamma-low", {"gamma": 1e-10}),
    ("gamma-high", {"gamma": 1e-7}),
    ("alpha-low", {"a": 0.25}),
    ("alpha-high", {"a": 0.75}),
    ("thermo-edge", {
        "G_OH": 1.8,
        "G_O": 2.2,
        "scaling_OOH_OH": 3.6,
    }),
]
```

- [ ] **Step 5: Generate, test and commit**

```bash
PYTHONPATH=code/python/src .venv/bin/python \
  code/python/scripts/freeze_physics_baseline.py \
  --output results/formal/physics_invariants/gate-a2-baseline-727ed64
.venv/bin/pytest -q code/python/tests/test_physics_baseline.py
git add code/python/scripts/freeze_physics_baseline.py \
  code/python/tests/test_physics_baseline.py \
  results/formal/physics_invariants/gate-a2-baseline-727ed64
git commit -m "data(a2): freeze legal-state physics baseline"
```

## Task 2: Extract elementary rates and stoichiometry

**Files:**

- Modify: `code/python/src/oer_aem/physics.py`
- Modify: `code/python/tests/test_physics.py`
- Modify: `code/python/tests/test_physics_baseline.py`

- [ ] **Step 1: Write failing stoichiometry tests**

Require:

```python
assert STOICHIOMETRIC_MATRIX.shape == (5, 5)
assert np.sum(STOICHIOMETRIC_MATRIX, axis=0) == pytest.approx(
    np.zeros(5), abs=0.0
)
rates = elementary_rates(t, y, params)
expected = STOICHIOMETRIC_MATRIX @ rates.net
assert coverage_derivatives(rates.net) == pytest.approx(expected)
```

Add a fixed-state test showing multiplying one `k0` by 10 multiplies only its
net elementary rate by 10. Add an overpotential test showing the
forward/reverse rate-constant ratio increases.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest -q code/python/tests/test_physics.py \
  -k "stoichiometric or elementary_rate"
```

- [ ] **Step 3: Implement the pure rate kernel**

Add immutable `ElementaryRates` with:

```python
@dataclass(frozen=True)
class ElementaryRates:
    applied_potential: float
    overpotentials: np.ndarray
    forward_constants: np.ndarray
    reverse_constants: np.ndarray
    net: np.ndarray
    normalized_coverages: np.ndarray
    original_coverage_sum: float
```

Move the existing exact BV expressions into `elementary_rates`. Define:

```python
STOICHIOMETRIC_MATRIX = np.array([
    [-1, 0, 0, 0, 0],
    [ 1,-1, 0, 0, 1],
    [ 0, 1,-1, 0, 0],
    [ 0, 0, 1,-1, 0],
    [ 0, 0, 0, 1,-1],
], dtype=float)
```

`_oer_model_rhs` must use `STOICHIOMETRIC_MATRIX @ rates.net`, then retain the
existing boundary projection for this task.

- [ ] **Step 4: Verify the frozen baseline**

Add a baseline comparison test:

```python
for record in baseline["rhs_records"]:
    actual = OERPhysics.oer_model(
        record["time"], np.array(record["state"]), record["params"]
    )
    assert actual == pytest.approx(
        record["dydt"], rel=1e-12, abs=1e-12
    )
```

Run:

```bash
.venv/bin/pytest -q \
  code/python/tests/test_physics.py \
  code/python/tests/test_physics_baseline.py
```

- [ ] **Step 5: Commit**

```bash
git add code/python/src/oer_aem/physics.py \
  code/python/tests/test_physics.py \
  code/python/tests/test_physics_baseline.py
git commit -m "refactor(physics): derive coverage from stoichiometry"
```

## Task 3: Enforce the supported parameter domain

**Files:**

- Modify: `code/python/src/oer_aem/physics.py`
- Modify: `code/python/src/oer_aem/defaults.py`
- Modify: `code/python/tests/test_physics.py`

- [ ] **Step 1: Write failing validation tests**

Parameterize:

```python
[
    ("Ru", 0.0),
    ("Cdl", 0.0),
    ("A", -1.0),
    ("gamma", -1e-9),
    ("T", 0.0),
    ("k0_3", -1.0),
    ("a", -0.01),
    ("a", 1.01),
]
```

Each must raise `ValueError` before calling `solve_ivp`. Add invalid `t_span`
tests and assert:

```python
assert initialize_oer_parameters()["Ru_range"] == [0.1, 500.0]
```

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest -q code/python/tests/test_physics.py \
  -k "parameter_domain or time_grid or ru_range"
```

- [ ] **Step 3: Implement validation**

Add `validate_physics_parameters(params, require_time_grid=False)`. Call it:

- at the end of `initialize_system` for scalar fields;
- at the start of `solve_ode_system` with `require_time_grid=True`;
- before direct rate evaluation.

Allow `k0=0`; require finite `E` values and `0<=a<=1`. Require
`w_recon>0` only when `beta_recon>0`.

- [ ] **Step 4: Verify regression suite**

```bash
.venv/bin/pytest -q code/python/tests/test_physics.py \
  code/python/tests/test_inversion.py \
  code/python/tests/test_importance.py
```

- [ ] **Step 5: Commit**

```bash
git add code/python/src/oer_aem/physics.py \
  code/python/src/oer_aem/defaults.py \
  code/python/tests/test_physics.py
git commit -m "fix(physics): reject unsupported parameter domains"
```

## Task 4: Make steady-state failure explicit

**Files:**

- Modify: `code/python/src/oer_aem/physics.py`
- Modify: `code/python/tests/test_physics.py`

- [ ] **Step 1: Write failing solver-failure tests**

Monkeypatch `solve_ivp` to return `success=False`. Require
`calculate_steady_state` to raise with the solver message. Add cases for:

- non-finite returned state;
- coverage sum error above `1e-8`;
- negative coverage below `-1e-8`;
- final RHS infinity norm above `1e-8`.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest -q code/python/tests/test_physics.py \
  -k "steady_state_rejects"
```

- [ ] **Step 3: Implement strict checks**

After Radau returns:

```python
if not sol.success:
    raise RuntimeError(...)
state = sol.y[:, -1]
validate_steady_state(state, params_ss, rhs_t=ss_time)
```

Delete the catch-and-fallback branch. `use_steady_state=False` remains the only
explicit path to the all-star initial state.

- [ ] **Step 4: Verify**

```bash
.venv/bin/pytest -q code/python/tests/test_physics.py
```

- [ ] **Step 5: Commit**

```bash
git add code/python/src/oer_aem/physics.py \
  code/python/tests/test_physics.py
git commit -m "fix(physics): fail closed on invalid steady states"
```

## Task 5: Add current decomposition and full M0 fallback tests

**Files:**

- Modify: `code/python/src/oer_aem/physics.py`
- Modify: `code/python/tests/test_physics.py`

- [ ] **Step 1: Write failing current tests**

For legal fixed states require:

```python
parts = current_components(t, y, params)
scale = max(
    abs(parts.solution),
    abs(parts.capacitive),
    abs(parts.faradaic),
    1e-12,
)
assert abs(parts.closure_residual) / scale <= 1e-12
```

For `beta_recon=0`, vary `E_recon` and `w_recon` over their allowed range and
require exact equality of rates, RHS, components and short LSODA trajectories.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest -q code/python/tests/test_physics.py \
  -k "current_components or full_m0"
```

- [ ] **Step 3: Implement components**

Add immutable `CurrentComponents`:

```python
@dataclass(frozen=True)
class CurrentComponents:
    solution: float
    capacitive: float
    faradaic: float
    closure_residual: float
```

Use one `ElementaryRates` instance and the same `dphi_s` expression as RHS.
Keep `solve_ode_system` return signature unchanged.

- [ ] **Step 4: Verify baseline and related tests**

```bash
.venv/bin/pytest -q code/python/tests/test_physics.py \
  code/python/tests/test_physics_baseline.py \
  code/python/tests/test_cpp_bridge.py
```

- [ ] **Step 5: Commit**

```bash
git add code/python/src/oer_aem/physics.py \
  code/python/tests/test_physics.py
git commit -m "feat(physics): expose charge-conserving current components"
```

## Task 6: Build the formal invariant audit

**Files:**

- Create: `code/python/scripts/audit_physics_invariants.py`
- Create: `code/python/tests/test_physics_invariant_audit.py`

- [ ] **Step 1: Write failing runner tests**

Require:

- exactly 12 frozen case IDs;
- 32 cycles × 128 points/cycle;
- finite states, rates and currents;
- coverage sum/range metrics;
- current-closure metric;
- steady-state status and RHS norm;
- projection trigger count;
- baseline comparison;
- M0 fallback comparison;
- deterministic JSON/JSONL and explicit failure class.

Inject one failure at a time for coverage, current closure, baseline and
projection.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest -q \
  code/python/tests/test_physics_invariant_audit.py
```

- [ ] **Step 3: Implement the runner**

CLI:

```text
audit_physics_invariants.py
  --baseline <physics_baseline.json>
  --output <new-directory>
```

Write:

- `physics_contract.json`;
- `trajectory_metrics.jsonl`;
- `baseline_comparison.json`;
- `gate_a2_summary.json`;
- `run_manifest.json`.

Formal thresholds must match the design exactly. Raw trajectories remain
outside tracked results and are identified by SHA-256 if retained.

- [ ] **Step 4: Verify runner tests**

```bash
.venv/bin/pytest -q \
  code/python/tests/test_physics_invariant_audit.py
```

- [ ] **Step 5: Commit**

```bash
git add code/python/scripts/audit_physics_invariants.py \
  code/python/tests/test_physics_invariant_audit.py
git commit -m "feat(a2): audit physics invariants"
```

## Task 7: Add independent Gate A2 validation

**Files:**

- Create: `code/python/scripts/validate_gate_a2_physics.py`
- Create: `code/python/tests/test_gate_a2_physics_validator.py`

- [ ] **Step 1: Write failing validator tests**

Cover:

1. exact 12-case PASS archive;
2. missing/duplicate case as `FAIL_STRUCTURE`;
3. NaN as `FAIL_NUMERICAL`;
4. altered stoichiometry or units as `FAIL_PHYSICS`;
5. nonzero projection count as `FAIL_NUMERICAL`;
6. current-closure threshold boundary and just-over-boundary;
7. baseline hash mismatch as `FAIL_STRUCTURE`;
8. runner summary tamper detection.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest -q \
  code/python/tests/test_gate_a2_physics_validator.py
```

- [ ] **Step 3: Implement independent validation**

The validator must not import the audit runner. It reloads all compact
artifacts, checks hashes, exact case IDs and thresholds, independently verifies
the stoichiometric column sums and recomputes the final Gate.

Exit codes:

- 0 PASS;
- 2 `FAIL_PHYSICS`;
- 3 `FAIL_NUMERICAL`;
- 4 `FAIL_STRUCTURE`.

- [ ] **Step 4: Verify all Python tests**

```bash
.venv/bin/pytest -q \
  code/python/tests/test_gate_a2_physics_validator.py
.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q
```

- [ ] **Step 5: Commit**

```bash
git add code/python/scripts/validate_gate_a2_physics.py \
  code/python/tests/test_gate_a2_physics_validator.py
git commit -m "feat(a2): independently validate physics invariants"
```

## Task 8: Run the formal Gate and publish

**Files:**

- Create: `results/formal/physics_invariants/gate-a2-<commit>/`
- Modify: `documents/project/WORK_STATUS.md`
- Modify: `documents/project/PROJECT_SUMMARY.md`
- Modify: `documents/corrections/项目纠错.md` only for new issues

- [ ] **Step 1: Run full preflight**

```bash
.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q
.venv/bin/python code/python/scripts/audit_repository_layout.py
git diff --check
git status --short
```

Require a clean tree before formal execution.

- [ ] **Step 2: Run formal once on Mac**

```bash
commit=$(git rev-parse --short=7 HEAD)
output="results/formal/physics_invariants/gate-a2-${commit}"
PYTHONPATH=code/python/src .venv/bin/python \
  code/python/scripts/audit_physics_invariants.py \
  --baseline \
  results/formal/physics_invariants/gate-a2-baseline-727ed64/physics_baseline.json \
  --output "$output"
PYTHONPATH=code/python/src .venv/bin/python \
  code/python/scripts/validate_gate_a2_physics.py \
  --archive "$output"
```

Do not rerun with changed thresholds or case definitions.

- [ ] **Step 3: Enforce result**

- PASS: close Gate A2.
- `FAIL_STRUCTURE`: stop and repair evidence plumbing only.
- `FAIL_NUMERICAL`: stop; retain the failing case and do not project/crop it.
- `FAIL_PHYSICS`: stop; do not change mechanism in this task.

- [ ] **Step 4: Write acceptance and project state**

Record commit, baseline hash, 12 cases, all worst metrics, projection counts,
current closure, M0 fallback, archive hashes and allowed/prohibited claims.

- [ ] **Step 5: Fresh verification, commit and push**

```bash
.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q
.venv/bin/python code/python/scripts/audit_repository_layout.py
git diff --check
git add results/formal/physics_invariants/gate-a2-* \
  documents/project/WORK_STATUS.md \
  documents/project/PROJECT_SUMMARY.md \
  documents/corrections/项目纠错.md
git commit -m "docs(a2): record formal physics invariant gate"
git push origin codex/reclassify-project
```

## Plan self-review

- **Design coverage:** behavior baseline, rates, stoichiometry, parameter
  domain, strict steady state, current components, M0 fallback, formal library,
  independent validation and project state each map to a task.
- **Behavior preservation:** the baseline is frozen before physics edits and
  cannot be regenerated to hide drift.
- **Physics scope:** no reaction, E0 rule or solver tolerance changes.
- **False monotonicity:** tests stay at instantaneous elementary-rate
  definitions.
- **Boundary handling:** projection activation is evidence of failure, not a
  repair.
- **Ru domain:** zero is explicitly rejected; no small-positive value is called
  the zero-resistance limit.
- **A1 isolation:** A2 uses synthetic parameters only and cannot enable real
  inversion.
- **Placeholder scan:** no unresolved implementation placeholder remains.
