# Gate A5 Feature Channel Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze target-derived feature channels, weights, masks and loss
normalization so every candidate is evaluated against the same observations.

**Architecture:** Build an immutable channel contract when the objective is
created. Use it for all residual evaluation and fail closed when a candidate
cannot provide an active block. Audit real target contracts without running
parameter optimization and validate the archive independently.

**Tech Stack:** Python 3.13, NumPy, dataclasses, SHA-256, JSON/JSONL, pytest.

---

## Fixed decisions

- The target and config are the only channel-selection inputs.
- Candidate values never change masks, weights or active block counts.
- Candidate-side missing values return `feature_fail_penalty`.
- Loss normalization is the frozen sum of active block weights.
- Formal A5 uses four experimental traces for signal contracts only; it does
  not run TPE or authorize inversion.

## File map

| File | Responsibility |
|---|---|
| `code/python/src/oer_aem/inversion.py` | Channel records, contract builder, fixed-mask objective and result evidence |
| `code/python/tests/test_inversion.py` | Contract, normalization and fail-closed tests |
| `code/python/scripts/audit_feature_channel_contracts.py` | Fixed 16-contract A5 runner |
| `code/python/tests/test_feature_channel_contract_audit.py` | Runner classification tests |
| `code/python/scripts/validate_gate_a5_channels.py` | Independent archive validator |
| `code/python/tests/test_gate_a5_channel_validator.py` | Tamper and threshold tests |
| `results/formal/feature_channel_contract/gate-a5-<commit>/` | Formal compact evidence |

## Task 1: Build immutable target-side contracts

**Files:**

- Modify: `code/python/src/oer_aem/inversion.py`
- Modify: `code/python/tests/test_inversion.py`

- [ ] **Step 1: Write failing contract tests**

Create targets for legacy, complex, lock-in and hybrid modes. Require:

```python
contract = build_feature_channel_contract(target, config)
assert contract.normalization_weight_sum > 0
assert contract.sha256 == build_feature_channel_contract(
    copy.deepcopy(target), config
).sha256
assert all(
    item.exclusion_reason is None
    for item in contract.channels
    if item.active
)
```

Add low-SNR, missing target, non-finite target and insufficient lock-in points.
Require the exact exclusion reasons frozen in the design.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest -q code/python/tests/test_inversion.py \
  -k "channel_contract"
```

- [ ] **Step 3: Implement contract records**

Add frozen `FeatureChannel` and `FeatureChannelContract`. Internal lock-in
masks stay immutable NumPy arrays; `to_evidence()` emits only point counts and
mask hashes. Serialize sorted keys with `allow_nan=False` before hashing.

- [ ] **Step 4: Reject invalid DC at construction**

DC missing, wrong-shaped or non-finite must raise `ValueError`. Other disabled
blocks remain explicit non-active records.

- [ ] **Step 5: Verify**

```bash
.venv/bin/pytest -q code/python/tests/test_inversion.py \
  -k "channel_contract"
```

- [ ] **Step 6: Commit**

```bash
git add code/python/src/oer_aem/inversion.py \
  code/python/tests/test_inversion.py
git commit -m "feat(features): freeze target channel contracts"
```

## Task 2: Evaluate candidates against the frozen contract

**Files:**

- Modify: `code/python/src/oer_aem/inversion.py`
- Modify: `code/python/tests/test_inversion.py`

- [ ] **Step 1: Write failing invariance tests**

Require two finite candidates to retain identical:

```text
channel_contract_sha256
normalization_weight_sum
active channel IDs
```

Inject a NaN at one frozen lock-in point. Require:

```python
assert objective(candidate) == config.feature_fail_penalty
assert objective.n_feature_fail == 1
assert objective.last_components["feature_failure"] == (
    config.feature_fail_penalty
)
```

Also require a low-SNR inactive channel not to appear in the denominator.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest -q code/python/tests/test_inversion.py \
  -k "frozen_channel or feature_fail or normalization_weight"
```

- [ ] **Step 3: Implement fixed residual evaluation**

Add `feature_fail_penalty` to `InversionConfig`. Build the contract once in
`InversionObjective.__init__`. Replace candidate-dependent lock-in
intersections with each channel's frozen target mask. Validate candidate
shape and finiteness before computing any residual.

- [ ] **Step 4: Normalize by active weight sum**

Apply `phase_weight` to both complex and lock-in phase blocks. Divide total
weighted block loss by `contract.normalization_weight_sum`. Keep named
components, adding `feature_failure`.

- [ ] **Step 5: Extend result evidence**

Add `n_feature_fail`, `channel_contract`, `channel_contract_sha256` and
`normalization_weight_sum` to `InversionResult`.

- [ ] **Step 6: Verify related suites**

```bash
.venv/bin/pytest -q code/python/tests/test_inversion.py \
  code/python/tests/test_importance.py \
  code/python/tests/test_model_compare.py
```

- [ ] **Step 7: Commit**

