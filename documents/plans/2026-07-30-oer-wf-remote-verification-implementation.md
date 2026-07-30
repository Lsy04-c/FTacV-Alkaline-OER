# oer-wf Frozen Remote Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `wf verify` reproduce scientific validators in the frozen Legion worktree and environment while keeping synchronized calculation archives immutable.

**Architecture:** Local validators check the Mac archive. Validators marked
`execution: remote_worktree` run through a small JSON worker on Legion. The
dispatcher validates commit, paths and environment before execution, then writes
an append-only receipt outside the calculation archive.

**Tech Stack:** Python 3.11/3.13, Pydantic, Typer, pytest, SSH, JSON, YAML.

---

### Task 1: Freeze verification runtime in snapshots

**Files:**
- Modify: `config/oer-wf/oer_wf/models.py`
- Modify: `config/oer-wf/oer_wf/snapshot.py`
- Modify: `config/oer-wf/tests/test_snapshot.py`
- Modify: `config/oer-wf/tests/test_verify.py`

- [ ] Add failing tests that require snapshot `env`, `python` and
  `worktree_root`, reject secret-like environment keys, and validate
  `execution` plus `timeout_sec`.
- [ ] Run the focused tests and confirm failure because these fields are absent.
- [ ] Add the minimal model validators and snapshot serialization.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Separate validator execution from command orchestration

**Files:**
- Create: `config/oer-wf/oer_wf/validator_runner.py`
- Modify: `config/oer-wf/oer_wf/commands/verify.py`
- Create: `config/oer-wf/tests/test_validator_runner.py`

- [ ] Add failing tests for local dispatch and removal of orchestration keys
  before validator invocation.
- [ ] Confirm RED because no shared runner exists.
- [ ] Move the validator map and common invocation into `validator_runner.py`.
- [ ] Keep existing local behavior unchanged and confirm GREEN.

### Task 3: Add the remote validator worker

**Files:**
- Create: `config/oer-wf/oer_wf/remote_verify.py`
- Create: `config/oer-wf/tests/test_remote_verify.py`

- [ ] Add failing tests for base64 JSON input, frozen commit checks, worktree and
  result-path containment, tracked-source cleanliness, env restoration, and
  one-JSON stdout.
- [ ] Confirm RED because the worker does not exist.
- [ ] Implement the worker without archive writes.
- [ ] Confirm all worker tests pass.

### Task 4: Route marked validators to Legion

**Files:**
- Modify: `config/oer-wf/oer_wf/commands/verify.py`
- Modify: `config/oer-wf/oer_wf/transport.py`
- Modify: `config/oer-wf/tests/test_verify.py`

- [ ] Add failing MockExecutor tests for successful remote checks, SSH failure,
  timeout, invalid JSON, commit mismatch, path mismatch and missing frozen env.
- [ ] Confirm RED because `run_verify` does not accept an executor or remote
  execution.
- [ ] Add dependency-injected remote dispatch with base64 payload and bounded
  timeout.
- [ ] Confirm local validators never use SSH and remote failures keep their
  transport/environment/structure class.

### Task 5: Add immutable verification receipts

**Files:**
- Create: `config/oer-wf/oer_wf/verification_receipt.py`
- Modify: `config/oer-wf/oer_wf/commands/verify.py`
- Create: `config/oer-wf/tests/test_verification_receipt.py`
- Modify: `config/oer-wf/tests/test_verify.py`

- [ ] Add failing tests for archive tree-hash stability, atomic receipt write,
  collision refusal and receipt metadata.
- [ ] Confirm RED because receipt support is absent.
- [ ] Implement append-only receipts under
  `MAC_ARCHIVE_ROOT/verifications/...`.
- [ ] Confirm the calculation archive hash is unchanged before and after verify.

### Task 6: Correct scientific failure classification

**Files:**
- Modify: `config/oer-wf/oer_wf/validators/v3_residual_attribution_gate.py`
- Modify: `config/oer-wf/oer_wf/validators/v4_experiment_design_gate.py`
- Modify: `config/oer-wf/tests/test_v3_residual_attribution_gate.py`
- Modify: `config/oer-wf/tests/test_v4_experiment_design_gate.py`

- [ ] Add failing tests showing `FAIL_NUMERICAL` must emit a `numerical:*`
  check and a valid but failed scientific gate must emit `scientific:*`.
- [ ] Confirm current wrappers incorrectly emit `structure:*`.
- [ ] Implement explicit gate-to-check mapping and confirm GREEN.

### Task 7: Enable remote execution in scientific TaskSpecs

**Files:**
- Modify: `config/oer-wf/examples/v2_conditional_reachability_lsoda.yaml`
- Modify: `config/oer-wf/examples/v3_residual_attribution_lsoda.yaml`
- Modify: `config/oer-wf/examples/v4_experiment_design_lsoda.yaml`
- Modify: `config/oer-wf/tests/test_verify.py`

- [ ] Add tests that all formal rerun validators declare
  `execution: remote_worktree` and bounded timeouts.
- [ ] Confirm RED against current YAML.
- [ ] Add routing fields without changing scientific thresholds or compute
  commits.
- [ ] Confirm TaskSpec hashes change and tests pass.

### Task 8: Version and documentation

**Files:**
- Modify: `config/oer-wf/pyproject.toml`
- Modify: `config/oer-wf/oer_wf/__init__.py`
- Modify: `documents/specifications/oer-wf-workflow-guide.md`
- Modify: `documents/project/WORK_STATUS.md`
- Modify: `documents/corrections/项目纠错.md`

- [ ] Bump oer-wf to `0.7.0`.
- [ ] Document local/remote validator split, receipts, failure classes and old
  snapshot behavior.
- [ ] Record that thresholds and prior Gate conclusions remain unchanged.

### Task 9: Full local verification

**Files:** no new files.

- [ ] Run `pytest config/oer-wf/tests -q`; require zero failures.
- [ ] Run `python code/python/scripts/run_tests.py code/python/tests -q`;
  require zero failures.
- [ ] Run `pytest code/web/tests -q`; require zero failures apart from the
  existing Starlette deprecation warning.
- [ ] Run `git diff --check` excluding immutable CRLF scientific CSV evidence.

### Task 10: Legion deployment and real closure

**Files:** generated smoke evidence and project status only after PASS.

- [ ] Commit and push the implementation.
- [ ] Update `/home/lsy/oer-wf` from the frozen implementation commit without
  reinstalling NumPy.
- [ ] Confirm remote import path, version and full oer-wf tests.
- [ ] Run a new V4 smoke with the updated snapshot and frozen compute commit.
- [ ] Sync that exact smoke timestamp to a new Mac archive.
- [ ] Run `wf verify`; require local integrity checks, remote scientific
  validator, frozen env restoration and a receipt.
- [ ] Hash the calculation archive before and after verify; require equality.
- [ ] On PASS, update progress/correction documents, commit only project files
  and push. On any failure, stop, preserve evidence and report the exact class.
