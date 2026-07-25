# Handoff: Resume OER-FTAcV architecture validation

## Session Metadata

- Created: 2026-07-25 23:34:05 Asia/Shanghai
- Project: `/Users/liushiyu/OER-FTAcV`
- Branch: `main`
- Current code commit: `3e08bdd195395152bb7ed8cb62aa8673c39d4eb9`
- Calculation host: Lenovo Legion, WSL2 `Debian-Bookworm`

### Recent Commits

- `3e08bdd` — checkpoint residual evidence
- `8cf26be` — correct architecture evidence pipeline
- `c5e8f57` — compare feature modes on common metrics
- `dc2845b` — gate reconstruction hypothesis
- `f88f5ff` — compare SNR-weighted complex features

## Current State Summary

The architecture-validation code has been corrected and pushed through
`3e08bdd`. The Legion environment is usable again. A formal 32
points-per-cycle residual run on `8cf26be` completed all four optimizations but
failed while writing the CSV because the writer omitted four new configuration
columns. Commit `3e08bdd` fixes that schema mismatch and atomically checkpoints
every completed dataset. The fix passes 70 tests on both Mac and the existing
Legion calculation environment. No formal result generated before `3e08bdd`
may be treated as current evidence.

## Codebase Understanding

## Architecture Overview

The validation pipeline has five layers:

1. `web/backend/main.py` parses raw FTacV traces and determines usable
   harmonics.
2. `python/oer_aem/data_contract.py` normalizes channels and defines
   experiment-minus-simulation residuals.
3. `python/oer_aem/inversion.py` builds legacy or complex-SNR features and
   runs TPE inversion.
4. Scripts under `scripts/` generate identifiability, residual, feature, and
   nested-model evidence.
5. `scripts/build_validation_manifest.py` binds generated artifacts to the
   tested code commit and SHA-256 hashes.

Real-data simulations use 32 points per cycle and derive the number of cycles
from experimental duration. H1-H3 are the common cross-dataset channels.
FT2 additionally uses H4-H5; FT8 uses H4. H6-H7 remain diagnostic for the
tracked real data, although synthetic H1-H7 amplitude and phase recovery is
tested.

## Critical Files

| File | Purpose | Relevance |
|---|---|---|
| `scripts/residual_diagnostics.py` | Runs real-data residual inversion and writes the full/trimmed contract | Fixed in `3e08bdd`; rerun first |
| `python/tests/test_residual_diagnostics.py` | Verifies schema, checkpoint accumulation, and atomic failure behavior | Regression coverage for the lost-result bug |
| `scripts/run_architecture_validation.py` | Generates sensitivity, classification, and synthetic recovery evidence | Must be rerun on `3e08bdd` |
| `scripts/compare_feature_objectives.py` | Runs equal-budget legacy/complex-SNR comparison | Formal run requires 50 trials and 8 workers |
| `scripts/compare_reconstruction_model.py` | Runs paired M0/M1 comparison and fixed gate | Formal run requires 50 trials and 8 workers |
| `scripts/plot_architecture_validation.py` | Regenerates PNG/SVG evidence figures | Run after both comparisons |
| `scripts/build_validation_manifest.py` | Records commands, configuration, tests, commit, and artifact hashes | Run only after all formal outputs exist |
| `docs/architecture_validation_report.md` | Human-readable evidence report | Currently contains old 12-point results |
| `WORK_STATUS.md` | Project progress and accepted interpretation | Section 15 is stale until formal rerun |

## Key Patterns Discovered

- Results must be tied to a clean, exact Git commit.
- Heavy calculations run on Legion; Mac handles code, tests, plots, review,
  documentation, and Git.
- Do not infer success from process exit alone. Validate row count, schema,
  trial count, seeds, sampling configuration, scan-rate error, and hashes.
- A generated file is not current evidence until its commit and configuration
  match the code under review.
- Use atomic output replacement and intermediate checkpoints for expensive
  multi-dataset calculations.

## Work Completed

## Tasks Finished

- [x] Corrected experiment/simulation duration and scan-rate matching.
- [x] Corrected per-channel normalization and residual direction.
- [x] Split common and dataset-specific harmonic loss components.
- [x] Corrected sensitivity feature mapping and one-parameter recovery.
- [x] Corrected paired-seed M0/M1 gate.
- [x] Increased formal real-data sampling from 12 to 32 points per cycle.
- [x] Added H1-H7 synthetic sampling/record-length tests.
- [x] Added full-trajectory coverage conservation tests.
- [x] Added reproducible configuration fields to comparison outputs.
- [x] Fixed residual CSV schema and atomic per-dataset checkpoints.
- [x] Restored Legion user, Git, network, tools, and calculation environment.

## Files Modified

| File | Change | Reason |
|---|---|---|
| `scripts/residual_diagnostics.py` | Added four sampling columns, atomic replacement, and per-dataset checkpoints | Prevent late failures from erasing completed calculations |
| `python/tests/test_residual_diagnostics.py` | Added three regression tests | Reproduce the production failure and verify recovery behavior |
| `scripts/build_validation_manifest.py` | Updated fresh test counts and runtimes | Keep the final manifest consistent with current verification |

