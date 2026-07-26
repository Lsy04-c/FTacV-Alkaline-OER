# OER-FTAcV Project Directory Reclassification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reclassify all project code, documents, data, and evidence into a navigable repository layout without changing scientific behavior or losing user files.

**Architecture:** Move the repository in gated stages. Establish README navigation and layout tests first, then migrate documents, MATLAB/C++, Python, Web, and results while updating every path consumer. Preserve Git history with `git mv`, keep secrets and build products untracked, and stop after any failed gate.

**Tech Stack:** Git, Python 3.13 on Mac, Python 3.11 on Legion, pytest, MATLAB source, C++17, FastAPI, React/Vite, Markdown.

---

## Preconditions

- Approved design: `docs/superpowers/specs/2026-07-26-project-directory-reclassification-design.md`
- Current tracked baseline at plan creation: `55927a4`
- Existing user files and unrelated changes must remain intact:
  - modified `results/architecture_validation/feature_objective_comparison.csv`;
  - untracked local C++ binaries and experiments;
  - untracked environment documents;
  - untracked `python/oer_aem/_rhs_jit.py`;
  - untracked local workflow and plan documents.
- The Legion solver-equivalence run based on `1becc12` must be accepted and synchronized before path migration begins.
- This migration changes paths only. It must not change equations, feature definitions, parameter bounds, scientific thresholds, or formal TPE settings.

## Target file map

### Code

```text
code/python/src/oer_aem/     Python scientific package
code/python/tests/           Python package tests
code/python/scripts/         Analysis and validation entry points
code/python/examples/        Python examples
code/matlab/src/             MATLAB implementation
code/matlab/tests/           MATLAB tests
code/cpp/src/                C++ production source
code/cpp/src/experimental/   C++ experimental source
code/cpp/build/              Ignored local binaries
code/web/frontend/           Browser application
code/web/backend/            FastAPI application
code/web/tests/backend/      Web backend tests
```

### Documents

```text
documents/project/           Goals, status, workflow, validation reports
documents/corrections/       Project error and correction records
documents/plans/             Executable plans
documents/specifications/    Design specifications
documents/research/          Papers, mechanisms, parameter studies
documents/environment/       Sanitized environment documentation
documents/handoffs/          Ignored local agent handoffs
```

### Evidence

```text
results/formal/              Manifest-backed formal evidence
results/smoke/               Small-budget workflow checks
results/diagnostics/         Data, residual, solver, grid, and model diagnostics
```

---

### Task 1: Close the active solver-equivalence evidence before migration

**Files:**
- Copy from Legion: `/home/lsy/OER-FTAcV/results/solver_equivalence/formal-1becc12/`
- Create: `results/solver_equivalence/formal-1becc12/`
- Modify: `WORK_STATUS.md`
- Modify: `docs/项目纠错.md`
- Modify: `PROJECT_SUMMARY.md`

- [ ] **Step 1: Observe the 20-minute remote-check rule**

Run:

```bash
date '+%Y-%m-%d %H:%M:%S %Z'
```

Expected: Beijing time at or after the next permitted check. If it is earlier, stop this task without contacting Legion.

- [ ] **Step 2: Inspect the remote result without changing it**

Run through the existing Windows-to-WSL connection:

```bash
wsl -d Debian-Bookworm -u lsy -- sh -lc \
  'test -f /home/lsy/OER-FTAcV/results/solver_equivalence/formal-1becc12/solver_equivalence_summary.json &&
   test -f /home/lsy/OER-FTAcV/results/solver_equivalence/formal-1becc12/solver_equivalence.csv'
```

Expected: exit 0. If either file is absent, inspect tmux and report progress; do not start directory migration.

- [ ] **Step 3: Validate the formal schema on Legion**

Run:

