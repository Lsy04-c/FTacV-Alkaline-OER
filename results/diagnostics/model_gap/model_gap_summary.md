# Model Gap Summary

## DC Residual Diagnostics

| Dataset | best | bias_lo | bias_mid | bias_hi | onset_offset | H1_peak_shift | H2_peak_shift | Primary Suspect |
|---------|------|---------|----------|---------|-------------|--------------|--------------|-----------------|
| ftacv2-ref-5hz.txt | 12101.9 | +0.03 | +0.05 | +0.54 | +0.000 | -0.284 | -0.378 | 高电流段偏差 → Ru/传质/气泡; H1峰位偏移(-0.284V); H2峰位偏移(-0.378V) |
| ftacv3-ref-5Hz.txt | 5631.8 | +0.01 | +0.07 | +0.66 | +0.000 | -0.053 | -0.042 | 高电流段偏差 → Ru/传质/气泡; H1峰位偏移(-0.053V); H2峰位偏移(-0.042V) |
| ftacv4-ref-1hz.txt | 3960.8 | +0.00 | +0.09 | +0.71 | +0.000 | -0.008 | -0.094 | 高电流段偏差 → Ru/传质/气泡; H2峰位偏移(-0.094V) |
| ftacv8-ref-5Hz.txt | 5424.7 | +0.00 | +0.05 | +0.64 | +0.000 | -0.048 | -0.256 | 高电流段偏差 → Ru/传质/气泡; H1峰位偏移(-0.048V); H2峰位偏移(-0.256V) |

## Summary
- 0/4 datasets: significant low-potential baseline offset → 低电位背景不是主因
- 4/4 datasets: significant high-current deviation, `bias_hi = experiment - simulation > 0`
- 0/4 datasets: onset misalignment → E0_pre/预氧化不是当前主因
- Ru sweep after true gamma fixing gives `bias_hi ≈ +0.399` for Ru=10-50 Ω → Ru is not the controlling cause

## Recommendation
跳过低电位背景模型。当前偏差集中在完整高电位区，且符号为实验高于模拟。简单 OH- depletion / current-limiting transport term would lower the simulated current and likely worsen this residual.

Stage 3 should therefore use two checks:

1. residual-sign / normalization audit: confirm the same bias definition on the full experimental grid and the trimmed inversion grid.
2. missing high-potential contribution test: evaluate a minimal high-E activation term, e.g. field-dependent active-site growth `gamma_eff(E)` or reconstruction current, before adding a full transport equation.
