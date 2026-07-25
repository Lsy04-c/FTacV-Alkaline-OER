# Experimental Data Layout

本目录保存 OER-FTAcV 项目的实验数据。

## 目录

| 目录 | 用途 |
|---|---|
| `raw/` | 原始实验数据，不直接改动。 |
| `processed/` | 后续保存清洗、截取、背景扣除、谐波分析后的派生数据。 |

## 当前原始数据

| 文件 | 点数 | 初步说明 |
|---|---:|---|
| `raw/ftacv2-ref-5hz.txt` | 65535 | 5 Hz FTacV 原始数据。 |
| `raw/ftacv3-ref-5Hz.txt` | 65535 | 5 Hz FTacV 原始数据。 |
| `raw/ftacv4-ref-1hz.txt` | 65535 | 旧基准 FTacV 数据，约 1 Hz。 |
| `raw/ftacv8-ref-5Hz.txt` | 65535 | 5 Hz FTacV 原始数据。 |
| `raw/cv-ftacv2.txt` | 1426 | 与 ftacv2 相关的 CV 数据。 |
| `raw/cv2-ftacv8.txt` | 1430 | 与 ftacv8 相关的 CV 数据。 |
| `raw/cv4-ftacv3.txt` | 1829 | 与 ftacv3 相关的 CV 数据。 |

## 使用原则

- `raw/` 内文件只读使用。
- 所有背景扣除、重采样、滤波结果保存到 `processed/`。
- 每个处理结果应记录来源文件、处理参数、时间和代码版本。
- 多组数据先用于判断信号质量、重复性和参数可识别性，再用于机器学习。
