# OER-FTAcV Architecture Validation and Feature Inversion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate the complete FTacV inversion chain, determine which parameters and one candidate high-potential physical term are supported by the data, and compare a complex-harmonic SNR-weighted feature objective against the current envelope objective.

**Architecture:** Keep data parsing, signal extraction, physical invariants, feature construction, and model comparison in separate modules with typed dictionaries at their boundaries. Preserve the current TPE optimizer and compare old and new objectives under identical seeds and trial budgets. Treat the existing uncommitted `gamma_eff(E)` code as an experiment that must pass a nested M0/M1 comparison before it enters the baseline model.

**Tech Stack:** Python 3, NumPy, SciPy, Optuna, pytest, FastAPI backend helpers, Matplotlib, Markdown/CSV reports, Git.

---

## File map

**Create**

- `python/oer_aem/data_contract.py`: validate and normalize experimental time, potential, and current arrays.
- `python/oer_aem/features.py`: extract complex harmonics, phase, noise floor, SNR, and weighted feature vectors.
- `python/oer_aem/identifiability.py`: finite-difference sensitivity matrix, scaled correlation, and parameter classification.
- `python/oer_aem/model_compare.py`: M0/M1 metrics, boundary checks, and complexity-penalized comparison.
- `python/tests/test_data_contract.py`: data-axis and residual-sign contracts.
- `python/tests/test_features.py`: synthetic amplitude, phase, SNR, and sampling stability tests.
- `python/tests/test_identifiability.py`: independent and coupled parameter classification tests.
- `python/tests/test_model_compare.py`: nested-model and acceptance-gate tests.
- `scripts/audit_workspace_baseline.py`: record worktree ownership, test baseline, and current artifacts.
- `scripts/run_architecture_validation.py`: execute invariant and synthetic-recovery checks.
- `scripts/compare_feature_objectives.py`: compare legacy and new objectives with identical budgets.
- `scripts/compare_reconstruction_model.py`: run M0/M1 nested model comparison.
- `results/architecture_validation/README.md`: generated-artifact contract; generated CSV/PNG files stay in this directory.
- `docs/architecture_validation_report.md`: verified findings and failed checks.

**Modify**

- `python/oer_aem/signal.py`: add a complex-harmonic extraction path without changing legacy envelope output.
- `python/oer_aem/physics.py`: isolate `gamma_eff` in a pure helper and preserve exact M0 behavior.
- `python/oer_aem/inversion.py`: add selectable feature mode and loss-component reporting.
- `python/oer_aem/defaults.py`: keep reconstruction disabled by default and remove it from default free parameters.
- `python/tests/test_physics.py`: add conservation, M0-equivalence, and time-step checks.
- `python/tests/test_inversion.py`: add feature-mode and loss-component tests.
- `scripts/residual_diagnostics.py`: use one shared residual definition on full and trimmed grids.
- `WORK_STATUS.md`: record verified results, failures, and interpretation limits.

## Task 1: Freeze the worktree baseline

**Files:**

- Create: `scripts/audit_workspace_baseline.py`
- Create: `results/architecture_validation/README.md`
- Create: `results/architecture_validation/baseline_manifest.json` (generated)
- Test: existing `python/tests`, `web/backend/test_analyze_e2e.py`

- [ ] **Step 1: Write the baseline auditor**

Create `scripts/audit_workspace_baseline.py` with this core behavior:

