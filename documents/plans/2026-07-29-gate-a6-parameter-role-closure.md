# Gate A6 Parameter Role Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze all 13 model parameters into auditable operational roles and close the current multi-parameter recovery route as `FAIL_RECOVERY` without running new numerical calculations.

**Architecture:** A hand-authored JSON registry states the role decision and cites immutable Git evidence by path and SHA-256. A standalone standard-library validator checks the schema, evidence bytes, role-specific claim restrictions, and clean Git provenance; the same validator writes a new immutable formal archive only after the registry passes.

**Tech Stack:** Python 3.13 standard library, JSON, SHA-256, subprocess Git provenance, pytest, Markdown.

---

## Fixed decisions

- Gate status is `FAIL_RECOVERY`.
- `eligible_for_real_inversion` is `false`.
- `free_parameters` and `narrow_prior_parameters` are empty.
- No parameter is labelled structurally unidentifiable.
- `fixed` means excluded from optimization, not known accurately.
- `diagnostic_only` forbids reporting an inversion point estimate.
- The task runs no ODE, optimizer, TPE, CN, or LSODA calculation.

## File map

| File | Responsibility |
|---|---|
| `config/parameter-roles/gate-a6-parameter-roles.json` | Authoritative 13-parameter role registry and evidence index |
| `code/python/scripts/validate_gate_a6_parameter_roles.py` | Independent schema, hash, role-contract, provenance and archive writer |
| `code/python/tests/test_gate_a6_parameter_roles.py` | Mutation, tamper, non-finite and formal-output tests |
| `results/formal/identifiability/gate-a6-closure-${short_commit}/` | Frozen snapshot, validation report, manifest and acceptance |
| `documents/project/PROJECT_SUMMARY.md` | Current A6 conclusion and route |
| `documents/project/WORK_STATUS.md` | Execution record |
| `documents/corrections/项目纠错.md` | Reusable distinction between operational and epistemic roles |

## Registry contract

The top-level object must contain exactly:

```json
{
  "schema_version": 1,
  "gate": "A6",
  "status": "FAIL_RECOVERY",
  "eligible_for_real_inversion": false,
  "free_parameters": [],
  "narrow_prior_parameters": [],
  "eligible_pairs": [],
  "evidence": [],
  "parameters": []
}
```

The expected parameter set is:

```python
EXPECTED_PARAMETERS = {
    "k0_1", "k0_2", "k0_3", "k0_4", "k0_pre", "gamma",
    "G_OH", "G_O", "scaling_OOH_OH", "E0_pre", "Cdl", "Ru", "A",
}
```

Each parameter record must contain:

```json
{
  "name": "k0_1",
  "role": "diagnostic_only",
  "fixing_basis": null,
  "evidence_ids": ["single_profiles", "sobol_confirmation"],
  "fixed_value_known_accurate": false,
  "inversion_point_estimate_reportable": false,
  "structurally_unidentifiable": false,
  "allowed_use": ["profile", "sensitivity", "experimental_design"],
  "prohibited_claims": [
    "credible_inversion_point_estimate",
    "mathematically_structurally_unidentifiable"
  ],
  "reason": "Four single-parameter profiles are broad or remotely degenerate."
}
```

Allowed roles:

```python
ROLES = {"fixed", "narrow_prior", "free", "diagnostic_only"}
FIXING_BASES = {
    "external_input",
    "calibrated_input",
    "model_assumption",
    "low_sensitivity",
    "coupling_control",
}
```

The exact role mapping is:

| Parameter | Role | fixing_basis | Required evidence |
|---|---|---|---|
| `A` | fixed | external_input | four-mode sensitivity |
| `Cdl` | fixed | calibrated_input | four-mode sensitivity |
| `Ru` | fixed | calibrated_input | four-mode sensitivity |
| `E0_pre` | fixed | calibrated_input | four-mode sensitivity |
| `k0_pre` | fixed | calibrated_input | four-mode sensitivity |
| `gamma` | fixed | coupling_control | four-mode sensitivity |
| `k0_4` | fixed | low_sensitivity | four-mode sensitivity |
| `scaling_OOH_OH` | fixed | coupling_control | four-mode sensitivity |
| `k0_1` | diagnostic_only | null | single profiles |
| `k0_2` | diagnostic_only | null | Stage 2 and Sobol confirmation |
| `k0_3` | diagnostic_only | null | Stage 2 and Sobol confirmation |
| `G_OH` | diagnostic_only | null | single/2D profile record and reduced recovery |
| `G_O` | diagnostic_only | null | Stage 2 and Sobol confirmation |

The evidence index uses these exact paths and hashes:

