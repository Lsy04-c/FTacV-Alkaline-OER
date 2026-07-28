# Gate A1 Experimental Data Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and formally audit a strict, provenance-aware contract for the
four frozen FTacV experimental files without silently repairing raw data or
inventing missing metadata.

**Architecture:** Extend the low-level data contract with a strict parser and
deterministic sampling diagnostics. Store expected file facts and metadata
source levels in a tracked registry. Keep the audit runner and independent
validator separate; both read raw files directly, while only the runner writes
formal evidence.

**Tech Stack:** Python 3.13, NumPy, JSON, SHA-256, pytest.

---

## Fixed decisions

- Inputs are FT2, FT3, FT4 and FT8 under `data/raw/`.
- Raw files remain unchanged and are never sorted, deduplicated, trimmed or
  interpolated.
- Formal schema is exactly three numeric columns:
  `potential,current,time`.
- File facts, derived values, external declarations and legacy assumptions are
  stored separately.
- Filename frequency is only a cross-check.
- Formal outcome may be `FAIL_METADATA`; engineering completion is not Gate
  PASS.
- No Legion compute, CN, LSODA, Web backend or dependency installation is
  needed.

## File map

| File | Responsibility |
|---|---|
| `code/python/src/oer_aem/data_contract.py` | Strict parsing, immutable file facts and deterministic diagnostics |
| `code/python/tests/test_data_contract.py` | Parser and threshold unit tests |
| `config/data-contracts/gate-a1-datasets.json` | Frozen dataset registry and metadata source levels |
| `code/python/scripts/audit_experimental_contracts.py` | Formal audit and evidence writer |
| `code/python/tests/test_experimental_contract_audit.py` | Registry, runner and real-file integration tests |
| `code/python/scripts/validate_gate_a1_contracts.py` | Independent archive validator |
| `code/python/tests/test_gate_a1_contract_validator.py` | Failure classification and tamper tests |
| `results/formal/data_contract/gate-a1-<commit>/` | Compact formal evidence |
| `documents/project/WORK_STATUS.md` | Execution record |
| `documents/project/PROJECT_SUMMARY.md` | Current Gate A1 status |

## Task 1: Add a strict raw-file parser

**Files:**

- Modify: `code/python/src/oer_aem/data_contract.py`
- Modify: `code/python/tests/test_data_contract.py`

- [ ] **Step 1: Write failing parser tests**

Add tests that create temporary files and require:

```python
from oer_aem.data_contract import read_strict_experimental_trace


def test_strict_trace_preserves_original_rows(tmp_path):
    path = tmp_path / "trace.txt"
    path.write_text("1.0 2.0 0.0\n1.1 3.0 0.5\n")
    trace, facts = read_strict_experimental_trace(path)
    assert trace.potential.tolist() == [1.0, 1.1]
    assert trace.current.tolist() == [2.0, 3.0]
    assert trace.time.tolist() == [0.0, 0.5]
    assert facts.n_rows == 2
    assert facts.n_columns == 3


@pytest.mark.parametrize(
    "content,match",
    [
        ("1 2\n", "exactly three"),
        ("1 2 3 4\n", "exactly three"),
        ("potential current time\n1 2 0\n", "numeric"),
        ("1 nan 0\n", "finite"),
        ("1 2 0\n2 3 0\n", "strictly increasing"),
        ("1 2 1\n2 3 0\n", "strictly increasing"),
    ],
)
def test_strict_trace_rejects_invalid_raw_structure(
    tmp_path, content, match
):
    path = tmp_path / "trace.txt"
    path.write_text(content)
    with pytest.raises(ValueError, match=match):
        read_strict_experimental_trace(path)
```

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/pytest -q code/python/tests/test_data_contract.py \
  -k "strict_trace"
```

Expected: import failure because `read_strict_experimental_trace` is absent.

- [ ] **Step 3: Implement the minimal parser**

Add:

```python
from pathlib import Path
import hashlib


@dataclass(frozen=True)
class ExperimentalFileFacts:
    sha256: str
    byte_count: int
    n_rows: int
    n_columns: int