```python
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "architecture_validation" / "baseline_manifest.json"


def run(*args: str) -> str:
    return subprocess.run(
        args, cwd=ROOT, check=True, text=True, capture_output=True
    ).stdout.strip()


def main() -> None:
    manifest = {
        "head": run("git", "rev-parse", "HEAD"),
        "branch": run("git", "branch", "--show-current"),
        "status": run("git", "status", "--short").splitlines(),
        "tracked_diff": run("git", "diff", "--name-status").splitlines(),
        "untracked": run(
            "git", "ls-files", "--others", "--exclude-standard"
        ).splitlines(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Document generated-artifact rules**

Write `results/architecture_validation/README.md` stating that scripts may overwrite generated JSON/CSV/PNG files in this directory, while Markdown conclusions require manual review before commit.

- [ ] **Step 3: Generate and inspect the manifest**

Run:

```bash
python scripts/audit_workspace_baseline.py
python -m json.tool results/architecture_validation/baseline_manifest.json
```

Expected: valid JSON containing commit `abea7ac...`, branch `main`, and the pre-existing uncommitted files. Confirm that `python/oer_aem/defaults.py` and `python/oer_aem/physics.py` appear as pre-existing modifications.

- [ ] **Step 4: Run the fresh test baseline**

Run:

```bash
pytest python/tests -q
python -m pytest web/backend/test_analyze_e2e.py -q
```

Expected: record exact pass/fail counts. Do not repair failures in this task. Add the command, exit code, and failing test names to `baseline_manifest.json` under `test_runs`.

- [ ] **Step 5: Commit only baseline-audit files**

```bash
git add scripts/audit_workspace_baseline.py \
  results/architecture_validation/README.md \
  results/architecture_validation/baseline_manifest.json
git diff --cached --check
git commit -m "chore(validation): record architecture baseline"
git push origin main
```

Expected: one commit containing no existing model or data changes.

## Task 2: Enforce the experimental data contract

**Files:**

- Create: `python/oer_aem/data_contract.py`
- Create: `python/tests/test_data_contract.py`
- Modify: `web/backend/main.py:94`

- [ ] **Step 1: Write failing normalization tests**

Create `python/tests/test_data_contract.py`:

```python
import numpy as np
import pytest

from oer_aem.data_contract import ExperimentalTrace, normalize_trace, residual_exp_minus_sim


def test_normalize_trace_sorts_time_and_keeps_columns_aligned():
    rows = np.array([[2.0, 1.2, 20.0], [0.0, 1.0, 10.0], [1.0, 1.1, 15.0]])
    trace = normalize_trace(rows)
    assert trace.time.tolist() == [0.0, 1.0, 2.0]
    assert trace.potential.tolist() == [1.0, 1.1, 1.2]
    assert trace.current.tolist() == [10.0, 15.0, 20.0]


def test_normalize_trace_rejects_duplicate_or_nonfinite_time():
    with pytest.raises(ValueError, match="strictly increasing"):
        normalize_trace(np.array([[0.0, 1.0, 1.0], [0.0, 1.1, 2.0]]))
    with pytest.raises(ValueError, match="finite"):
        normalize_trace(np.array([[0.0, 1.0, np.nan], [1.0, 1.1, 2.0]]))


def test_residual_sign_is_experiment_minus_simulation():
    residual = residual_exp_minus_sim(np.array([3.0, 5.0]), np.array([2.0, 7.0]))
    assert residual.tolist() == [1.0, -2.0]
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
pytest python/tests/test_data_contract.py -q
```

Expected: collection error because `oer_aem.data_contract` does not exist.

- [ ] **Step 3: Implement the minimal contract**

Create `python/oer_aem/data_contract.py`:

```python
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class ExperimentalTrace:
    time: np.ndarray
    potential: np.ndarray
    current: np.ndarray


def normalize_trace(rows: np.ndarray) -> ExperimentalTrace:
    rows = np.asarray(rows, dtype=float)
    if rows.ndim != 2 or rows.shape[1] < 3:
        raise ValueError("experimental rows must have time, potential, current columns")
    if not np.all(np.isfinite(rows[:, :3])):
        raise ValueError("experimental rows must be finite")
    order = np.argsort(rows[:, 0], kind="stable")
    values = rows[order, :3]
    if np.any(np.diff(values[:, 0]) <= 0):
        raise ValueError("time must be strictly increasing")
    return ExperimentalTrace(values[:, 0], values[:, 1], values[:, 2])


def residual_exp_minus_sim(experiment, simulation) -> np.ndarray:
    experiment = np.asarray(experiment, dtype=float)
    simulation = np.asarray(simulation, dtype=float)
    if experiment.shape != simulation.shape:
        raise ValueError("experiment and simulation must have identical shapes")
    return experiment - simulation