| ID | Path | SHA-256 |
|---|---|---|
| `sensitivity_legacy` | `results/formal/identifiability/gate-a6-sensitivity-cf33eba/legacy/run_manifest.json` | `858d3bae451c4b36e0292760c720304e2e245bf4ec5418018e86f697ac77b9b7` |
| `sensitivity_complex` | `results/formal/identifiability/gate-a6-sensitivity-cf33eba/complex_snr/run_manifest.json` | `a7b6fe385480413ee65871cd76412ffff1fd58b66e55b525497fe9ae8adfd8e2` |
| `sensitivity_lockin` | `results/formal/identifiability/gate-a6-sensitivity-cf33eba/lockin_only/run_manifest.json` | `dbbe3ef21a08489cbeeb2a504ca0e3f419dd86b324322f454378d4e67cf38bcf` |
| `sensitivity_hybrid` | `results/formal/identifiability/gate-a6-sensitivity-cf33eba/hybrid/run_manifest.json` | `656518ab1a425fad55416ec6a8ff7df48cfc265bbf26bb3f3b4754e9775d3962` |
| `single_profiles` | `results/formal/identifiability/gate-a6-profile-3f9aad1/profile_analysis.md` | `58753d4670a752427a09e00128099479fd48d85c5cd760633452cf3418b0d45b` |
| `reduced_recovery` | `results/formal/identifiability/gate-a6-reduced-recovery-a7bc9e4/acceptance.md` | `c8988372a3e521e30d6775be6a7a7234f20c5e00f437d0ae2505cd390446cb3d` |
| `stage2_recovery` | `results/formal/identifiability/gate-a6-stage2-cn-732bf5d/acceptance.md` | `49835e20294ff6ea0044d7df82230eb486839b1093a1cc6fd0fd8cfd9ec2c258` |
| `optimizer_development` | `results/formal/identifiability/gate-a6-optimizer-development/acceptance.md` | `574c3bcc8bfb76e6d228572b9abe2c0cab2c2c0ab444baf32f22ff10a0f942de` |
| `sobol_confirmation` | `results/formal/identifiability/gate-a6-sobol-confirmation/acceptance.md` | `f00a5510639156cedf60a50c6caf29ff35098cb3e55e2ba0347eee99bd8ee8a0` |

## Task 1: Freeze validator behavior with failing tests

**Files:**

- Create: `code/python/tests/test_gate_a6_parameter_roles.py`
- Create: `code/python/scripts/validate_gate_a6_parameter_roles.py`

- [ ] **Step 1: Write the passing-fixture and mutation tests**

Build a complete in-memory registry fixture with all 13 parameters and temporary
evidence files. Load the validator by file path. Require:

```python
report = module.validate_registry(project_root, registry)
assert report["gate"] == "PASS"
assert report["parameter_count"] == 13
assert report["role_counts"] == {
    "fixed": 8,
    "narrow_prior": 0,
    "free": 0,
    "diagnostic_only": 5,
}
```

Parameterize these mutations and expected gates:

```python
[
    ("missing_parameter", "FAIL_STRUCTURE"),
    ("duplicate_parameter", "FAIL_STRUCTURE"),
    ("unknown_parameter", "FAIL_STRUCTURE"),
    ("invalid_role", "FAIL_ROLE_CONTRACT"),
    ("invalid_fixing_basis", "FAIL_ROLE_CONTRACT"),
    ("missing_evidence", "FAIL_STRUCTURE"),
    ("evidence_hash", "FAIL_STRUCTURE"),
    ("nonempty_free_parameters", "FAIL_ROLE_CONTRACT"),
    ("nonempty_narrow_prior", "FAIL_ROLE_CONTRACT"),
    ("fixed_claimed_accurate", "FAIL_ROLE_CONTRACT"),
    ("diagnostic_point_estimate", "FAIL_ROLE_CONTRACT"),
    ("structurally_unidentifiable", "FAIL_ROLE_CONTRACT"),
    ("eligible_pair", "FAIL_ROLE_CONTRACT"),
]
```

Write a separate raw-JSON test containing `NaN`; require
`FAIL_NUMERICAL`.

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/pytest -q code/python/tests/test_gate_a6_parameter_roles.py
```

Expected: collection or import failure because the validator does not exist.

- [ ] **Step 3: Add the validator skeleton**

Create the script with only constants, strict JSON loading and public API:

```python
EXIT_CODES = {
    "PASS": 0,
    "FAIL_ROLE_CONTRACT": 2,
    "FAIL_NUMERICAL": 3,
    "FAIL_STRUCTURE": 4,
}

def validate_registry(
    project_root: Path,
    registry: dict[str, Any],
) -> dict[str, Any]:
    ...