```bash
/home/lsy/OER-FTAcV-run-8cf26be/.venv/bin/python - <<'PY'
import csv
import json
from pathlib import Path

root = Path("/home/lsy/OER-FTAcV/results/solver_equivalence/formal-1becc12")
summary = json.loads((root / "solver_equivalence_summary.json").read_text())
rows = list(csv.DictReader((root / "solver_equivalence.csv").open()))
assert summary["samples"] == 24
assert summary["cycles"] == 256
assert summary["points_per_cycle"] == 128
assert summary["resolvability_fraction"] == 0.02
assert len(rows) == 168
assert len({int(row["sample"]) for row in rows}) == 24
assert all(row["lsoda_success"] == "True" for row in rows)
assert all(row["cn_success"] == "True" for row in rows)
print("PASS" if summary["passed"] else "FAIL", summary["n_failures"])
PY
```

Expected: `PASS 0` for a passed gate. A FAIL stops CN adoption and this migration task records the failure before continuing with later local-only work.

- [ ] **Step 4: Synchronize exact evidence to Mac**

Copy only:

```text
solver_equivalence.csv
solver_equivalence_summary.json
started_at.txt
commit.txt
python.txt
```

Expected: local byte counts and SHA-256 hashes match the remote files.

- [ ] **Step 5: Update project state**

Record:

- formal configuration;
- commit and environment;
- row and sample counts;
- gate decision;
- allowed or forbidden next use of CN;
- statement that formal TPE remains paused.

- [ ] **Step 6: Verify and commit solver evidence**

Run:

```bash
.venv/bin/python scripts/run_tests.py python/tests -q
git diff --check
git diff --cached
```

Expected: all Python tests pass and only solver evidence plus three project-state documents are staged.

Commit:

```bash
git commit -m "docs(solver): record formal backend equivalence"
git push origin main
```

---

### Task 2: Add repository-layout tests and README skeleton

**Files:**
- Create: `code/python/tests/test_repository_layout.py`
- Create: `code/python/README.md`
- Create: `code/matlab/README.md`
- Create: `code/cpp/README.md`
- Create: `code/web/README.md`
- Create: `documents/README.md`
- Create: `config/README.md`
- Modify: `README.md`
- Modify: `.gitignore`

- [ ] **Step 1: Create the target directory skeleton**

Create:

```text
code/python/src/
code/python/tests/
code/python/scripts/
code/python/examples/
code/matlab/src/
code/matlab/tests/
code/cpp/src/experimental/
code/cpp/tests/
code/cpp/build/
code/web/backend/
code/web/frontend/
code/web/tests/backend/
documents/project/
documents/corrections/
documents/plans/
documents/specifications/
documents/research/
documents/environment/
documents/handoffs/
config/
```

Do not move scientific code in this step.

- [ ] **Step 2: Write the failing layout test**

Create `code/python/tests/test_repository_layout.py`:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_required_top_level_directories_exist():
    required = {
        "code/python",
        "code/matlab",
        "code/cpp",
        "code/web",
        "documents/project",
        "documents/corrections",
        "documents/plans",
        "documents/specifications",
        "documents/research",
        "documents/environment",
        "data/raw",
        "data/processed",
        "results/formal",
        "results/smoke",
        "results/diagnostics",
        "config",
    }
    missing = sorted(path for path in required if not (ROOT / path).is_dir())
    assert missing == []


def test_root_markdown_is_limited_to_navigation():
    allowed = {"README.md"}
    actual = {path.name for path in ROOT.glob("*.md")}
    assert actual == allowed


def test_code_and_document_indexes_exist():
    required = {
        "README.md",
        "code/python/README.md",
        "code/matlab/README.md",
        "code/cpp/README.md",
        "code/web/README.md",
        "documents/README.md",
        "data/README.md",
        "results/README.md",
        "config/README.md",
    }
    missing = sorted(path for path in required if not (ROOT / path).is_file())
    assert missing == []