```

- [ ] **Step 4: Route backend analysis through the contract**

In `web/backend/main.py::_analyze_ftacv_data`, replace direct column slicing with:

```python
from oer_aem.data_contract import normalize_trace

trace = normalize_trace(rows)
t = trace.time
E = trace.potential
current = trace.current
```

Preserve the existing response schema.

- [ ] **Step 5: Verify unit and backend tests**

Run:

```bash
pytest python/tests/test_data_contract.py -q
python -m pytest web/backend/test_analyze_e2e.py -q
```

Expected: all tests pass and the API response keys remain unchanged.

- [ ] **Step 6: Commit and push**

```bash
git add python/oer_aem/data_contract.py python/tests/test_data_contract.py web/backend/main.py
git diff --cached --check
git commit -m "test(data): enforce FTacV trace contract"
git push origin main
```

## Task 3: Add complex harmonics, phase, noise, and SNR

**Files:**

- Create: `python/oer_aem/features.py`
- Create: `python/tests/test_features.py`
- Modify: `python/oer_aem/signal.py:127-183`

- [ ] **Step 1: Write failing complex-signal tests**

Create `python/tests/test_features.py`:

```python
import numpy as np
import pytest

from oer_aem.features import complex_harmonic_metrics


def test_complex_harmonics_recover_amplitude_and_relative_phase():
    fs, f0, duration = 512.0, 4.0, 8.0
    t = np.arange(0.0, duration, 1.0 / fs)
    signal = 2.0 * np.cos(2*np.pi*f0*t + 0.30)
    signal += 0.5 * np.cos(2*np.pi*2*f0*t - 0.40)
    metrics = complex_harmonic_metrics(signal, fs=fs, f0=f0, n_harmonics=2)
    assert metrics["amplitude"] == pytest.approx([2.0, 0.5], rel=0.03)
    assert np.angle(np.exp(1j*(metrics["phase"][0] - 0.30))) == pytest.approx(0.0, abs=0.04)
    assert np.angle(np.exp(1j*(metrics["phase"][1] + 0.40))) == pytest.approx(0.0, abs=0.04)


def test_snr_rejects_noise_dominated_harmonic():
    rng = np.random.default_rng(7)
    fs, f0 = 512.0, 4.0
    t = np.arange(0.0, 8.0, 1.0 / fs)
    signal = np.cos(2*np.pi*f0*t) + 0.02*rng.normal(size=t.size)
    metrics = complex_harmonic_metrics(signal, fs=fs, f0=f0, n_harmonics=3)
    assert metrics["snr"][0] > 10.0
    assert metrics["snr"][2] < metrics["snr"][0]
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
pytest python/tests/test_features.py -q
```

Expected: collection error because `oer_aem.features` does not exist.

- [ ] **Step 3: Expose the complex FFT coefficients**

In `python/oer_aem/signal.py`, add:

```python
def extract_complex_harmonics(signal, fs, f0, n_harmonics=7, side_bins=4):
    values = _clean_current(signal)
    window = np.hanning(values.size)
    coherent_gain = np.mean(window)
    spectrum = np.fft.rfft(values * window)
    freqs = np.fft.rfftfreq(values.size, d=1.0 / fs)
    coeffs, noise = [], []
    for harmonic in range(1, n_harmonics + 1):
        center = int(np.argmin(np.abs(freqs - harmonic * f0)))
        coeffs.append(2.0 * spectrum[center] / (values.size * coherent_gain))
        neighborhood = np.r_[max(1, center-side_bins):center-1, center+2:center+side_bins+1]
        neighborhood = neighborhood[(neighborhood >= 0) & (neighborhood < spectrum.size)]
        noise.append(float(np.median(np.abs(spectrum[neighborhood])) * 2.0 /
                           (values.size * coherent_gain)))
    return np.asarray(coeffs, complex), np.asarray(noise, float)
```

Do not change `extract_harmonics`; it remains the legacy envelope path.

- [ ] **Step 4: Implement metrics and SNR**

Create `python/oer_aem/features.py`:

```python
import numpy as np
from .signal import extract_complex_harmonics


