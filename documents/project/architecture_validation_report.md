# OER-FTAcV Architecture Validation Report

Date: 2026-07-26 (Phase 0 32-point recalibration)
Evaluation base commit: `3e08bdd` (residual) — recomputed feature/reconstruction on `b8b176c`
Data: four tracked FTacV traces in `data/raw/`

## 1. Baseline and tested commit

This report evaluates the validation plan in
`documents/plans/2026-07-25-architecture-validation-feature-inversion.md`.
The corrected worktree passed:

```text
python scripts/run_tests.py python/tests -q
59 passed in 44.56 s

python scripts/run_tests.py \
  web/backend/test_analyze_e2e.py web/backend/test_inversion_api.py -q
3 passed in 6.65 s, 1 third-party Starlette deprecation warning
```

The architecture, residual, feature, and M0/M1 calculations ran on the Lenovo
Legion WSL2 host with Python 3.11. The Mac handled code changes, focused and
complete tests, table validation, figures, report review, and Git operations.

## 2. Data and residual contract

`python/oer_aem/data_contract.py` defines the raw column order as
`[potential, current, time]` and the residual as:

```text
residual = experiment - simulation
```

The experiment and simulation now use the same per-channel maximum-absolute
normalization. Simulation cycle counts are derived from experimental duration
and frequency using 12 points per cycle. Each comparison records experimental
and simulated duration and scan rate and aborts above a relative scan-rate
error of `5e-4`.

`results/architecture_validation/residual_contract.csv` contains eight rows:
four datasets on both the full experimental grid and the trimmed inversion
grid. The maximum scan-rate relative error is `1.53e-5`. Corrected
high-potential normalized biases are:

| Dataset | Full-grid bias | Trimmed-grid bias |
|---|---:|---:|
| FT2 | -0.0015 | -0.0020 |
| FT3 | 0.0310 | 0.0251 |
| FT4 | 0.0362 | 0.0362 |
| FT8 | 0.0222 | 0.0149 |

These values confirm the residual direction but withdraw the earlier claim of
a large persistent high-potential model deficit. The previous `0.54–0.72`
values came from comparing normalized experimental channels against
dimensional simulated current at an incorrect scan rate.

## 3. Signal amplitude and phase recovery

`python/tests/test_features.py` tests two known cosine components. A fresh
recalculation produced relative amplitude errors of
`1.02e-7` and `8.29e-7`, and wrapped phase errors of
`6.96e-8` and `6.63e-7 rad`. Both remain well inside the test limits of
3% amplitude and 0.04 rad phase. The exact recalculated values are stored under
`measured_checks` in `results/architecture_validation/run_manifest.json`.

The signal layer also rejects requests above the Nyquist limit and assigns a
lower SNR to a noise-dominated harmonic. These checks validate global complex
FFT coefficients. They do not yet validate potential-resolved phase curves.

## 4. Physical invariant results

The physical tests passed the following checks:

- the four AEM free-energy steps sum to `4.92 eV`;
- the five coverage derivatives sum to `0.0` in the conservation test;
- the ODE solver returns finite coverage and current arrays;
- `beta_recon=0` returns the canonical fixed `gamma`;
- reconstruction parameters stay outside the default optimizer;
- the 512/1024-point output-grid refinement test gives normalized RMSE
  `0.00274`, below the `0.05` limit.

The architecture therefore recovers M0 exactly when reconstruction is
disabled and remains stable under the tested output-grid refinement.
`run_manifest.json` records the measured conservation and refinement values.

## 5. Parameter identifiability

The full runner wrote:

- `results/architecture_validation/sensitivity_matrix.csv`;
- `results/architecture_validation/parameter_classification.csv`;
- `results/architecture_validation/synthetic_recovery.json`.

The corrected matrix has 21 feature rows by 13 parameters, including 15
explicit H1–H3 rows, and 173 nonzero entries. The classification table reports
8 identifiable, 4 coupled, and 1 unresolved parameter. Because the matrix
still stores unsigned response magnitudes, this classification remains a
coarse local diagnostic rather than proof of global uniqueness.

The independent synthetic check fixes all parameters except `k0_1`, starts
`k0_1` at `10`, and uses 50 trials to recover `98.81` against a truth of
`100`. Its relative error is `1.19%`, below the declared `25%` tolerance.
Unlike the superseded run, the truth is not enqueued as the first trial. This
satisfies the limited acceptance criterion of recovering one parameter in a
designed-identifiable experiment; it does not establish joint recovery of the
full parameter vector.

## 6. Legacy versus complex-SNR objective

`results/architecture_validation/feature_objective_comparison.csv` contains
30 rows: one synthetic target plus four real datasets, two feature modes, three
seeds, and 50 trials per combination. Both modes use the same seeds, bounds,
fixed parameters, and trial counts.

| Metric | Legacy | Complex-SNR | Direction |
|---|---:|---:|---|
| Synthetic normalized recovery error, mean | 0.2513 | 0.1612 | improved |
| Synthetic recovery error, seed SD | 0.0188 | 0.0000 | lower; all complex runs stayed at one solution |
| Real-data common DC RMSE, mean | 0.0583 | 0.0389 | improved |
| Real-data common H1-H3 RMSE, mean | 0.2084 | 0.2893 | worse |
| Experimental boundary hits across 12 runs | 2 | 2 | unchanged |
| Cumulative worker time across 15 runs | 9162.5 s | 8705.2 s | comparable |

Using the median parameter across seeds for each dataset gives:

| Parameter | Legacy CV | Complex-SNR CV |
|---|---:|---:|
| `G_OH` | 0.166 | 0.058 |
| `G_O` | 0.081 | 0.030 |
| `scaling_OOH_OH` | 0.028 | 0.033 |