def read_strict_experimental_trace(
    path: str | Path,
) -> tuple[ExperimentalTrace, ExperimentalFileFacts]:
    source = Path(path)
    raw = source.read_bytes()
    if not raw:
        raise ValueError("experimental file must not be empty")
    rows = []
    for line_number, line in enumerate(
        raw.decode("utf-8").splitlines(), start=1
    ):
        fields = line.split()
        if len(fields) != 3:
            raise ValueError(
                f"line {line_number} must contain exactly three columns"
            )
        try:
            rows.append([float(field) for field in fields])
        except ValueError as exc:
            raise ValueError(
                f"line {line_number} must be numeric"
            ) from exc
    values = np.asarray(rows, dtype=float)
    if not np.all(np.isfinite(values)):
        raise ValueError("experimental values must be finite")
    if np.any(np.diff(values[:, 2]) <= 0):
        raise ValueError("time must be strictly increasing")
    trace = ExperimentalTrace(
        potential=values[:, 0].copy(),
        current=values[:, 1].copy(),
        time=values[:, 2].copy(),
    )
    facts = ExperimentalFileFacts(
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_count=len(raw),
        n_rows=len(values),
        n_columns=3,
    )
    return trace, facts
```

The parser must not call `normalize_trace`.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
.venv/bin/pytest -q code/python/tests/test_data_contract.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add code/python/src/oer_aem/data_contract.py \
  code/python/tests/test_data_contract.py
git commit -m "feat(data): add strict experimental trace parser"
```

## Task 2: Compute deterministic sampling diagnostics

**Files:**

- Modify: `code/python/src/oer_aem/data_contract.py`
- Modify: `code/python/tests/test_data_contract.py`

- [ ] **Step 1: Write failing known-signal tests**

Use a 5 Hz potential signal on a 0.01 V/s ramp:

```python
from oer_aem.data_contract import derive_sampling_diagnostics


def test_sampling_diagnostics_recover_known_signal():
    fs = 1280.0
    time = np.arange(0.0, 20.0, 1.0 / fs)
    potential = (
        1.0 + 0.01 * time
        + 0.16 * np.sin(2.0 * np.pi * 5.0 * time)
    )
    trace = ExperimentalTrace(
        potential=potential,
        current=np.zeros_like(time),
        time=time + 7.0,
    )
    result = derive_sampling_diagnostics(trace)
    assert result["sampling_rate_hz"] == pytest.approx(fs, rel=1e-12)
    assert result["frequency_hz"] == pytest.approx(5.0, rel=1e-6)
    assert result["scan_rate_v_s"] == pytest.approx(0.01, rel=1e-6)
    assert result["amplitude_v"] == pytest.approx(0.16, rel=1e-6)
```

Add boundary tests for jitter, a deleted sample, fewer than 20 cycles and fewer
than 64 samples per cycle.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest -q code/python/tests/test_data_contract.py \
  -k "sampling_diagnostics"
```

Expected: import failure because the diagnostic function is absent.

- [ ] **Step 3: Implement diagnostics and frozen numerical checks**

Implement `derive_sampling_diagnostics(trace)` using:

- `duration / (n_rows - 1)` for nominal sampling interval and sampling rate;
- maximum residual from the nominal timestamp grid to measure export
  quantization;
- least-squares linear trend for DC potential;
- FFT of detrended applied potential for an initial frequency;
- sine/cosine least squares at that frequency for amplitude;
- explicit metrics for jitter, maximum gap, cycles and points per cycle.

Implement:

```python
GATE_A1_THRESHOLDS = {
    "expected_rows": 65536,
    "max_timestamp_residual_samples": 1e-2,
    "max_gap_ratio": 1.05,
    "min_points_per_cycle": 64.0,
    "min_complete_cycles": 20,
    "max_frequency_relative_error": 1e-3,
    "max_scan_rate_relative_error": 5e-4,
    "max_amplitude_relative_error": 5e-3,
}
```

Keep metric computation separate from comparison to declared metadata.

- [ ] **Step 4: Verify all contract tests**

```bash
.venv/bin/pytest -q code/python/tests/test_data_contract.py
```

- [ ] **Step 5: Commit**

```bash
git add code/python/src/oer_aem/data_contract.py \
  code/python/tests/test_data_contract.py
git commit -m "feat(data): derive frozen sampling diagnostics"
```

## Task 3: Freeze the dataset registry

**Files:**

- Create: `config/data-contracts/gate-a1-datasets.json`
- Create: `code/python/tests/test_experimental_contract_audit.py`

- [ ] **Step 1: Write a failing registry test**

The test must load the registry and assert exactly four dataset IDs, relative
paths, current hashes, expected 65,536 rows and source levels for every required
metadata field:

```python
REQUIRED_METADATA = {
    "potential_unit",
    "potential_reference",
    "current_unit",
    "time_unit",
    "frequency_hz",
    "amplitude_v",
    "scan_rate_v_s",
    "scan_direction",
    "continuous_forward_scan",
    "instrument_preprocessing",
}
ACCEPTED_SOURCES = {
    "file_observed",
    "derived",
    "externally_declared",
}
```

The test must allow `legacy_assumption` and `unresolved` in the registry but
must not treat them as acceptable Gate evidence.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest -q \
  code/python/tests/test_experimental_contract_audit.py
```