def complex_harmonic_metrics(signal, fs, f0, n_harmonics=7):
    coeffs, noise = extract_complex_harmonics(signal, fs, f0, n_harmonics)
    amplitude = np.abs(coeffs)
    snr = amplitude / np.maximum(noise, np.finfo(float).eps)
    return {
        "complex": coeffs,
        "amplitude": amplitude,
        "phase": np.angle(coeffs),
        "noise": noise,
        "snr": snr,
    }
```

- [ ] **Step 5: Verify amplitude, phase, and regression tests**

Run:

```bash
pytest python/tests/test_features.py python/tests/test_physics.py -q
```

Expected: new tests pass and legacy DC/envelope extraction remains green.

- [ ] **Step 6: Commit and push**

```bash
git add python/oer_aem/signal.py python/oer_aem/features.py python/tests/test_features.py
git diff --cached --check
git commit -m "feat(signal): extract complex harmonic features"
git push origin main
```

## Task 4: Verify physical invariants and isolate the M0 model

**Files:**

- Modify: `python/oer_aem/physics.py:99-200`
- Modify: `python/oer_aem/defaults.py:49-109`
- Modify: `python/tests/test_physics.py`

- [ ] **Step 1: Write failing M0 and invariant tests**

Add to `python/tests/test_physics.py`:

```python
def test_effective_gamma_is_constant_when_reconstruction_disabled():
    from oer_aem.physics import effective_gamma
    E = np.array([1.2, 1.5, 1.8])
    params = {"gamma": 3e-9, "beta_recon": 0.0}
    assert effective_gamma(E, params) == pytest.approx(np.full(3, 3e-9))


def test_effective_gamma_increases_above_reconstruction_potential():
    from oer_aem.physics import effective_gamma
    params = {"gamma": 3e-9, "beta_recon": 2.0, "E_recon": 1.55, "w_recon": 0.05}
    values = effective_gamma(np.array([1.3, 1.8]), params)
    assert values[1] > values[0]


def test_default_optimizer_does_not_free_reconstruction_parameters():
    params = initialize_oer_parameters()
    assert params["beta_recon"] == 0.0
    assert "beta_recon" not in params["optimize_params"]
    assert "E_recon" not in params["optimize_params"]
    assert "w_recon" not in params["optimize_params"]
```

- [ ] **Step 2: Run targeted tests and verify the intended failure**

Run:

```bash
pytest python/tests/test_physics.py -q
```

Expected: fail because `effective_gamma` is not public and reconstruction parameters are currently listed in `optimize_params`.

- [ ] **Step 3: Extract a pure effective-gamma helper**

In `python/oer_aem/physics.py`, add:

```python
def effective_gamma(E, params):
    gamma0 = float(params.get("gamma", params.get("gamma0", 3e-9)))
    beta = float(params.get("beta_recon", 0.0))
    if beta == 0.0:
        return np.asarray(E, dtype=float) * 0.0 + gamma0
    center = float(params.get("E_recon", 1.55))
    width = max(float(params.get("w_recon", 0.05)), 1e-6)
    x = np.clip((np.asarray(E, dtype=float) - center) / width, -60.0, 60.0)
    return gamma0 * (1.0 + beta / (1.0 + np.exp(-x)))
