# Gate A6 Identifiability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 生成与当前 LSODA、128 点特征网格和四种冻结目标模式一致的可识别性证据，并冻结可用于正式 TPE 的参数角色。

**Architecture:** 将“敏感度幅值”和“带符号中心差分”分为两个明确的数据契约；由带符号矩阵计算耦合方向，由幅值指标判断是否近零。先用确定性单元测试验证数学定义，再做本地 smoke，最后才在 Legion 生成正式证据。参数分类必须同时通过局部敏感度、多参数含噪合成恢复和边界稳定性，不能由单一相关阈值决定。

**Tech Stack:** Python 3.11/3.13、NumPy、SciPy LSODA、pytest、CSV/JSON provenance、Legion WSL systemd-run

---

## 文件结构

- 修改 `code/python/src/oer_aem/importance.py`：输出真实的中心差分带符号特征响应，同时保留非负重要性幅值。
- 修改 `code/python/src/oer_aem/identifiability.py`：验证矩阵有限性，计算相关性并避免把负相关错误解释为“可区分”。
- 修改 `code/python/scripts/run_architecture_validation.py`：显式接收模式、128 网格、求解器和输出目录；写完整 provenance。
- 修改 `code/python/tests/test_importance.py`：测试正负扰动方向不会在上游丢失。
- 修改 `code/python/tests/test_identifiability.py`：测试正相关、负相关、零列及非有限输入。
- 新增正式输出目录 `results/formal/identifiability/gate-a6-<commit>/`：每次运行不可覆盖旧证据。
- 修改 `documents/project/PROJECT_SUMMARY.md`、`documents/project/WORK_STATUS.md` 和 `documents/corrections/项目纠错.md`：只在正式验收后记录结论。

### Task 1：冻结数学与证据契约

- [x] 写失败测试：构造标量和向量特征，断言中心差分保留正、负方向，幅值评分仍为非负。
- [x] 运行 `python -m pytest code/python/tests/test_importance.py code/python/tests/test_identifiability.py -q`，确认新测试在旧实现上失败。
- [x] 在 `importance.py` 增加归一化中心差分：
  - log10 参数除以 `log10(plus)-log10(minus)`；
  - linear/percent 参数除以 `plus-minus`；
  - 标量输出保留符号；
  - 向量输出使用逐点响应，不再压缩为单个绝对 RMSE 后冒充方向。
- [x] 为分类矩阵定义固定行集合；不得混合“shape 向量的一行”和“peak 标量的一行”造成维数语义不一致。
- [x] 再次运行目标测试，预期全部通过。

### Task 2：修正耦合解释

- [x] 写失败测试：重复列相关为 `+1`，相反列相关为 `-1`，二者均应标为 coupled。
- [x] 将方向命名改为：
  - `same_response`：相关系数为正；
  - `opposite_response`：相关系数为负；
  - 两者都代表局部共线和不可独立识别，不能把负相关写成 distinguishable。
- [x] 对 NaN/Inf 输入直接报错，不生成看似有效的分类。
- [x] 运行 `python -m pytest code/python/tests/test_identifiability.py -q`，预期全部通过。

### Task 3：重构 A6 生成器

- [x] 给脚本增加 `--feature-mode`、`--feature-grid-size`、`--solver-backend`、`--output`、`--seed` 和 `--noise-fraction` 参数。
- [x] 默认正式配置固定为 `feature_grid_size=128`、`solver_backend=lsoda`，禁止写入旧的 `results/architecture_validation`。
- [x] 每种模式独立生成矩阵；不得把四种模式的 `total_loss` 横向排名。
- [x] manifest 写入 Git commit、dirty 状态、完整命令、Python/NumPy/SciPy/Optuna 版本、参数基线、扰动规则、物理边界、模式、网格、solver、随机种子、输入哈希和每个输出哈希。
- [x] 若工作树 dirty、ODE 失败、结果非有限、行列缺失或输出目录已存在，正式模式应失败退出。
- [x] 运行脚本 `--smoke` 到临时目录，验收 schema 和 provenance。

### Task 4：设计多参数合成恢复

- [ ] 从当前候选参数中构造至少三种真值，避免只在默认点验证。
- [ ] 每种真值至少覆盖无噪声和与实验通道估计一致的噪声；噪声强度必须写入 manifest，不能凭空指定后解释。
- [ ] 对每个候选自由参数记录相对误差、对数误差、区间覆盖、边界命中率和跨 seed 稳定性。
- [ ] 压力测试预算：先比较 20/50/100 trials 的排序与恢复稳定性；只有 50 相对 100 足够稳定时才能采用 50。
- [ ] 8 workers、每 worker 1 BLAS 线程；增加线程数前必须提供实测吞吐证据。

### Task 5：正式运行与 Gate A6 决策

- [ ] 读取 `/Users/liushiyu/gpt/本机环境配置.md`，通过既有 SSH 别名同步精确 commit。
- [ ] 使用 `systemd-run --user` 在 Legion 运行，输出到唯一 commit 目录。
- [ ] 验收所有模式、真值、噪声、seed、参数和状态均齐全且有限；区分 infrastructure FAIL 与 scientific FAIL。
- [ ] 按证据将参数标为 `fixed`、`narrow_prior`、`free` 或 `diagnostic_only`，并记录每项来源。
- [ ] 若合成恢复失败或参数持续命中边界，参数不得进入自由集合，也不得扩大边界制造 PASS。
- [ ] 更新项目状态和纠错文档，运行完整测试。
- [ ] 仅提交 A6 代码、测试、正式证据和项目文档，推送 `codex/reclassify-project`。

## 压力测试结论

- 旧 `signed_sensitivity.csv` 的上游数据是绝对距离，不含方向，必须作废。
- 旧 `synthetic_recovery.json` 是 32 点 smoke、2 trials，且自身 `recovered=false`，不能支持“k0_1 可恢复”。
- 旧 manifest 和结果来自多个 commit，不能构成单一可复现证据链。
- 单点局部相关不足以冻结参数；A6 必须加入多真值、多 seed、含噪恢复。
- 负相关不是“可区分”，而是相反方向的局部共线；旧标签存在解释错误。
- 在上述问题修复前启动四模式正式 TPE，会把结构不可识别误当成优化精度，故禁止启动。