```

Do not import project science modules. The source must not contain
`oer_aem`, recovery runners, or optimizer adapters.

- [ ] **Step 4: Implement structural validation**

Validate exact top-level fields, exact parameter set, unique evidence IDs,
project-relative evidence paths, file existence and SHA-256. Reject absolute
paths and `..` path components.

- [ ] **Step 5: Implement role-contract validation**

Enforce:

```python
registry["status"] == "FAIL_RECOVERY"
registry["eligible_for_real_inversion"] is False
registry["free_parameters"] == []
registry["narrow_prior_parameters"] == []
registry["eligible_pairs"] == []
```

For fixed records require:

```python
role == "fixed"
fixing_basis in FIXING_BASES
fixed_value_known_accurate is False
inversion_point_estimate_reportable is False
structurally_unidentifiable is False
"fixed_value_is_known_accurate" in prohibited_claims
```

For diagnostic records require:

```python
role == "diagnostic_only"
fixing_basis is None
fixed_value_known_accurate is False
inversion_point_estimate_reportable is False
structurally_unidentifiable is False
"credible_inversion_point_estimate" in prohibited_claims
"mathematically_structurally_unidentifiable" in prohibited_claims
```

Reject `free` and `narrow_prior` records while their top-level lists remain
empty.

- [ ] **Step 6: Verify GREEN**

Run:

```bash
.venv/bin/pytest -q code/python/tests/test_gate_a6_parameter_roles.py
```

Expected: all tests pass.

## Task 2: Add formal archive writing and provenance

**Files:**

- Modify: `code/python/scripts/validate_gate_a6_parameter_roles.py`
- Modify: `code/python/tests/test_gate_a6_parameter_roles.py`

- [ ] **Step 1: Write failing archive tests**

Require `write_formal_archive()` to write exactly:

```text
parameter_roles.snapshot.json
validation_report.json
run_manifest.json
```

The test must assert:

```python
assert manifest["commit"] == "1" * 40
assert manifest["dirty"] is False
assert manifest["runs_numerical_calculation"] is False
assert set(manifest["artifact_sha256"]) == {
    "parameter_roles.snapshot.json",
    "validation_report.json",
}
```

Require refusal when the output directory is non-empty.

Also require `validate_archive(path)` to:

```python
archive_report = module.validate_archive(output)
assert archive_report["gate"] == "PASS"
```

Mutate each artifact after writing and require `FAIL_STRUCTURE`.

- [ ] **Step 2: Verify RED**

Run the archive tests and confirm failure because `write_formal_archive` is
missing.

- [ ] **Step 3: Implement atomic output**

Use `tempfile.mkstemp`, `os.fsync` and `os.replace`. Serialize with sorted keys,
indent 2 and `allow_nan=False`. Compute artifact hashes from the exact bytes
written.

- [ ] **Step 4: Add clean Git provenance**

The CLI accepts:

```text
--registry <path>
--output PATH
--archive PATH
```

Before writing, require:

```bash
git status --porcelain=v1
git rev-parse HEAD
```

Reject a dirty tree. Write Python version, command, registry path, registry
SHA-256 and `runs_numerical_calculation=false`.

`--archive` is mutually exclusive with `--registry/--output`. It recomputes
snapshot and report hashes from the archive manifest and checks that the
snapshot still satisfies the complete role contract without reading the source
registry.

- [ ] **Step 5: Verify**

Run:

```bash
.venv/bin/pytest -q code/python/tests/test_gate_a6_parameter_roles.py
.venv/bin/python -m py_compile \
  code/python/scripts/validate_gate_a6_parameter_roles.py
```

Expected: all tests and compilation pass.

## Task 3: Add the authoritative registry

**Files:**

- Create: `config/parameter-roles/gate-a6-parameter-roles.json`
- Modify: `code/python/tests/test_gate_a6_parameter_roles.py`

- [ ] **Step 1: Write the real-registry integration test**

Load the project registry and require:

```python
report = module.validate_registry(ROOT, registry)
assert report["gate"] == "PASS"
assert report["parameter_count"] == 13
assert report["role_counts"]["fixed"] == 8
assert report["role_counts"]["diagnostic_only"] == 5
```

Also assert the exact mapping table from this plan.

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/pytest -q \
  code/python/tests/test_gate_a6_parameter_roles.py \
  -k real_registry
```

Expected: fail because the registry file is absent.

- [ ] **Step 3: Write the registry**

Use the exact top-level contract, evidence index, role mapping and claim flags
defined above. Every fixed record must include all four sensitivity manifest
IDs. Add the most specific recovery/profile evidence to each diagnostic record.

Use these `allowed_use` values:

```python
fixed: ["forward_input", "fixed_parameter_stress_test"]
diagnostic_only: ["profile", "sensitivity", "experimental_design"]
```