```

Replace the inline `gamma_eff` block in `_oer_model_rhs` with:

```python
gamma_eff = float(effective_gamma(E_app, params))
gammaF_Cdl_eff = gamma_eff * params["F"] / params["Cdl"]
```

- [ ] **Step 4: Restore conservative defaults**

In `python/oer_aem/defaults.py`, keep `beta_recon=0.0`, `E_recon=1.55`, and `w_recon=0.05` available, but remove them from `optimize_params`. Keep `gamma` as the canonical site-density field; do not create an independent `gamma0` free parameter.

- [ ] **Step 5: Add time-step convergence assertion**

Add a test that runs the same fixed simulation at `n_points=1024` and `2048`, interpolates both currents to a 200-point common grid, and requires normalized RMSE below `0.03`.

- [ ] **Step 6: Run physical and inversion regressions**

Run:

```bash
pytest python/tests/test_physics.py python/tests/test_inversion.py -q
```

Expected: all tests pass; failures from the recorded baseline must be identified separately rather than hidden.

- [ ] **Step 7: Commit and push**

```bash
git add python/oer_aem/physics.py python/oer_aem/defaults.py python/tests/test_physics.py
git diff --cached --check
git commit -m "refactor(model): isolate reconstruction experiment"
git push origin main
```

## Task 5: Add parameter identifiability diagnostics

**Files:**

- Create: `python/oer_aem/identifiability.py`
- Create: `python/tests/test_identifiability.py`
- Create: `scripts/run_architecture_validation.py`

- [ ] **Step 1: Write failing matrix-classification tests**

Create `python/tests/test_identifiability.py`:

```python
import numpy as np
from oer_aem.identifiability import classify_columns, sensitivity_correlation


def test_identifiability_flags_duplicate_columns_as_coupled():
    matrix = np.array([[1.0, 1.0, 0.0], [2.0, 2.0, 1.0], [3.0, 3.0, 0.0]])
    correlation = sensitivity_correlation(matrix)
    result = classify_columns(["a", "b", "c"], matrix, correlation)
    assert result["a"] == "coupled"
    assert result["b"] == "coupled"
    assert result["c"] == "identifiable"


def test_identifiability_flags_near_zero_column_as_unresolved():
    matrix = np.column_stack([np.ones(5), np.full(5, 1e-14)])
    result = classify_columns(["active", "silent"], matrix, sensitivity_correlation(matrix))
    assert result["silent"] == "unresolved"
```

- [ ] **Step 2: Verify tests fail**

Run:

```bash
pytest python/tests/test_identifiability.py -q
```

Expected: collection error because the module does not exist.

- [ ] **Step 3: Implement scaled correlation and classification**

Create `python/oer_aem/identifiability.py` with:

```python
import numpy as np


def sensitivity_correlation(matrix):
    matrix = np.asarray(matrix, float)
    scale = np.linalg.norm(matrix, axis=0)
    normalized = matrix / np.maximum(scale, np.finfo(float).eps)
    return normalized.T @ normalized


def classify_columns(names, matrix, correlation, norm_floor=1e-8, corr_limit=0.98):
    matrix = np.asarray(matrix, float)
    norms = np.linalg.norm(matrix, axis=0)
    labels = {}
    for idx, name in enumerate(names):
        peers = np.delete(np.abs(correlation[idx]), idx)
        if norms[idx] < norm_floor:
            labels[name] = "unresolved"
        elif peers.size and np.max(peers) >= corr_limit:
            labels[name] = "coupled"
        else:
            labels[name] = "identifiable"
    return labels
```

- [ ] **Step 4: Build the validation runner**

`scripts/run_architecture_validation.py` must use `analyze_parameter_importance`, assemble a feature-by-parameter sensitivity matrix, write:

- `results/architecture_validation/sensitivity_matrix.csv`
- `results/architecture_validation/parameter_classification.csv`
- `results/architecture_validation/synthetic_recovery.json`

Use a fixed seed and record parameter specs, perturbations, forward count, and runtime.

- [ ] **Step 5: Run tests and a smoke validation**

Run:

```bash
pytest python/tests/test_identifiability.py python/tests/test_importance.py -q
python scripts/run_architecture_validation.py --smoke
```

Expected: tests pass and all three output files parse successfully.

- [ ] **Step 6: Commit and push**

```bash
git add python/oer_aem/identifiability.py python/tests/test_identifiability.py \
  scripts/run_architecture_validation.py results/architecture_validation/