```bash
git add code/python/src/oer_aem/inversion.py \
  code/python/tests/test_inversion.py
git commit -m "fix(objective): keep feature observations candidate invariant"
```

## Task 3: Build the formal A5 contract audit

**Files:**

- Create: `code/python/scripts/audit_feature_channel_contracts.py`
- Create: `code/python/tests/test_feature_channel_contract_audit.py`

- [ ] **Step 1: Write failing summary tests**

Require exactly 16 unique dataset/mode records, non-empty independently
recomputable contract hashes, positive finite weights, explicit exclusion
reasons and candidate invariance. Contract hashes may repeat when two records
have the same channel structure. Mutate each condition separately and require
`FAIL_CONTRACT`; malformed sets require `FAIL_STRUCTURE`.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest -q \
  code/python/tests/test_feature_channel_contract_audit.py
```

- [ ] **Step 3: Implement the runner**

Load FT2, FT3, FT4 and FT8 through the strict trace parser. Reuse the validated
signal extraction path, but do not call `TPEInverter`. Build four mode
contracts per dataset and write:

```text
channel_contracts.jsonl
candidate_invariance.jsonl
gate_a5_summary.json
run_manifest.json
```

Refuse a non-empty output directory.

- [ ] **Step 4: Verify**

```bash
.venv/bin/pytest -q \
  code/python/tests/test_feature_channel_contract_audit.py
```

- [ ] **Step 5: Commit**

```bash
git add code/python/scripts/audit_feature_channel_contracts.py \
  code/python/tests/test_feature_channel_contract_audit.py
git commit -m "feat(a5): audit frozen feature channels"
```

## Task 4: Add independent A5 validation

**Files:**

- Create: `code/python/scripts/validate_gate_a5_channels.py`
- Create: `code/python/tests/test_gate_a5_channel_validator.py`

- [ ] **Step 1: Write failing tamper tests**

Cover PASS, missing/duplicate contracts, artifact hash mismatch, invalid
exclusion reason, zero active weight, contract hash mismatch, candidate mask
drift, normalization drift, missing failure injection and runner-summary
tampering.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest -q code/python/tests/test_gate_a5_channel_validator.py
```

- [ ] **Step 3: Implement independent validation**

Do not import the runner or `oer_aem.inversion`. Recompute evidence hashes,
contract hashes, active weight sums, exact dataset/mode sets and the final
Gate.

Exit codes:

```text
0 PASS
2 FAIL_CONTRACT
3 FAIL_NUMERICAL
4 FAIL_STRUCTURE
```

- [ ] **Step 4: Run all tests**

```bash
.venv/bin/pytest -q code/python/tests/test_gate_a5_channel_validator.py
.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q
```

- [ ] **Step 5: Commit**

```bash
git add code/python/scripts/validate_gate_a5_channels.py \
  code/python/tests/test_gate_a5_channel_validator.py
git commit -m "feat(a5): independently validate channel contracts"
```

## Task 5: Run Gate A5 once and publish

**Files:**

- Create: `results/formal/feature_channel_contract/gate-a5-<commit>/`
- Modify: `documents/project/WORK_STATUS.md`
- Modify: `documents/project/PROJECT_SUMMARY.md`
- Modify: `documents/corrections/项目纠错.md` only for new reusable issues

- [ ] **Step 1: Clean preflight**

```bash
.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q
.venv/bin/python code/python/scripts/audit_repository_layout.py
git diff --check
git status --short
```

- [ ] **Step 2: Run the formal contract audit once**

```bash
commit=$(git rev-parse --short=7 HEAD)
output="results/formal/feature_channel_contract/gate-a5-${commit}"
PYTHONPATH=code/python/src .venv/bin/python \
  code/python/scripts/audit_feature_channel_contracts.py --output "$output"
PYTHONPATH=code/python/src .venv/bin/python \
  code/python/scripts/validate_gate_a5_channels.py --archive "$output"
```

- [ ] **Step 3: Enforce the result**

PASS closes the A5 channel/loss contract only. Any failure is retained and
stops layer-B precision comparisons. Do not rerun with changed target rules.

- [ ] **Step 4: Update acceptance and project state**

Record contract hashes, active/excluded channels, weights, mask counts,
normalization sums, failure injection and allowed/prohibited claims.

- [ ] **Step 5: Verify, commit and push**

```bash
.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q
.venv/bin/python code/python/scripts/audit_repository_layout.py
git diff --check
git add results/formal/feature_channel_contract/gate-a5-* \
  documents/project/WORK_STATUS.md \
  documents/project/PROJECT_SUMMARY.md \
  documents/corrections/项目纠错.md
git commit -m "docs(a5): record feature channel contract gate"
git push origin codex/reclassify-project
```

## Plan self-review

- Target-only selection and candidate fail-closed behavior each have tests.
- Every inactive block has a finite vocabulary reason.
- Loss denominator is derived from the same active records as the numerator.
- Formal execution does not run TPE or reinterpret A1/A6.
- Historical A4/A5/A6 evidence remains unchanged.
- No unresolved placeholder remains.