```

- [ ] **Step 3: Run the layout test and observe RED**

Run:

```bash
.venv/bin/python -m pytest code/python/tests/test_repository_layout.py -q
```

Expected: failure because root project Markdown files and result classification directories still use the old layout.

- [ ] **Step 4: Write the README indexes**

Root `README.md` must contain:

```markdown
# OER-FTAcV

碱性 OER FTacV 微观动力学建模、谐波分析和参数反演项目。

## 目录索引

| 路径 | 内容 |
|---|---|
| `code/python/` | Python 科学计算核心、测试和计算脚本 |
| `code/matlab/` | MATLAB 参考实现和测试 |
| `code/cpp/` | C++ 数值求解器源码与本机构建目录 |
| `code/web/` | 前端和 FastAPI 服务 |
| `documents/` | 项目、纠错、计划、规格、科研和环境文档 |
| `data/` | 原始和处理数据 |
| `results/` | formal、smoke 和 diagnostics 证据 |
| `config/` | 不含秘密的项目配置 |
```

Until Task 3 moves the documents, keep working links to the current paths:

- `PROJECT_SUMMARY.md`;
- `WORK_STATUS.md`;
- `docs/项目纠错.md`;
- each code README.

Task 3 replaces these three links with their final `documents/` paths in the same commit that moves the files.

- [ ] **Step 5: Add future file-placement rules**

Add this table to both `README.md` and `documents/README.md`:

```markdown
| 新内容 | 保存位置 |
|---|---|
| 项目目标、状态、工作流 | `documents/project/` |
| 错误、根因、修复 | `documents/corrections/` |
| 可执行任务步骤 | `documents/plans/` |
| 架构和接口规格 | `documents/specifications/` |
| 文献、机理和研究分析 | `documents/research/` |
| 脱敏环境说明 | `documents/environment/` |
| agent 交接 | `documents/handoffs/` |
```

State explicitly: do not add project-background Markdown to the repository root.

- [ ] **Step 6: Extend ignore rules**

Add:

```gitignore
# Local C++ build products
code/cpp/build/*
!code/cpp/build/.gitkeep

# Local agent handoffs and private environment details
documents/handoffs/*
!documents/handoffs/.gitkeep
documents/environment/private/
```

- [ ] **Step 7: Review the uncommitted skeleton**

Run:

```bash
git diff --check
git status --short
```

Expected: the layout test remains RED only because root project Markdown has not moved. Do not commit this intermediate broken state; continue directly to Task 3, which moves the documents and makes the test GREEN.

---

### Task 3: Reclassify project documents

**Files:**
- Move: `PROJECT_SUMMARY.md` → `documents/project/PROJECT_SUMMARY.md`
- Move: `PROJECT_WORKFLOW.md` → `documents/project/PROJECT_WORKFLOW.md`
- Move: `WORK_STATUS.md` → `documents/project/WORK_STATUS.md`
- Move: `docs/architecture_validation_report.md` → `documents/project/architecture_validation_report.md`
- Move: `docs/context_compact_2026-07-26.md` → `documents/project/context_compact_2026-07-26.md`
- Move: `docs/workflow_summary_2026-07-26.md` → `documents/project/workflow_summary_2026-07-26.md`
- Move: `docs/项目纠错.md` → `documents/corrections/项目纠错.md`
- Move: `docs/superpowers/plans/*` → `documents/plans/`
- Move: `docs/superpowers/specs/*` → `documents/specifications/`
- Move: `docs/papers/` → `documents/research/papers/`
- Move: `docs/gamma_calibration_proposal.md` → `documents/research/gamma_calibration_proposal.md`
- Move: `docs/her_oer_comparison_critique.md` → `documents/research/her_oer_comparison_critique.md`
- Move: `docs/parameter_importance_design.md` → `documents/research/parameter_importance_design.md`
- Move: sanitized environment Markdown → `documents/environment/`

- [ ] **Step 1: Inventory tracked and untracked documents**

Run:

```bash
git ls-files '*.md' | sort
git status --short
rg -n -i '(password|passwd|token|api[_-]?key|secret|BEGIN .* PRIVATE KEY)' docs *.md
```

Expected: a complete list. Do not print secret values in reports.

- [ ] **Step 2: Separate public and private environment documents**

Public environment documents may contain versions, platform roles, and non-secret reproduction rules. Any document containing credentials or full authentication commands moves locally to:

```text
documents/environment/private/
```

This directory remains ignored. Do not stage those files.

- [ ] **Step 3: Move tracked project and correction documents with Git**

Use `git mv` for every tracked file. Keep filenames stable. No mapped destination in this task has a filename collision.

- [ ] **Step 4: Move plans and specifications**

The current implementation plan moves from:

```text
docs/superpowers/plans/2026-07-26-project-directory-reclassification.md
```

to:

```text
documents/plans/2026-07-26-project-directory-reclassification.md
```

The approved design moves to:

```text
documents/specifications/2026-07-26-project-directory-reclassification-design.md
```

- [ ] **Step 5: Move research documents**

Move:

```text
docs/gamma_calibration_proposal.md
docs/her_oer_comparison_critique.md
docs/parameter_importance_design.md
docs/papers/
```

into `documents/research/`.

Move `docs/deepseek/` into `documents/handoffs/deepseek/` locally. If those files are tracked, stage their removal from the public repository but keep the local copies in the ignored handoff directory.

- [ ] **Step 6: Update Markdown links**

Run:

```bash
rg -n 'docs/|PROJECT_SUMMARY\\.md|PROJECT_WORKFLOW\\.md|WORK_STATUS\\.md' \
  README.md documents code data results
```

Replace each old tracked path with its exact new path. Do not rewrite historical command strings inside archived evidence unless they are active instructions; provenance must retain original paths.

- [ ] **Step 7: Run document and layout checks**

Run:

```bash
.venv/bin/python -m pytest code/python/tests/test_repository_layout.py -q
git diff --check
```

Expected: root Markdown test passes after project files move.

- [ ] **Step 8: Commit the document migration**

```bash
git add README.md documents code/python/tests/test_repository_layout.py
git diff --cached --check
git diff --cached --stat
git commit -m "docs(structure): classify project documentation"
git push origin main
```

---

### Task 4: Move MATLAB and C++ code

**Files:**
- Move MATLAB files listed in the approved design
- Move: `cpp/oer_cn_solver.cpp` → `code/cpp/src/oer_cn_solver.cpp`
- Move local experimental C++ files → `code/cpp/src/experimental/`
- Modify after Python move: `code/python/src/oer_aem/cpp_bridge.py`
- Modify: `.gitignore`

- [ ] **Step 1: Move MATLAB production and test files**

Use `git mv` for tracked MATLAB files:

```text
OER_Core.m
OER_IO.m
OER_Objective.m
OER_Params.m
OER_Physics.m
OER_Signal.m
apply_alkaline_aem.m
initialize_oer_parameters.m
test_oer_model.m
```

- [ ] **Step 2: Document MATLAB entry points**

`code/matlab/README.md` must contain:

```matlab
project_root = fileparts(mfilename('fullpath'));
addpath(fullfile(project_root, 'src'));
run(fullfile(project_root, 'tests', 'test_oer_model.m'));
```

Explain that MATLAB is the reference implementation and Python is the active production path.

- [ ] **Step 3: Move C++ sources**

Use `git mv` for tracked `oer_cn_solver.cpp`. Move untracked experimental source files without staging them until they pass source review.

- [ ] **Step 4: Rebuild into the ignored build directory**

Mac command:

```bash
c++ -O3 -march=native -shared -fPIC -std=c++17 \
  -o code/cpp/build/liboercn.dylib \
  code/cpp/src/oer_cn_solver.cpp
```

Legion command:

```bash
c++ -O3 -march=native -shared -fPIC -std=c++17 \
  -o code/cpp/build/liboercn.so \
  code/cpp/src/oer_cn_solver.cpp
```

Expected: platform-native binary in ignored `code/cpp/build/`.

- [ ] **Step 5: Write a bridge-path regression test**

After the Python move, add to `code/python/tests/test_cpp_bridge.py`:

```python
from pathlib import Path

from oer_aem import cpp_bridge


def test_cpp_library_path_uses_classified_build_directory():
    path = Path(cpp_bridge.library_path())
    assert path.parent.as_posix().endswith("code/cpp/build")
```

Expose in `cpp_bridge.py`:

```python
def library_path() -> str:
    return _lib_path
```

- [ ] **Step 6: Verify and commit MATLAB/C++ movement**

Run:

```bash
git diff --check
file code/cpp/build/liboercn.dylib
git diff --cached
```

Commit only tracked source and README files:

```bash
git commit -m "refactor(structure): classify MATLAB and C++ sources"
git push origin main
```

---

### Task 5: Move the Python package, tests, and scripts

**Files:**
- Move: `python/oer_aem/` → `code/python/src/oer_aem/`
- Move: `python/tests/` → `code/python/tests/`
- Move: `python/examples/` → `code/python/examples/`
- Move: `scripts/` → `code/python/scripts/`
- Move: `python/requirements.txt` → `code/python/requirements.txt`
- Move: `python/bench_inversion.py` → `code/python/scripts/bench_inversion.py`
- Create: `code/python/scripts/project_paths.py`
- Modify: all moved scripts and tests

- [ ] **Step 1: Add a central path helper before rewriting scripts**

Create `code/python/scripts/project_paths.py`:

```python
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "code" / "python"
PYTHON_SRC = PYTHON_ROOT / "src"
WEB_BACKEND = REPO_ROOT / "code" / "web" / "backend"
RESULTS_ROOT = REPO_ROOT / "results"
DATA_ROOT = REPO_ROOT / "data"
DOCUMENTS_ROOT = REPO_ROOT / "documents"
```

Scripts must import these constants instead of independently guessing `parents[1]`.

- [ ] **Step 2: Move tracked Python files with Git**

Move directory contents because Task 2 already created destination README and test files:

```bash
git mv python/oer_aem code/python/src/oer_aem
git mv python/tests/* code/python/tests/
git mv python/examples/* code/python/examples/
git mv scripts/* code/python/scripts/
git mv python/requirements.txt code/python/requirements.txt
git mv python/bench_inversion.py code/python/scripts/bench_inversion.py
```

Remove empty old directories after confirming they contain no ignored or untracked files.

Move the untracked `_rhs_jit.py` with the package but keep it unstaged until its ownership and tests are reviewed.

- [ ] **Step 3: Update package imports**

At the top of each executable script, use:

```python
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_SRC = REPO_ROOT / "code" / "python" / "src"
sys.path.insert(0, str(PYTHON_SRC))
```

Where Web backend access is required, add:

```python
sys.path.insert(0, str(REPO_ROOT / "code" / "web" / "backend"))
```

Do not retain `ROOT / "python"` or `ROOT / "web" / "backend"`.

- [ ] **Step 4: Update the test runner**

`code/python/scripts/run_tests.py` must use:

```python
ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TESTS = ROOT / "code" / "python" / "tests"
args = sys.argv[1:] or [str(DEFAULT_TESTS), "-q"]
```

It must still prefer the repository `.venv/bin/python`.

- [ ] **Step 5: Update tests that locate scripts**

Replace old locations with:

```python
ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "code" / "python" / "scripts"
```

Update `test_project_test_runner.py`, `test_data_quality_report.py`, and `test_baseline_audit.py`. Then run:

```bash
rg -n 'parents\\[2\\].*"scripts"|/ "scripts" /|ROOT / "scripts"' code/python/tests
```

Expected: no remaining test loads scripts from the removed top-level `scripts/`.

- [ ] **Step 6: Update C++ bridge path**

In `code/python/src/oer_aem/cpp_bridge.py`, derive:

```python
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_CPP_BUILD = _PROJECT_ROOT / "code" / "cpp" / "build"
```

Choose `liboercn.dylib`, `.so`, or `.dll` from `_CPP_BUILD`.

- [ ] **Step 7: Run focused RED/GREEN checks**

Run:

```bash
.venv/bin/python -m pytest \
  code/python/tests/test_project_test_runner.py \
  code/python/tests/test_data_quality_report.py \
  code/python/tests/test_cpp_bridge.py -q
```

Expected: all pass after path updates.

- [ ] **Step 8: Run the complete Python suite**

Run:

```bash
.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q
```

Expected: 93 or more tests pass, with no collection errors. If Task 1 adds tests, the expected count increases by that exact number.

- [ ] **Step 9: Scan for active old Python paths**

Run:

```bash
rg -n 'ROOT / "python"|/python/tests|scripts/run_tests\\.py|ROOT / "scripts"' \
  code README.md documents config
```

Expected: no active instruction or executable reference to old paths. Historical provenance may remain only when clearly labeled.

- [ ] **Step 10: Commit the Python migration**

```bash
git add code/python README.md documents
git diff --cached --check
git diff --cached --stat
git commit -m "refactor(structure): move Python core into classified layout"
git push origin main
```

---

### Task 6: Move Web frontend and backend

**Files:**
- Move: `web/frontend/` → `code/web/frontend/`
- Move: `web/backend/main.py` → `code/web/backend/main.py`
- Move: `web/backend/test_*.py` → `code/web/tests/backend/`
- Move: `web/package.json` → `code/web/package.json`
- Move: `web/requirements.txt` → `code/web/requirements.txt`
- Move: `web/dev.sh` → `code/web/dev.sh`
- Modify: imports and startup paths

- [ ] **Step 1: Move tracked Web files with Git**

Keep backend tests out of the application directory by moving them to `code/web/tests/backend/`.

- [ ] **Step 2: Update backend Python path**

At the top of `code/web/backend/main.py`:

```python
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_SRC = REPO_ROOT / "code" / "python" / "src"
sys.path.insert(0, str(PYTHON_SRC))
```

- [ ] **Step 3: Update Web tests**

In each backend test:

```python
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "code" / "web" / "backend"))
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))
```

- [ ] **Step 4: Update `dev.sh`**

The script must compute its own directory and start:

```bash
uvicorn main:app --app-dir code/web/backend
npm --prefix code/web run dev
```

Do not assume the caller's current working directory.

- [ ] **Step 5: Run Web backend tests**

Run:

```bash
.venv/bin/python -m pytest code/web/tests/backend -q
```

Expected: all backend tests pass.

- [ ] **Step 6: Verify frontend build**

Run:

```bash
npm --prefix code/web run build
```

Expected: exit 0 and build output remains ignored.

- [ ] **Step 7: Commit the Web migration**

```bash
git add code/web README.md
git diff --cached --check
git commit -m "refactor(structure): classify Web frontend and backend"
git push origin main
```

---

### Task 7: Classify result evidence without changing provenance

**Files:**
- Move files listed with `evidence_level="formal"` in `results/result_classification.json`
- Move files listed with `evidence_level="smoke"` in `results/result_classification.json`
- Move files listed with `evidence_level="diagnostics"` in `results/result_classification.json`
- Modify: `results/README.md`
- Modify: active scripts that write result paths

- [ ] **Step 1: Protect the dirty feature comparison**

Before any result move, record:

```bash
git status --short results
git diff -- results/architecture_validation/feature_objective_comparison.csv
```

Copy the dirty 3-trial smoke to an ignored temporary location. Verify its SHA-256. Restore the tracked formal file only after the smoke copy is proven intact.

Expected: both the tracked formal baseline and local smoke evidence remain recoverable.

- [ ] **Step 2: Build a result classification manifest**

Create `results/result_classification.json` with entries:

```json
{
  "source": "results/architecture_validation/residual_contract.csv",
  "destination": "results/formal/architecture_validation/residual_contract.csv",
  "evidence_level": "formal",
  "reason": "manifest-backed 32-point recalculation"
}
```

Every moved result needs `source`, `destination`, `evidence_level`, and `reason`.

- [ ] **Step 3: Classify formal evidence**

Only manifest-backed, full-budget results move to `results/formal/`. Solver-equivalence formal evidence moves to:

```text
results/formal/solver_equivalence/formal-1becc12/
```

- [ ] **Step 4: Classify smoke evidence**

The preserved 3-trial feature comparison moves to:

```text
results/smoke/architecture_validation/feature_objective_comparison_3trial.csv
```

Its filename and README must state that it cannot replace the formal baseline.

- [ ] **Step 5: Classify diagnostics**

Move data quality, model gap, grid, harmonic, staged inversion, figures, and benchmark diagnostics under topic subdirectories of `results/diagnostics/`.

- [ ] **Step 6: Update output paths in scripts**

Use `RESULTS_ROOT` from `project_paths.py`. Each script must explicitly choose `formal`, `smoke`, or `diagnostics`; no script writes directly to an ambiguous `results/architecture_validation/`.

- [ ] **Step 7: Validate result references**

Run:

```bash
rg -n 'results/architecture_validation|results/model_gap|results/data_quality' \
  code README.md documents results
```

Expected: old paths remain only in historical provenance or the classification manifest.

- [ ] **Step 8: Commit the result classification**

Stage only verified evidence and path updates:

```bash
git diff --cached --check
git diff --cached --stat
git commit -m "refactor(results): separate formal smoke and diagnostics evidence"
git push origin main
```

---

### Task 8: Add Markdown-link and stale-path audits

**Files:**
- Create: `code/python/scripts/audit_repository_layout.py`
- Create: `code/python/tests/test_repository_links.py`
- Modify: `code/python/tests/test_repository_layout.py`

- [ ] **Step 1: Write the failing stale-path test**

Create:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ACTIVE_SUFFIXES = {".py", ".sh", ".json", ".toml", ".ini", ".md"}
FORBIDDEN = (
    '"python"',
    '"scripts"',
    '"web" / "backend"',
    '"cpp"',
)


def test_active_files_do_not_reference_removed_top_level_code_paths():
    hits = []
    for path in ROOT.rglob("*"):
        if path.suffix not in ACTIVE_SUFFIXES or ".git" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in FORBIDDEN:
            if token in text and "historical provenance" not in text.lower():
                hits.append(f"{path.relative_to(ROOT)}: {token}")
    assert hits == []
```

Limit this executable-path test to:

```python
SCAN_ROOTS = (
    ROOT / "code",
    ROOT / "config",
)
SCAN_FILES = (ROOT / "README.md", ROOT / "documents" / "README.md")
```

The separate Markdown-link audit scans all tracked documents. Historical command paths remain allowed because this test does not interpret archived project records as executable configuration.

- [ ] **Step 2: Implement Markdown-link audit**

`audit_repository_layout.py` must:

- scan tracked Markdown;
- resolve relative local links;
- ignore HTTP(S), anchors, and intentionally ignored private files;
- report broken links with file and line;
- return nonzero when broken links exist.

- [ ] **Step 3: Test the audit**

Create a temporary Markdown file under pytest `tmp_path`, pass one valid and one broken relative link, and assert the broken link is reported.

- [ ] **Step 4: Run audits**

```bash
.venv/bin/python code/python/scripts/audit_repository_layout.py
.venv/bin/python -m pytest \
  code/python/tests/test_repository_layout.py \
  code/python/tests/test_repository_links.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit audit tooling**

```bash
git add code/python/scripts/audit_repository_layout.py \
  code/python/tests/test_repository_layout.py \
  code/python/tests/test_repository_links.py
git diff --cached --check
git commit -m "test(structure): enforce repository layout and links"
git push origin main
```

---

### Task 9: Run full migration verification

**Files:**
- Modify: `README.md`
- Modify: subdirectory README files
- Modify: `documents/project/WORK_STATUS.md`
- Modify: `documents/corrections/项目纠错.md`

- [ ] **Step 1: Verify the final tree**

Run:

```bash
find code documents data results config -maxdepth 3 -type d | sort
find . -maxdepth 1 -type f | sort
```

Expected: only `README.md`, `.gitignore`, and necessary non-Markdown project configuration remain at root.

- [ ] **Step 2: Run Python tests**

```bash
.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q
```

Expected: no regression from the pre-migration test count.

- [ ] **Step 3: Run Web tests**

```bash
.venv/bin/python -m pytest code/web/tests/backend -q
```

Expected: all pass.

- [ ] **Step 4: Rebuild and smoke-test C++**

```bash
c++ -O3 -march=native -shared -fPIC -std=c++17 \
  -o code/cpp/build/liboercn.dylib code/cpp/src/oer_cn_solver.cpp
.venv/bin/python -m pytest \
  code/python/tests/test_cpp_bridge.py \
  code/python/tests/test_solver_equivalence.py -q
```

Expected: library loads and solver tests pass.

- [ ] **Step 5: Check MATLAB paths**

If MATLAB is installed:

```bash
matlab -batch "addpath('code/matlab/src'); run('code/matlab/tests/test_oer_model.m')"
```

If MATLAB is unavailable, run:

```bash
rg -n 'OER_(Core|IO|Objective|Params|Physics|Signal)|apply_alkaline_aem|initialize_oer_parameters' \
  code/matlab/src code/matlab/tests
test -f code/matlab/src/OER_Core.m
test -f code/matlab/tests/test_oer_model.m
```

Record: `MATLAB runtime test not run: matlab executable unavailable`. Do not report the MATLAB gate as runtime-verified.

- [ ] **Step 6: Run repository audits**

```bash
.venv/bin/python code/python/scripts/audit_repository_layout.py
git diff --check
git status --short
```

Expected:

- no broken tracked Markdown links;
- no active old top-level code paths;
- no build products staged;
- private environment and handoff files ignored;
- all unrelated user files preserved.

- [ ] **Step 7: Update README final index**

Confirm that a new user or agent can find within three minutes:

- project goal;
- current status;
- correction log;
- Python entry;
- MATLAB entry;
- C++ build;
- Web entry;
- formal results;
- file-placement rules.

- [ ] **Step 8: Update project records**

Add:

- migration commits;
- tests and unrun checks;
- known path changes for Legion;
- residual risks;
- rule that future documentation follows `documents/README.md`.

- [ ] **Step 9: Commit final migration verification**

```bash
git add README.md code documents data results config .gitignore
git diff --cached --check
git diff --cached --stat
git commit -m "docs(structure): finalize classified repository index"
git push origin main
```

---

## Final pressure-test checklist

- [ ] The active solver-equivalence evidence was synchronized before moving paths.
- [ ] No secret-bearing environment file entered Git.
- [ ] No user-owned untracked source or result was deleted.
- [ ] The dirty 3-trial CSV was preserved separately from the formal baseline.
- [ ] Git moves and content rewrites are reviewable in separate stages.
- [ ] Python, MATLAB, C++, and Web each have one documented entry.
- [ ] All active old paths were removed.
- [ ] Historical provenance retained its original command paths.
- [ ] formal, smoke, and diagnostics results are visibly distinct.
- [ ] Root README and documents README define future placement rules.
- [ ] Full tests and link audits passed before completion was claimed.