git diff --cached --check
git commit -m "feat(validation): classify identifiable parameters"
git push origin main
```

## Task 6: Unify full-grid and trimmed-grid residuals

**Files:**

- Modify: `scripts/residual_diagnostics.py`
- Modify: `python/tests/test_data_contract.py`
- Create: `results/architecture_validation/residual_contract.csv` (generated)

- [ ] **Step 1: Write the failing interpolation-sign test**

Add to `python/tests/test_data_contract.py`:

```python
def test_trimmed_residual_preserves_full_grid_sign():
    from oer_aem.data_contract import residual_on_grid
    full_e = np.array([1.0, 1.1, 1.2, 1.3])
    exp = np.array([1.0, 2.0, 4.0, 8.0])
    sim = np.array([0.5, 1.5, 3.0, 7.0])
    trimmed = np.array([1.1, 1.2])
    residual = residual_on_grid(full_e, exp, full_e, sim, trimmed)
    assert np.all(residual > 0.0)
```

- [ ] **Step 2: Verify the test fails**

Run:

```bash
pytest python/tests/test_data_contract.py::test_trimmed_residual_preserves_full_grid_sign -q
```

Expected: import error for `residual_on_grid`.

- [ ] **Step 3: Implement one interpolation path**

Add to `data_contract.py`:

```python
def residual_on_grid(exp_e, exp_i, sim_e, sim_i, common_e):
    common_e = np.asarray(common_e, float)
    exp_interp = np.interp(common_e, np.asarray(exp_e, float), np.asarray(exp_i, float))
    sim_interp = np.interp(common_e, np.asarray(sim_e, float), np.asarray(sim_i, float))
    return residual_exp_minus_sim(exp_interp, sim_interp)
```

- [ ] **Step 4: Replace local residual calculations**

In `scripts/residual_diagnostics.py`, use `residual_on_grid` for both the full experimental grid and the trimmed inversion grid. Write one CSV row per dataset and grid with `bias_lo`, `bias_mid`, `bias_hi`, and sign convention.

- [ ] **Step 5: Verify and generate the contract report**

Run:

```bash
pytest python/tests/test_data_contract.py -q
python scripts/residual_diagnostics.py --output results/architecture_validation/residual_contract.csv
```

Expected: four datasets × two grids, with the same documented `experiment - simulation` convention.

- [ ] **Step 6: Commit and push**

```bash
git add python/oer_aem/data_contract.py python/tests/test_data_contract.py \
  scripts/residual_diagnostics.py results/architecture_validation/residual_contract.csv
git diff --cached --check
git commit -m "fix(diagnostics): unify residual grid contract"
git push origin main
```

## Task 7: Add selectable legacy and complex feature objectives

**Files:**

- Modify: `python/oer_aem/inversion.py:44-504`
- Modify: `python/tests/test_inversion.py`
- Create: `scripts/compare_feature_objectives.py`

- [ ] **Step 1: Write failing loss-component tests**

Add to `python/tests/test_inversion.py`:

```python
def test_objective_reports_named_loss_components():
    config = InversionConfig(
        n_points=256, points_per_cycle=32, feature_grid_size=32,
        fit_harmonics=(1, 2, 3), feature_mode="legacy",
    )
    target = make_synthetic_target(TRUTH, config=config, noise_fraction=0.0)
    objective = InversionObjective(target, config=config)
    objective(encode_params(TRUTH))
    assert set(objective.last_components) >= {"dc", "harmonic_amplitude", "physical"}


def test_complex_feature_mode_wraps_phase_residual():
    from oer_aem.features import wrapped_phase_difference
    value = wrapped_phase_difference(np.array([np.pi - 0.1]), np.array([-np.pi + 0.1]))
    assert value[0] == pytest.approx(-0.2, abs=1e-8)
```

Move the repeated truth dictionary in the test file to a module constant `TRUTH`.

- [ ] **Step 2: Verify tests fail**

Run:

```bash
pytest python/tests/test_inversion.py -q
```

Expected: `InversionConfig` rejects `feature_mode` or required attributes are missing.

- [ ] **Step 3: Add explicit configuration**

Extend `InversionConfig`:

```python
feature_mode: str = "legacy"
phase_weight: float = 1.0
snr_floor: float = 3.0
```

Validate `feature_mode in {"legacy", "complex_snr"}` in `InversionObjective.__init__`.

- [ ] **Step 4: Add wrapped phase and bounded SNR weights**

In `features.py`:

```python
def wrapped_phase_difference(simulated, experimental):
    return np.angle(np.exp(1j * (np.asarray(simulated) - np.asarray(experimental))))