## Decisions Made

| Decision | Alternatives | Rationale |
|---|---|---|
| Use 32 points per cycle | Keep 12; use 64 or 128 | Resolves H1-H7 synthetic extraction with acceptable formal cost |
| Reuse the existing validated Legion environment | Install latest dependencies; create another environment | User requested no additional NumPy installation |
| Checkpoint after every dataset | Write only at the end | The first formal rerun lost all rows after hours of work |
| Keep old result files out of code commits | Commit code and old evidence together | Old files were generated by a different sampling configuration |

## Pending Work

## Immediate Next Steps

1. In `/home/lsy/OER-FTAcV-run-3e08bdd`, run
   `scripts/run_architecture_validation.py --trials 50` with the existing
   environment at `/home/lsy/OER-FTAcV-run-8cf26be/.venv/bin/python`.
2. Run `scripts/residual_diagnostics.py --trials 30` and verify the checkpoint
   CSV after each dataset. Final acceptance requires 8 rows and 32
   points-per-cycle in every row.
3. Run the feature and M0/M1 comparisons with 50 trials and 8 workers each.
   Do not start them until residual evidence passes.
4. Copy only expected result artifacts back to Mac, regenerate figures and
   manifest, then update the report and `WORK_STATUS.md`.
5. Run the complete final audit, commit the evidence/report, and push `main`.

## Blockers/Open Questions

- No environment blocker remains.
- Formal evidence is incomplete until every 32-point calculation finishes.
- The failed `8cf26be` residual run is diagnostic history only.
- The final feature and M0/M1 decisions may change after higher-resolution
  reruns. Preserve the fixed criteria rather than tuning them to old results.

## Deferred Items

- Potential-resolved complex phase, peak width, and peak area.
- Signed sensitivity columns.
- Repeat FTacV measurements for empirical repeatability weights.
- M2 reconstruction model; run only if M1 passes the fixed gate.

## Context for Resuming Agent

## Important Context

- Connect to Legion through the saved `legion` shell function. Do not embed
  connection details in commands, documents, or logs.
- Run all Legion Git and Python operations as Linux user `lsy`.
- Code worktree:
  `/home/lsy/OER-FTAcV-run-3e08bdd`.
- Existing calculation environment is the `.venv` directory under
  `/home/lsy/OER-FTAcV-run-8cf26be`.
- Validated environment: Python 3.11.2, NumPy 2.2.6, SciPy 1.16.3,
  Optuna 4.9.0.
- `3e08bdd` passes 70 Python tests on Mac and Legion. Mac backend tests pass
  3 tests with one third-party Starlette warning.
- The local file `docs/environment_resolved_state.md` contains sensitive
  connection material. It is untracked and must never be staged, quoted, or
  copied into another artifact.
- The local Mac result files and Section 15 of `WORK_STATUS.md` describe the
  superseded 12-point formal run. Treat them as stale until overwritten.

## Assumptions Made

- The four tracked raw data files remain unchanged; their hashes matched
  between Mac and Legion during the previous audit.
- The existing validated calculation environment remains readable by `lsy`.
- The fixed seeds and acceptance gates remain unchanged during reruns.

## Potential Gotchas

- `scripts/run_tests.py` prefers `.venv` inside the current worktree. The
  `3e08bdd` worktree intentionally has no `.venv`, so invoke the existing
  environment directly with `python -m pytest`.
- Do not use the incomplete environment that was briefly created under the
  `3e08bdd` worktree; it was removed.
- A successful GitHub SSH authentication can return a nonzero shell status.
- The old `8cf26be` calculation worktree is dirty because it contains generated
  evidence. Do not reset it.
- Do not describe ordinary goal continuations as 20-minute checks. Record the
  actual Beijing time for each scheduled inspection.
- `environment_resolved_state.md` must remain local-only until redacted.

## Environment State

## Tools and Services

- Mac repository: `/Users/liushiyu/OER-FTAcV`, branch `main`.
- Legion main repository: `/home/lsy/OER-FTAcV`, branch `main`.
- Legion calculation worktree: `/home/lsy/OER-FTAcV-run-3e08bdd`.
- SSH helper: `legion`.
- Long-task manager: `tmux`.
- Available WSL diagnostics: `ps`, `pgrep`, `rg`, `tmux`.

## Active Processes

- No formal calculation is expected to be active at handoff creation.
- Confirm with `pgrep -af` and `tmux ls` before starting a formal task.

## Environment Variables

No project-specific environment variable is required. If thread limiting is
tested later, document variable names only; never record sensitive values.

## Related Resources

- `docs/superpowers/plans/2026-07-25-architecture-validation-feature-inversion.md`
- `docs/architecture_validation_report.md`
- `docs/environment_configuration_issues.md`
- `results/architecture_validation/README.md`
- `WORK_STATUS.md`

---

Before resuming, verify the code commit, worktree status, active processes, and
calculation interpreter. Never trust stale generated evidence.
