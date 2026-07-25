# Result artifact policy

`results/` contains reproducible analysis outputs grouped by workflow.

- `benchmarks/`: optimizer benchmark summaries.
- `data_quality/`: experimental metadata, harmonic screening, and figures.
- `staged_inversion/`: cross-dataset parameter stability snapshots.
- `model_gap/`: residual, Ru, and high-current diagnostic snapshots.
- `figures/`: manually selected comparison figures.

The staged-inversion and model-gap files created before 2026-07-25 are
historical diagnostic snapshots. Their scripts are tracked, but the reports
must be regenerated after residual-contract and feature-objective changes
before they support new scientific claims.

Cache, progress, empty test output, and failed-download artifacts are ignored.
Every new generated report should record its input files, configuration,
random seed when applicable, and tested Git commit.