Use these fixed prohibited claims:

```python
[
    "fixed_value_is_known_accurate",
    "fixed_value_has_no_uncertainty",
    "credible_inversion_point_estimate"
]
```

Use these diagnostic prohibited claims:

```python
[
    "credible_inversion_point_estimate",
    "mathematically_structurally_unidentifiable"
]
```

- [ ] **Step 4: Verify all role tests**

Run:

```bash
.venv/bin/pytest -q code/python/tests/test_gate_a6_parameter_roles.py
git diff --check
```

Expected: all pass and no whitespace errors.

- [ ] **Step 5: Commit implementation**

```bash
git add \
  config/parameter-roles/gate-a6-parameter-roles.json \
  code/python/scripts/validate_gate_a6_parameter_roles.py \
  code/python/tests/test_gate_a6_parameter_roles.py
git diff --cached --check
git commit -m "feat(a6): freeze evidence-based parameter roles"
git push origin codex/reclassify-project
```

## Task 4: Generate and validate the formal closure archive

**Files:**

- Create: `results/formal/identifiability/gate-a6-closure-${short_commit}/`

- [ ] **Step 1: Clean preflight**

Require:

```bash
test -z "$(git status --porcelain=v1)"
commit=$(git rev-parse --short=7 HEAD)
output="results/formal/identifiability/gate-a6-closure-${commit}"
test ! -e "$output"
```

- [ ] **Step 2: Run once**

```bash
.venv/bin/python \
  code/python/scripts/validate_gate_a6_parameter_roles.py \
  --registry config/parameter-roles/gate-a6-parameter-roles.json \
  --output "$output"
```

Expected command exit code: 0. The validation report's internal gate is
`PASS`; the scientific project status in the snapshot remains
`FAIL_RECOVERY`.

- [ ] **Step 3: Revalidate the archive bytes**

Use the already-tested `--archive` mode to recompute both artifact hashes and
manifest provenance without reading the source registry:

```bash
.venv/bin/python \
  code/python/scripts/validate_gate_a6_parameter_roles.py \
  --archive "$output"
```

Expected: validator report `gate=PASS`.

- [ ] **Step 4: Stop on any failure**

If registry or archive validation fails, preserve the new directory, record the
failure, and do not edit roles, evidence hashes or thresholds to obtain PASS.

## Task 5: Record the A6 decision

**Files:**

- Create: `results/formal/identifiability/gate-a6-closure-${short_commit}/acceptance.md`
- Modify: `documents/project/PROJECT_SUMMARY.md`
- Modify: `documents/project/WORK_STATUS.md`
- Modify: `documents/corrections/项目纠错.md`
- Modify: `documents/plans/2026-07-26-gate-a6-identifiability.md`

- [ ] **Step 1: Write acceptance**

Record:

- operational Gate A6 status `FAIL_RECOVERY`;
- validator `PASS`;
- 8 fixed, 5 diagnostic-only, 0 narrow-prior, 0 free;
- no eligible two-parameter combinations;
- no new numerical calculation;
- exact commit and artifact hashes;
- allowed and prohibited claims.

- [ ] **Step 2: Update project state**

Mark the original A6 profile/recovery/role tasks complete. Replace stale
“next optimizer comparison” text with:

```text
The frozen optimizer comparison and Sobol confirmation are complete.
No pair passed Recovery Gate v2. The current route is closed as
FAIL_RECOVERY; real-data TPE remains prohibited.
```

Do not mark A6 `PASS`.

- [ ] **Step 3: Add one correction**

Record the reusable rule:

```text
Operational fixed/free roles describe what the workflow may optimize.
They do not establish parameter truth or mathematical identifiability.
```

- [ ] **Step 4: Final verification**

Run:

```bash
.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q
.venv/bin/python code/python/scripts/audit_repository_layout.py
short_commit=$(git rev-parse --short=7 HEAD)
.venv/bin/python \
  code/python/scripts/validate_gate_a6_parameter_roles.py \
  --archive "results/formal/identifiability/gate-a6-closure-${short_commit}"
git diff --check
```

Expected: full test suite passes, Markdown audit passes, archive validator
passes and the worktree contains only the formal archive and project documents.

- [ ] **Step 5: Commit and push**

```bash
git add \
  results/formal/identifiability/gate-a6-closure-* \
  documents/project/PROJECT_SUMMARY.md \
  documents/project/WORK_STATUS.md \
  documents/corrections/项目纠错.md \
  documents/plans/2026-07-26-gate-a6-identifiability.md
git diff --cached --check
git commit -m "docs(a6): close failed multi-parameter recovery route"
git push origin codex/reclassify-project
```