def snr_weights(snr, floor=3.0, cap=30.0):
    snr = np.asarray(snr, float)
    return np.clip((snr - floor) / max(cap - floor, 1e-12), 0.0, 1.0)
```

- [ ] **Step 5: Report loss components**

Keep legacy calculations unchanged. For `complex_snr`, add SNR-weighted amplitude and wrapped-phase residuals for selected harmonics. Store the latest unnormalized components in `objective.last_components`; return their normalized sum.

- [ ] **Step 6: Build the equal-budget comparison**

`scripts/compare_feature_objectives.py` must run:

- modes: `legacy`, `complex_snr`;
- seeds: `7`, `17`, `27`;
- identical trial count;
- identical fixed parameters and bounds;
- synthetic target plus four real datasets.

Write `results/architecture_validation/feature_objective_comparison.csv` with recovery error, total loss, component losses, boundary hits, forward count, and runtime.

- [ ] **Step 7: Verify unit and smoke comparisons**

Run:

```bash
pytest python/tests/test_features.py python/tests/test_inversion.py -q
python scripts/compare_feature_objectives.py --smoke --trials 3
```

Expected: both modes execute with identical seed/trial schedules and the CSV has no missing required fields.

- [ ] **Step 8: Commit and push**

```bash
git add python/oer_aem/features.py python/oer_aem/inversion.py \
  python/tests/test_inversion.py scripts/compare_feature_objectives.py \
  results/architecture_validation/feature_objective_comparison.csv
git diff --cached --check
git commit -m "feat(inversion): compare SNR-weighted complex features"
git push origin main
```

## Task 8: Compare M0 and the minimal M1 reconstruction model

**Files:**

- Create: `python/oer_aem/model_compare.py`
- Create: `python/tests/test_model_compare.py`
- Create: `scripts/compare_reconstruction_model.py`
- Create: `results/architecture_validation/reconstruction_model_comparison.csv` (generated)

- [ ] **Step 1: Write failing acceptance-gate tests**

Create `python/tests/test_model_compare.py`:

```python
from oer_aem.model_compare import information_criteria, reconstruction_gate


def test_information_criteria_penalize_extra_parameters():
    m0 = information_criteria(loss=100.0, n_observations=200, n_parameters=8)
    m1 = information_criteria(loss=99.9, n_observations=200, n_parameters=9)
    assert m1["bic"] > m0["bic"]


def test_reconstruction_gate_requires_three_datasets_and_stable_thermodynamics():
    rows = [
        {"improved": True, "harmonics_not_worse": True, "boundary_hit": False}
        for _ in range(3)
    ] + [{"improved": False, "harmonics_not_worse": True, "boundary_hit": False}]
    assert reconstruction_gate(rows, thermo_cv_ratio=1.05)["accepted"] is True
    assert reconstruction_gate(rows, thermo_cv_ratio=1.30)["accepted"] is False
```

- [ ] **Step 2: Verify tests fail**

Run:

```bash
pytest python/tests/test_model_compare.py -q
```

Expected: collection error because `model_compare` does not exist.

- [ ] **Step 3: Implement metrics and the explicit gate**

Create `model_compare.py` with Gaussian-residual AIC/BIC:

```python
import math


def information_criteria(loss, n_observations, n_parameters):
    scaled = max(float(loss) / int(n_observations), 1e-300)
    return {
        "aic": n_observations * math.log(scaled) + 2 * n_parameters,
        "bic": n_observations * math.log(scaled) + n_parameters * math.log(n_observations),
    }


def reconstruction_gate(rows, thermo_cv_ratio, required_datasets=3, max_cv_ratio=1.15):
    passed = sum(
        bool(r["improved"]) and bool(r["harmonics_not_worse"]) and not bool(r["boundary_hit"])
        for r in rows
    )
    accepted = passed >= required_datasets and thermo_cv_ratio <= max_cv_ratio
    return {"accepted": accepted, "datasets_passed": passed, "thermo_cv_ratio": thermo_cv_ratio}
