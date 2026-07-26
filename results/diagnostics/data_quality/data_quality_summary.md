# Data Quality Summary

Analyzed 7 files from `data/raw/`.

| File | Type | n_pts | E range | f | dE | v | H2/H1 | H3/H1 | H4/H1 | Fit H | CdlA | Tafel | Pre-ox |
|------|------|-------|---------|---|---|---|-------|-------|-------|-------|------|-------|--------|
| cv-ftacv2.txt | CV | 1400 | 0.000 – 0.700 |  |  |  |  |  |  |  |  |  |  |
| cv2-ftacv8.txt | CV | 1400 | 0.000 – 0.700 |  |  |  |  |  |  |  |  |  |  |
| cv4-ftacv3.txt | CV | 1800 | 0.000 – 0.900 |  |  |  |  |  |  |  |  |  |  |
| ftacv2-ref-5hz.txt | FTacV | 65536 | 1.124 – 1.623 | 5.00 Hz | 0.160 V | 9.74 mV/s | 0.403 | 0.189 | 0.068 | [1, 2, 3, 4, 5] | 34.5 µF | FAIL | not detected |
| ftacv3-ref-5Hz.txt | FTacV | 65536 | 0.924 – 1.923 | 5.00 Hz | 0.160 V | 19.51 mV/s | 0.251 | 0.036 | 0.008 | [1, 2, 3] | 16.9 µF | FAIL | not detected |
| ftacv4-ref-1hz.txt | FTacV | 65536 | 0.924 – 1.923 | 1.00 Hz | 0.160 V | 3.90 mV/s | 0.251 | 0.043 | 0.014 | [1, 2, 3] | 28.9 µF | 0 mV/dec | not detected |
| ftacv8-ref-5Hz.txt | FTacV | 65536 | 0.924 – 1.823 | 5.00 Hz | 0.160 V | 17.56 mV/s | 0.245 | 0.063 | 0.026 | [1, 2, 3, 4] | 30.8 µF | 0 mV/dec | not detected |

## Key Observations

- 4/4 FTacV files analyzed successfully.
- CV files: ['cv-ftacv2.txt', 'cv2-ftacv8.txt', 'cv4-ftacv3.txt']
- Common fitting harmonics across all datasets: [1, 2, 3]
- Dataset-specific optional fitting harmonics: [4, 5]
- Diagnostic-only harmonics across all datasets: [6, 7]
