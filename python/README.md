# OER-AEM Python 核心

本目录包含 `/Users/liushiyu/OER-FTAcV/` 中 MATLAB 核心模块的 Python 翻译，面向碱性 OER AEM（Adsorbate Evolution Mechanism）微观动力学模型与 FTacV 参数反演。

## 快速开始

```bash
cd /Users/liushiyu/OER-FTAcV/python
pip install -r requirements.txt
python examples/test_oer_model.py
pytest tests/
```

## 目录

- `oer_aem/` — 核心包（物理模型、信号处理、目标函数、IO）
- `tests/` — pytest 单元测试
- `examples/` — 复现 MATLAB 测试可视化

## 参考

- Bonke et al. (2016) JACS 138, 16095–16104.
- Snitkoff-Sol et al. (2024) Nat. Catal. 7, 139–147.
- Bergmann et al. (2015) Nat. Commun. 6, 8625.