```

- [ ] **Step 4: Implement the nested experiment**

`compare_reconstruction_model.py` must run:

- M0: `beta_recon=0`;
- M1: fit only `beta_recon`, fix `E_recon=1.55`, `w_recon=0.05`;
- identical seeds, trials, feature mode, thermodynamic bounds, and fixed experimental parameters.

Do not run M2 automatically. Write per-dataset AIC, BIC, high-potential bias, H1–H3 loss, thermodynamic parameters, and boundary hits.

- [ ] **Step 5: Run tests and smoke comparison**

Run:

```bash
pytest python/tests/test_model_compare.py python/tests/test_physics.py -q
python scripts/compare_reconstruction_model.py --smoke --trials 3
```

Expected: M0 and M1 both execute and the report states accepted/rejected from the fixed gate without causal language.

- [ ] **Step 6: Commit and push**

```bash
git add python/oer_aem/model_compare.py python/tests/test_model_compare.py \
  scripts/compare_reconstruction_model.py \
  results/architecture_validation/reconstruction_model_comparison.csv
git diff --cached --check
git commit -m "feat(model): gate reconstruction hypothesis"
git push origin main
```

## Task 9: Run the full comparison and publish the verified report

**Files:**

- Create: `docs/architecture_validation_report.md`
- Modify: `WORK_STATUS.md`
- Modify: `results/architecture_validation/README.md`

- [ ] **Step 1: Run the complete verification suite**

Run:

```bash
pytest python/tests -q
python -m pytest web/backend/test_analyze_e2e.py web/backend/test_inversion_api.py -q
python scripts/run_architecture_validation.py
python scripts/compare_feature_objectives.py --trials 50
python scripts/compare_reconstruction_model.py --trials 50
```

Expected: record exact pass/fail counts, runtimes, and generated file hashes. A failed command blocks any completion claim but does not erase the diagnostic result.

- [ ] **Step 2: Verify generated tables are complete**

Run:

```bash
python -m json.tool results/architecture_validation/synthetic_recovery.json
python - <<'PY'
import csv
from pathlib import Path
root = Path("results/architecture_validation")
for name in [
    "sensitivity_matrix.csv",
    "parameter_classification.csv",
    "residual_contract.csv",
    "feature_objective_comparison.csv",
    "reconstruction_model_comparison.csv",
]:
    rows = list(csv.DictReader((root / name).open()))
    assert rows, name
    assert all(None not in row.values() for row in rows), name
print("REPORT_TABLES_OK")
PY
```

Expected: `REPORT_TABLES_OK`.

- [ ] **Step 3: Write the evidence report**

Create `docs/architecture_validation_report.md` with these sections:

1. Baseline and tested commit.
2. Data and residual contract.
3. Signal amplitude/phase recovery error.
4. Physical invariant results.
5. Identifiable, coupled, and unresolved parameters.
6. Legacy versus complex-SNR objective.
7. M0 versus M1 result.
8. Failed checks and risks.
9. Allowed scientific claims.
10. Next single model or experiment decision.

Every quantitative claim must cite a generated CSV/JSON row or test command.

- [ ] **Step 4: Update project status**

In `WORK_STATUS.md`, add the tested commit, commands, exact results, accepted/rejected hypotheses, and remaining experimental needs. Correct the stale statement that H4–H7 are diagnostic-only for every dataset; state that H1–H3 are the common cross-dataset channels.

- [ ] **Step 5: Review scope and prose**

Run:

```bash
git diff --check
rg -n "TBD|TODO|待定|待补|已经证明|完全证明" \
  docs/architecture_validation_report.md WORK_STATUS.md
git diff --stat
```

Expected: no placeholders or unsupported proof language. Review every changed file and exclude caches, temporary figures, and unrelated pre-existing edits.

- [ ] **Step 6: Commit and push the verified report**

```bash
git add docs/architecture_validation_report.md WORK_STATUS.md \
  results/architecture_validation/
git diff --cached --check
git commit -m "docs(validation): report architecture evidence"
git push origin main
```

Expected: GitHub `main` contains the code commits and a final report tied to their tested commit hashes.
