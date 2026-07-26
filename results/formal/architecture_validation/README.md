# Architecture validation artifacts

Scripts may overwrite generated JSON, CSV, and PNG files in this directory.
Each generated file must record the tested commit, input data, configuration,
random seed when applicable, and the command that produced it.

Markdown conclusions require manual review before commit. A failed diagnostic
remains valid evidence when its command, exit status, and error output are
recorded. Generated results must not be described as confirmed findings until
the corresponding tests and report review pass.

## Current generated artifacts

| Artifact | Producer |
|---|---|
| `baseline_manifest.json` | `scripts/audit_workspace_baseline.py` |
| `sensitivity_matrix.csv` | `scripts/run_architecture_validation.py` |
| `parameter_classification.csv` | `scripts/run_architecture_validation.py` |
| `synthetic_recovery.json` | `scripts/run_architecture_validation.py` |
| `residual_contract.csv` | `scripts/residual_diagnostics.py` |
| `feature_objective_comparison.csv` | `scripts/compare_feature_objectives.py` |
| `reconstruction_model_comparison.csv` | `scripts/compare_reconstruction_model.py` |
| `feature_objective_comparison.png/.svg` | `scripts/plot_architecture_validation.py` |
| `reconstruction_model_comparison.png/.svg` | `scripts/plot_architecture_validation.py` |
| `run_manifest.json` | `scripts/build_validation_manifest.py` |

The corrected architecture, residual, and 50-trial comparison tables were
computed on the Lenovo Legion WSL2 host from the reviewed worktree based on
`c5e8f57` and copied back without manual editing. Every real-data table records
matched experimental/simulated duration and scan-rate evidence. The report
records the source revisions, commands, tests, and interpretation limits.