Expected: file-not-found failure.

- [ ] **Step 3: Create the registry**

Use exact current hashes from the design. Record existing project conventions
as `legacy_assumption`, not `externally_declared`. Use `unresolved` for
potential reference and instrument preprocessing unless a tracked primary
source already proves them.

Each field uses:

```json
{
  "value": null,
  "source_kind": "unresolved",
  "source_note": "No instrument method or primary experiment record in repository"
}
```

Derived frequency, amplitude and scan rate may use `source_kind: "derived"`;
the formal runner fills their measured values rather than trusting filenames.

- [ ] **Step 4: Verify the registry test**

```bash
.venv/bin/pytest -q \
  code/python/tests/test_experimental_contract_audit.py
```

- [ ] **Step 5: Commit**

```bash
git add config/data-contracts/gate-a1-datasets.json \
  code/python/tests/test_experimental_contract_audit.py
git commit -m "data(a1): freeze experimental dataset registry"
```

## Task 4: Build the formal audit runner

**Files:**

- Create: `code/python/scripts/audit_experimental_contracts.py`
- Modify: `code/python/tests/test_experimental_contract_audit.py`

- [ ] **Step 1: Write failing runner tests**

Tests must require:

- deterministic JSON with sorted keys and no NaN;
- `PASS`, `FAIL_STRUCTURE`, `FAIL_NUMERICAL` or `FAIL_METADATA`;
- per-field `source_kind`;
- per-dataset file facts and diagnostics;
- no output creation when the registry is malformed;
- aggregate FAIL when any one dataset fails;
- `--output` must be a new or empty directory;
- no imports from `code/web`, C++ bridge or solver modules.

Example assertion:

```python
assert summary["gate"] == "FAIL_METADATA"
assert summary["structure_passed"] is True
assert summary["numerical_passed"] is True
assert summary["metadata_passed"] is False
assert summary["eligible_for_inversion"] is False
```

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest -q \
  code/python/tests/test_experimental_contract_audit.py -k runner
```

- [ ] **Step 3: Implement the runner**

CLI:

```text
audit_experimental_contracts.py
  --registry config/data-contracts/gate-a1-datasets.json
  --output <new-directory>
```

Write atomically:

- `dataset_contracts.json`;
- `gate_a1_summary.json`;
- `run_manifest.json`.

Manifest fields include commit, dirty state, registry SHA-256, every raw file
SHA-256, Python and NumPy versions, command and UTC timestamps. Dirty project
state is a structure failure for a formal run.

- [ ] **Step 4: Verify runner tests and real dry run**

```bash
.venv/bin/pytest -q \
  code/python/tests/test_experimental_contract_audit.py
tmp_dir=$(mktemp -d)
.venv/bin/python code/python/scripts/audit_experimental_contracts.py \
  --registry config/data-contracts/gate-a1-datasets.json \
  --output "$tmp_dir/audit"
```

Expected real outcome with current evidence:
`FAIL_METADATA`, not `PASS`.

- [ ] **Step 5: Commit**

```bash
git add code/python/scripts/audit_experimental_contracts.py \
  code/python/tests/test_experimental_contract_audit.py
git commit -m "feat(a1): audit experimental data contracts"
```

## Task 5: Add an independent archive validator

**Files:**

- Create: `code/python/scripts/validate_gate_a1_contracts.py`
- Create: `code/python/tests/test_gate_a1_contract_validator.py`

- [ ] **Step 1: Write failing validator tests**

Create synthetic archives and require:

1. valid structure and numerical evidence with unresolved metadata returns
   `FAIL_METADATA`;
2. a modified raw-file hash returns `FAIL_STRUCTURE`;
3. missing/extra dataset returns `FAIL_STRUCTURE`;
4. NaN or invalid time metrics returns `FAIL_NUMERICAL`;
5. legacy assumptions never satisfy required metadata;
6. all accepted metadata and valid metrics return `PASS`;
7. changing runner-reported gate without changing evidence is detected.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest -q \
  code/python/tests/test_gate_a1_contract_validator.py
```

- [ ] **Step 3: Implement independent recomputation**

The validator reads the registry, raw files and archive. It must independently:

- hash and parse each raw file;
- recalculate row/column/finite/time checks;
- recalculate sampling metrics without importing the runner;
- apply source-level and numerical thresholds;
- compare the recomputed result with both JSON outputs.

CLI:

```text
validate_gate_a1_contracts.py
  --registry <registry>
  --archive <archive>
```

Exit codes:

