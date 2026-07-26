# High-Current Penalty Diagnostic

Ru fixed at 30 ohm. gamma fixed at 3e-9 mol/cm2 and removed from optimizer specs.
Trials per dataset/weight: 10

Sign convention: `bias_hi = experiment - simulation`. Positive values mean the model underpredicts the high-current region.

| Dataset | high_weight | best | level | bias_lo | bias_hi | rmse_hi | G_OH | G_O | scaling |
|---------|-------------|------|-------|---------|---------|---------|------|-----|---------|
| ftacv2-ref-5hz.txt | 0.0 | 13274.6 | poor | +0.002 | -0.216 | 0.274 | 1.78 | 3.29 | 2.81 |
| ftacv2-ref-5hz.txt | 2.0 | 12826.5 | poor | +0.002 | -0.216 | 0.274 | 1.78 | 3.29 | 2.81 |
| ftacv2-ref-5hz.txt | 5.0 | 12434.5 | poor | +0.002 | -0.216 | 0.274 | 1.78 | 3.29 | 2.81 |
| ftacv2-ref-5hz.txt | 10.0 | 12088.6 | poor | +0.002 | -0.216 | 0.274 | 1.78 | 3.29 | 2.81 |
| ftacv3-ref-5Hz.txt | 0.0 | 11941.6 | poor | -0.013 | -0.075 | 0.167 | 1.11 | 2.82 | 3.24 |
| ftacv3-ref-5Hz.txt | 2.0 | 9719.6 | poor | -0.013 | -0.075 | 0.167 | 1.11 | 2.82 | 3.24 |
| ftacv3-ref-5Hz.txt | 5.0 | 8053.1 | poor | -0.013 | -0.075 | 0.167 | 1.11 | 2.82 | 3.24 |
| ftacv3-ref-5Hz.txt | 10.0 | 6757.0 | poor | -0.013 | -0.075 | 0.167 | 1.11 | 2.82 | 3.24 |
| ftacv4-ref-1hz.txt | 0.0 | 4662.7 | poor | -0.021 | +0.060 | 0.162 | 1.11 | 2.82 | 3.24 |
| ftacv4-ref-1hz.txt | 2.0 | 4451.9 | poor | -0.021 | +0.060 | 0.162 | 1.11 | 2.82 | 3.24 |
| ftacv4-ref-1hz.txt | 5.0 | 3674.7 | poor | -0.016 | +0.021 | 0.114 | 1.78 | 3.29 | 2.81 |
| ftacv4-ref-1hz.txt | 10.0 | 3096.1 | poor | -0.016 | +0.021 | 0.114 | 1.78 | 3.29 | 2.81 |
| ftacv8-ref-5Hz.txt | 0.0 | 9810.2 | poor | -0.033 | -0.054 | 0.177 | 1.11 | 2.82 | 3.24 |
| ftacv8-ref-5Hz.txt | 2.0 | 8537.6 | poor | -0.033 | -0.054 | 0.177 | 1.11 | 2.82 | 3.24 |
| ftacv8-ref-5Hz.txt | 5.0 | 7496.4 | poor | -0.033 | -0.054 | 0.177 | 1.11 | 2.82 | 3.24 |
| ftacv8-ref-5Hz.txt | 10.0 | 6628.8 | poor | -0.033 | -0.054 | 0.177 | 1.11 | 2.82 | 3.24 |

## Interpretation

- `ftacv2-ref-5hz.txt`: best |bias_hi| 0.216 at weight 0.0; improvement vs weight 0 = 0.000. high-current weighting does not materially reduce bias; likely missing physics.
- `ftacv3-ref-5Hz.txt`: best |bias_hi| 0.075 at weight 0.0; improvement vs weight 0 = 0.000. high-current weighting does not materially reduce bias; likely missing physics.
- `ftacv4-ref-1hz.txt`: best |bias_hi| 0.021 at weight 5.0; improvement vs weight 0 = 0.039. high-current weighting does not materially reduce bias; likely missing physics.
- `ftacv8-ref-5Hz.txt`: best |bias_hi| 0.054 at weight 0.0; improvement vs weight 0 = 0.000. high-current weighting does not materially reduce bias; likely missing physics.

## Next Decision

- If high-current weighting reduces `|bias_hi|` without pushing `G_OH/G_O/scaling` to bounds, revise the objective function first.
- If high-current weighting cannot reduce `|bias_hi|`, do not keep tuning weights. Move to a missing-physics test.
- Because positive `bias_hi` means experiment > simulation, a simple OH- depletion/current-limiting term would likely worsen the high-current DC residual. Check residual sign before adding OH- transport.