The new objective satisfies five of the six prespecified directional checks:
synthetic recovery error, seed dispersion, aggregate thermodynamic stability,
boundary hits, and explainable runtime improve or do not worsen. Common DC
agreement also improves as an additional metric. It fails the common H1-H3
check: mean RMSE rises by 38.8%, with the largest regression on FT2. The zero
synthetic seed dispersion comes from
all three Complex-SNR runs retaining the same solution and is therefore weak
convergence evidence. Under the written majority rule, Complex-SNR passes as a
feature candidate, but the H1-H3 regression prevents an unconditional
replacement of the legacy envelope loss. The next objective should combine
the accepted complex coefficients with an explicit common-H1-H3 safeguard.

![Feature-objective evidence](../results/architecture_validation/feature_objective_comparison.png)

## 7. M0 versus M1

`results/architecture_validation/reconstruction_model_comparison.csv`
contains 24 rows: four datasets, M0/M1, three seeds, and 50 trials per
combination. M1 adds only `beta_recon`; it fixes
`E_recon=1.55 V` and `w_recon=0.05 V`. The script did not run M2.

The corrected gate compares M0 and M1 at the same seed. A dataset requires a
majority of its three seed pairs to improve both high-potential RMSE and
demeaned shape RMSE, preserve H1-H3 within 5%, and lower BIC. It also rejects
systematic boundary solutions and requires a cross-dataset thermodynamic CV
ratio no greater than 1.15.

| Dataset | Bias improved | H1-H3 preserved | BIC supports M1 | Dataset passes |
|---|---|---|---|---|
| FT2 | no (1/3) | no (1/3) | no (1/3) | no |
| FT3 | yes (2/3) | yes (2/3) | yes (3/3) | yes |
| FT4 | yes (2/3) | no (0/3) | no (0/3) | no |
| FT8 | no (1/3) | yes (2/3) | no (1/3) | no |

M1 passed `1/4` datasets. Its thermodynamic CV ratio was `3.145`, above the
`1.15` limit. The M1 solutions did not systematically hit the same
`beta_recon` boundary, but this favorable check cannot offset the residual,
harmonic, complexity, and stability failures. The fixed gate rejects M1, so
the project does not run M2. The 24 recorded runs consumed `17577.0`
cumulative worker-seconds under parallel execution.

![Reconstruction-model evidence](../results/architecture_validation/reconstruction_model_comparison.png)

## 8. Failed checks and risks

Three limitations govern interpretation:

1. The identifiability matrix uses unsigned sensitivity magnitudes and cannot
   resolve signed parameter responses.
2. The current complex feature uses one global coefficient per harmonic.
   It does not preserve phase as a function of potential.
3. The real datasets have no repeat measurements in this comparison, so SNR
   weights use local spectral noise without a repeatability term.

The FastAPI tests also emit one Starlette deprecation warning from a
third-party compatibility shim. It does not affect current test outcomes.

## 9. Allowed scientific claims

The evidence supports these claims:

- the tested data, residual-sign, signal, and M0 numerical contracts are
  internally consistent;
- experiment and simulation scan duration and per-channel scale are matched,
  and the corrected high-potential residuals are small and mixed in sign;
- one parameter can be recovered from an independent initial value in a
  designed-identifiable synthetic experiment;
- the Complex-SNR objective passes the written majority rule but worsens the
  common experimental H1-H3 metric and therefore needs a harmonic safeguard;
- the tested one-parameter reconstruction extension fails the fixed M0/M1
  gate.

The evidence does not prove a surface-reconstruction mechanism, a unique set of
rate constants, or the absence of all high-potential missing physics.

## 10. Next decision

Keep M0 and do not add M2 or another physical parameter in the next version.
Advance Complex-SNR as the feature candidate, but retain the legacy H1-H3
envelope term as a safeguard until the experimental harmonic regression is
removed. The next single development target is a potential-resolved complex
harmonic representation with signed sensitivity columns. Pair that work with
repeat FTacV measurements so phase and SNR weights include repeatability.

## Artifact hashes

SHA-256 values for the evidence used in this report:

```text
98bd8dbe6d3d344863ad77c9386539c3c653c8e33730e2b34b5aca51968da8c1  baseline_manifest.json
eeea66e2c0d56d34ae7668bdd091a2f705204233d6fb5b1668134d5bf1dbb96e  sensitivity_matrix.csv
0dd97a8fa940405b79c7f4a46734754b95146932d56fd5ac81bee5566c2992e1  parameter_classification.csv
454792a027e9fa167011239786bee3a90eacbe349d3cd4dab78532468c488956  synthetic_recovery.json
8439e177b516d8a5f5835400f12d99c3182fe28fd91689fc4a003530cfc85fc5  residual_contract.csv
a4d938ed0fe7db3a62f8118e5645bd4202e06aeb159ea82340eb003dc443cdca  feature_objective_comparison.csv
7bd51875f905a79c430826acb09654a47a2adfb45e9811c005c30dcd7457500e  reconstruction_model_comparison.csv
7fd6eed498fae1fd4f99a7c81b6e969490a1ae93b6e6071dea88205fc3742e5d  feature_objective_comparison.png
f206884a5d9413b461004e60e34c868ca146a70e503641812c9e5fcd2005e1ba  feature_objective_comparison.svg
0f7ebd3fdf9d06f65b55147b9b76cdc4fd56f0520c84bc5ae0e7ead37ef11ea3  reconstruction_model_comparison.png
19222326735a252fdcb6579120033b3cec9a636862bf20e791e3941fb280d207  reconstruction_model_comparison.svg
```