- `0`: PASS;
- `2`: FAIL_METADATA;
- `3`: FAIL_NUMERICAL;
- `4`: FAIL_STRUCTURE.

- [ ] **Step 4: Verify validator and all Python tests**

```bash
.venv/bin/pytest -q \
  code/python/tests/test_gate_a1_contract_validator.py
.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q
```

- [ ] **Step 5: Commit**

```bash
git add code/python/scripts/validate_gate_a1_contracts.py \
  code/python/tests/test_gate_a1_contract_validator.py
git commit -m "feat(a1): independently validate data contracts"
```

## Task 6: Freeze and run the formal Gate A1 audit

**Files:**

- Create:
  `results/formal/data_contract/gate-a1-<commit>/dataset_contracts.json`
- Create:
  `results/formal/data_contract/gate-a1-<commit>/gate_a1_summary.json`
- Create:
  `results/formal/data_contract/gate-a1-<commit>/run_manifest.json`
- Create:
  `results/formal/data_contract/gate-a1-<commit>/acceptance.md`

- [ ] **Step 1: Run preflight verification**

```bash
.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q
.venv/bin/python code/python/scripts/audit_repository_layout.py
git diff --check
git status --short
```

Expected: tests and audits pass; working tree clean.

- [ ] **Step 2: Freeze the implementation commit**

Commit all implementation files before running formal evidence. Record the full
commit in the output directory name and manifest.

- [ ] **Step 3: Run once on Mac**

Gate A1 is file auditing, not an ODE task. Run it locally:

```bash
commit=$(git rev-parse --short=7 HEAD)
output="results/formal/data_contract/gate-a1-${commit}"
.venv/bin/python code/python/scripts/audit_experimental_contracts.py \
  --registry config/data-contracts/gate-a1-datasets.json \
  --output "$output"
.venv/bin/python code/python/scripts/validate_gate_a1_contracts.py \
  --registry config/data-contracts/gate-a1-datasets.json \
  --archive "$output"
```

If the runner requires a clean tree, create evidence outside the repository,
validate it there, then copy only the validated compact artifacts into the
tracked result directory.

- [ ] **Step 4: Enforce the outcome**

- `FAIL_STRUCTURE` or `FAIL_NUMERICAL`: stop and diagnose before any later
  Gate.
- `FAIL_METADATA`: keep engineering evidence, request only the missing primary
  metadata and do not enable inversion.
- `PASS`: close Gate A1.

Do not alter source levels or thresholds after seeing the result.

- [ ] **Step 5: Write acceptance**

Record:

- implementation commit and registry hash;
- four file hashes and row counts;
- all sampling metrics;
- exact missing metadata;
- independent validator result;
- artifact SHA-256 values;
- allowed and prohibited conclusions.

Do not duplicate raw data in the result directory.

## Task 7: Update project state and publish

**Files:**

- Modify: `documents/project/WORK_STATUS.md`
- Modify: `documents/project/PROJECT_SUMMARY.md`
- Modify: `documents/corrections/项目纠错.md` only if a new issue occurred

- [ ] **Step 1: Update status with the actual formal outcome**

If metadata remains unresolved, write:

```text
Gate A1 engineering implementation PASS; formal gate FAIL_METADATA.
Downstream real inversion remains prohibited.
```

Never replace that with “A1 completed”.

- [ ] **Step 2: Run fresh completion verification**

```bash
.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q
.venv/bin/python code/python/scripts/audit_repository_layout.py
git diff --check
```

- [ ] **Step 3: Commit compact evidence and documents**

```bash
git add results/formal/data_contract/gate-a1-* \
  documents/project/WORK_STATUS.md \
  documents/project/PROJECT_SUMMARY.md
git commit -m "docs(a1): record formal data contract audit"
```

- [ ] **Step 4: Push only project files**

```bash
git push origin codex/reclassify-project
```

## Plan self-review

- **Spec coverage:** strict parsing, hashes, source levels, sampling diagnostics,
  thresholds, failure classes, independent validation, formal evidence and
  project updates each map to a task.
- **Data leakage:** no model, fitted parameters or recovery truth enters A1.
- **Raw-data safety:** no task modifies `data/raw/`.
- **Metadata honesty:** current missing primary metadata yields
  `FAIL_METADATA`; filenames and defaults cannot promote it to PASS.
- **Numerical pressure:** boundary tests cover every frozen threshold.
- **Environment:** local Mac execution is sufficient; no remote dependency or
  ODE compute is introduced.
- **Failure exit:** later Gate work stops on structure/numerical failure and
  remains prohibited on metadata failure.
- **Placeholder scan:** no unresolved implementation placeholder remains.
