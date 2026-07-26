# 工作区环境与资产审计

日期：2026-07-25

## 已修复

### Python测试入口

项目依赖位于根目录`.venv`，而默认Shell使用Miniconda base。直接调用`pytest`或`python -m pytest`无法找到项目测试依赖。

项目现在统一使用：

```bash
python scripts/run_tests.py python/tests -q
```

该入口优先调用`.venv/bin/python`，不依赖VS Code、Codex或普通终端是否已经激活虚拟环境。

### 后端端到端测试

`web/backend/test_analyze_e2e.py`已从顶层执行脚本改为两个pytest测试。真实FTacV数据移动到`data/raw/ftacv4-ref-1hz.txt`，文件内容未改变。

### 可选Tafel特征

低分辨率合成配置不一定跨越Tafel测量使用的固定绝对电流阈值。反演核心现在允许目标Tafel为`None`：

- 目标不可测时跳过Tafel通道；
- 目标可测但候选正演不可测时保留失败处罚；
- FastAPI输入模型与核心使用相同的可选字段定义。

### 数据与基准结果

七组CV/FTacV原始输入已纳入`data/raw/`。原始仪器文件保留原始字节和行尾格式，不做清洗覆盖。

反演基准结果已按原字节移动到：

```text
results/benchmarks/bench_inversion_results.json
```

未来缓存和进度文件也写入`results/benchmarks/bench_artifacts/`。

## 当前验证

```text
python scripts/run_tests.py python/tests -q
→ 33 passed

python scripts/run_tests.py \
  web/backend/test_analyze_e2e.py \
  web/backend/test_inversion_api.py -q
→ 3 passed
```

后端测试仍报告一个第三方`StarletteDeprecationWarning`。该警告来自测试客户端兼容层，不影响当前断言结果；依赖升级应作为独立版本处理。

## 暂缓提交的实验资产

以下内容仍保留在本机工作区，需在架构验证任务中分别复跑后再提交：

- `python/oer_aem/defaults.py`和`physics.py`中的`gamma_eff(E)`候选模型；
- `scripts/staged_inversion.py`；
- `scripts/residual_diagnostics.py`；
- `scripts/sweep_ru.py`；
- `scripts/diagnose_high_current_penalty.py`；
- `results/model_gap/`与`results/staged_inversion/`旧输出；
- 数据质量PNG和其它展示图。

这些文件含有有价值的阶段工作，但部分报告仍使用已经修正的旧残差判断或旧参数固定逻辑。项目不会把它们当作当前已验证基线。

## 后续规则

1. 使用标准测试入口。
2. 每个模型实验单独提交。
3. 生成报告必须记录输入数据、配置、随机种子和提交哈希。
4. 原始数据保持只读，处理结果写入`results/`。
5. 候选物理项默认关闭，通过M0/M1对照后才能进入主模型。
