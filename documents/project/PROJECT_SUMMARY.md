# OER-FTAcV 项目目标与架构优先路线

更新日期：2026-07-29
项目负责人：刘拾玉
当前分支：`codex/reclassify-project`（正式版本以 `WORK_STATUS.md` 记录的
commit 和归档 snapshot 为准）

> 本文是项目目标、完成定义和后续路线的唯一总入口。
> 历史执行记录见 `WORK_STATUS.md`，阶段纠错见 `documents/corrections/项目纠错.md`，具体实施步骤见 `documents/plans/`。

---

## 1. 项目目标

### 1.1 科学目标

建立一套可验证、可复现的碱性 OER FTacV 微观动力学反演方法，将实验电流转换为具有明确可信边界的动力学与热力学信息：

```text
实验 FTacV 数据
→ 数据与采样契约
→ AEM 正演模型
→ 谐波特征
→ 参数反演
→ 可识别性与不确定度
→ 对反应控制因素的有限度解释
```

项目最终需要回答：

1. 当前数据能稳定识别哪些参数？
2. 哪些参数只能固定、给范围或报告下限？
3. 哪些谐波和电位区间提供独立信息？
4. 不同数据集的差异来自动力学、热力学，还是实验与模型偏差？
5. 结论在数值误差、随机种子和实验重复性下是否仍成立？

### 1.2 工程目标

形成一个可复用的 Python 计算核心，并在核心可信后接入 Web 工作台。系统至少支持：

- 真实 FTacV 数据导入与元数据验证；
- AEM 正演及覆盖度、电位、电流输出；
- DC、全局复数谐波和电位分辨锁相特征；
- 可选择且可追踪的目标函数；
- 参数反演、失败统计和结果复算；
- 敏感性、耦合、边界命中和不确定度报告；
- 结果、配置、代码提交和计算环境追溯。

### 1.3 当前主线

当前主线不是继续扩展机理，也不是直接追求更低拟合损失，而是：

```text
先完成底层架构
→ 冻结可信正演与特征接口
→ 再提高反演精度
→ 最后建立置信度并形成科学结论
```

正式 TPE 比较必须等待底层架构 Gate A 全部通过。

---

## 2. 完成本项目需要达成的目标

项目分为三层。每一层通过后，下一层才能成为主线。

| 层级 | 目标 | 完成定义 | 当前状态 |
|---|---|---|---|
| A | 底层架构可用 | 数据、物理、求解器、信号、特征、目标函数和证据链均有独立测试 | 进行中 |
| B | 反演精度提高 | 新方法在统一预算下优于或不劣于可信基线，并能解释增益来源 | 未开始正式评价 |
| C | 置信度验证 | 参数结论具有数值、优化和实验不确定度，结论可重复 | 未完成 |

“代码可以运行”不等于完成；“一次拟合更好”也不等于精度提高。

---

# 3. 层级 A：完成底层代码架构

## A1. 数据与采样契约

### 目标

保证每个实验文件进入模型前具有正确的列、单位、时间轴、电位轴、扫描方向、基频、采样率和扫描速率。

### 已完成

- 数据加载与基础分析：
  - `code/python/src/oer_aem/io.py`
  - `code/python/src/oer_aem/data_contract.py`
  - `code/python/scripts/analyze_data_quality.py`
- 四组数据 FT2、FT3、FT4、FT8 已完成基础质量诊断：
  - `results/diagnostics/data_quality/`
- 残差的电位网格和符号契约已统一：
  - `code/python/scripts/residual_diagnostics.py`
  - `results/formal/architecture_validation/residual_contract.csv`

### 文件总结

`data_contract.py` 负责把原始数组转换为可验证的数据结构；`residual_diagnostics.py` 检查实验与模拟是否在同一电位口径下比较。FT4 已按实测低扫描速率处理，不能仅因 1 Hz 基频排除。

### 未达成与路径规划

1. 为四个真实文件建立固定 schema 快照，检查列数、单位、时间单调性和采样字段。
2. 对裁剪、排序、插值和扫描方向分别建立回归测试。
3. 将数据文件哈希、解析参数和排除原因写入正式 manifest。
4. Gate A1：任一数据缺少关键元数据或坐标不一致时，禁止进入反演。

### 纠错与失败路径

- 若文件格式不统一：先增加显式适配器，不在分析脚本中隐式猜列。
- 若扫描速率无法从数据可靠恢复：标记 `metadata_unresolved`，不使用假定值替代。
- 若数据方向不同：保留原始顺序并显式分支，不用排序掩盖回扫。

---

## A2. 物理模型与参数系统

### 目标

建立含预氧化步骤的五步 AEM 正演模型，并证明方程、单位、参数变换和物理不变量正确。

### 已完成

- AEM 状态方程与总电流：
  - `code/python/src/oer_aem/physics.py`
- 热力学标度关系：
  - `code/python/src/oer_aem/thermodynamics.py`
- 默认参数及统一入口：
  - `code/python/src/oer_aem/defaults.py`
  - `code/python/src/oer_aem/core.py`
- 参数编码、解码和边界：
  - `code/python/src/oer_aem/inversion.py`
- M0 与最小重构 M1 已做初步对照，M1 未通过多数数据门：
  - `code/python/scripts/compare_reconstruction_model.py`
  - `results/formal/architecture_validation/reconstruction_model_comparison.csv`

### 文件总结

当前主模型为固定活性位密度的 M0。M1 只作为被拒绝的候选假设保留，不能写成已证明的表面重构机制。

### 未达成与路径规划

1. 补齐完整轨迹上的覆盖度范围与总和守恒测试。
2. 对电荷守恒、单位和关键参数单调性建立独立测试。
3. 验证关闭任何候选扩展时严格恢复 M0。
4. 建立参数来源表：实测、文献、可反演、耦合或不可识别。
5. Gate A2：所有物理不变量、参数变换和 M0 回退测试通过后，才允许新增机理。

### 纠错与失败路径

- 覆盖度越界：先定位方程或数值约束，不通过裁剪输出掩盖。
- 单调性不符：先检查单位、指数符号和参数映射，再讨论机理缺项。
- M0 无法解释结构残差：只有在数据、求解器和特征层均通过后，才允许测试一个最小新增物理项。

---

## A3. 数值求解器与后端一致性

### 目标

建立可信参考求解器和快速求解器，保证加速不改变下游科学特征。

### 已完成

- LSODA 参考路径：
  - `code/python/src/oer_aem/physics.py`
- C++ Crank–Nicolson 求解器与 Python bridge：
  - `code/cpp/src/oer_cn_solver.cpp`
  - `code/python/src/oer_aem/cpp_bridge.py`
- 显式后端选择：
  - `solver_backend=auto|cn|lsoda`
  - `code/python/src/oer_aem/inversion.py`
- CN 与 LSODA 已统一稳态初值；`cn` 失败时禁止静默回退。
- 下游特征等价性脚本：
  - `code/python/scripts/validate_solver_equivalence.py`
- 本机压力测试结果：
  - 32 points/cycle：高次谐波失败；
  - 64 points/cycle：6 样本仍有失败；
  - 128 points/cycle：6 样本通过。
- Legion 正式门已按预注册配置完成：
  - commit `1becc125311e`；
  - 24 samples、seed 17、256 cycles、128 points/cycle；
  - 正式证据：`results/formal/solver_equivalence/formal-1becc12/`；
  - Gate A3 结果：**FAIL**。
- 预注册失败路径的 256 points/cycle 独立门也已完成：
  - commit `a4581dea2d8`；
  - 168 行完整，LSODA/CN 均成功且指标有限；
  - 仍有 22 项锁相相位误差超阈值，包含低阶 H2/H3；
  - 正式证据：`results/formal/solver_equivalence/formal-a4581de-ppc256/`；
  - Gate A3 结果：**FAIL**。

### 文件总结

旧 C++ 内部稳态 Newton 会给出错误初值，造成约 18.5% 总电流
NRMSE。统一初值后，本机 6 样本测试曾通过，但 24 样本正式门未通过：
LSODA 在 sample 12、21 失败；有效样本中有 15 项锁相相位超阈值，
sample 20 的 DC NRMSE 为 2.61%，超过 1% 门。正式 CSV 因两个参考
求解失败只有 156 行，而不是预期 168 行。LSODA 初始步修复后，
256 points/cycle 的完整门不再缺行且 DC 通过，但仍有 22 项锁相相位
失败，说明主要偏差不是输出采样密度不足。因此 CN 不能进入正式搜索。

### 未达成与路径规划

1. 将 Gate A3 保持为 FAIL，正式 TPE 继续使用 LSODA。
2. sample 12、21 的 LSODA 直接失败机制已定位为高速率参数组合下自动
   初始步长路径不稳定；显式 `first_step=1e-8` 后固定 24 样本全部完成
   且无警告。更广参数空间的充分性未经验证，该修复不改变原 Gate A3 的
   FAIL。
3. 256 points/cycle 独立门已按原阈值完成并 FAIL；停止继续提高采样密度
   作为修复手段。
4. 当前底层架构冻结 LSODA 为唯一正式后端。CN 转为隔离的实验后端；
   只有重新诊断离散方程/相位传播并通过新预注册门后才能恢复。

### 纠错与失败路径

- 正式门失败：不调整阈值；128 和 256 points/cycle 均失败后，不再继续
  用提高采样密度替代算法诊断。
- 仅弱谐波相位失败：保留原始数值，按预注册 2% 可解析性规则判断，不事后改变阈值。
- 总电流或 H1–H3 失败：CN 不进入正式反演，继续使用 LSODA。
- 动态库与源码提交不一致：整次结果作废并重算。

---

## A4. 信号与谐波提取

### 目标

保证 DC、H1–H7 幅值、复数响应和相位具有统一的数学定义与应用电位参考。

### 已完成

- FFT 与锁相实现：
  - `code/python/src/oer_aem/signal.py`
  - `code/python/src/oer_aem/features.py`
- 应用电位参考相位、I/Q 约定和复数域相位插值已修复：
  - 提交 `f43e441`
- 合成信号 H1–H7 压力测试：
  - 最大幅值误差 0.29%；
  - 最大相位误差 0.0029 rad；
  - 峰位误差小于 5 mV。
- 四个真实数据集已完成无警告诊断：
  - `code/python/scripts/validate_potential_resolved_harmonics.py`
  - `results/diagnostics/potential_resolved_harmonics/harmonic_diagnostics.json`
- 四个真实数据集的正式稳定性门已通过：
  - 抗混叠 2×/4×降采样；
  - 单端 10% 记录截断；
  - 112 行完整，60 行进入信号门评价；
  - 最坏被评价幅值 NRMSE 0.411%，最坏相位 RMSE 0.0181 rad；
  - `results/formal/harmonic_stability/gate-a4-6848613/`。

### 文件总结

锁相结果现在参考实测或已知应用电位基频，不再参考数组起点。`complex`、幅值和相位约定一致，有效区剔除滤波边缘。

### 未达成与路径规划

1. 合法重采样和记录长度比较已完成，Gate A4 为 PASS。
2. 峰位漂移、相位环绕差、有效区比例和独立电位区间数已进入正式证据。
3. 下一步分离真正的 `lockin_only` 与包含全局复数特征的 `hybrid`。
4. 锁相特征可以进入 A5 正式精度比较，但不可把信号稳定性写成精度增益。

### 纠错与失败路径

- 相位随起始时间变化：回到参考相位定义，不用相位平移常数补偿。
- 峰位随滤波设置漂移：降低电位分辨率声明或放弃该数据集的局部峰位。
- H4–H7 低于噪声或可解析性门：保留诊断，不强制加入共同目标。

---

## A5. 特征、目标函数与损失分解

### 目标

建立接口清晰、量纲可解释、分量可追踪的目标函数，避免单一总损失掩盖局部失败。

### 已完成

- legacy、Complex-SNR 和当前 `lockin_only` 模式：
  - `code/python/src/oer_aem/inversion.py`
  - `code/python/scripts/compare_feature_objectives.py`
- 目标函数已区分：
  - DC；
  - 共同谐波；
  - 数据特有谐波；
  - 物理约束。
- `feature_grid_size` 与损失点数尺度已修正：
  - `code/python/scripts/compare_feature_grids.py`
  - `results/formal/architecture_validation/grid_convergence.csv`
- 固定参数库正式网格门已通过：
  - 四模式 × 64/128/256/full × 8 候选，共 128 行；
  - 128 vs full 最坏总损失误差 1.18%，共同 DC/H1–H3 均小于 0.4%；
  - 四模式损失排序 Spearman 均为 1.0；
  - 后续冻结 `feature_grid_size=128`；
  - `results/formal/feature_grid_convergence/gate-a5-grid-44a020e/`。
- 模式语义已严格拆分：
  - `legacy`；
  - `complex_snr`；
  - 真正不含全局复数项的 `lockin_only`；
  - 同时包含全局复数和锁相项的 `hybrid`。
- 锁相损失已拆成 common/dataset-specific 的 amplitude/phase 四个分量。
- 1-trial Legion smoke 为 60 行，四模式调度一致且损失字段有限：
  - `results/smoke/architecture_validation/feature_mode_separation/`。

### 文件总结

`lockin_only` 与 `hybrid` 的代码语义现在可独立归因。现有 1-trial/3-trial
smoke 只证明流程可运行，不是正式精度证据；不同模式的 `total_loss` 也
不能直接横向排名。

### 未达成与路径规划

1. 模式拆分和独立损失分量已完成。
2. 下一步补齐有效通道、权重和缺失通道原因的正式证据字段。
3. 固定参数库的 64/128/256/full-grid 特征与损失收敛已 PASS。
4. 正式反演统一使用 128 点；优化随机性比较转入层级 B，不再重复用 TPE
   证明纯数值网格。
5. Gate A5：模式可独立归因、损失口径冻结、网格收敛通过后，才能进入层级 B。

### 纠错与失败路径

- 新模式只能降低总损失但恶化 H1–H3：判定失败。
- 网格点增加导致损失机械增加：修正归一化，不比较未同构结果。
- 权重依赖候选模拟参数：视为目标漂移，禁止进入正式评价。

---

## A6. 可识别性与参数分类

### 目标

在真实反演前确定哪些参数值得自由拟合，避免优化器用参数补偿制造虚假机理解释。

### 已完成

- 敏感性矩阵、参数分类和合成恢复：
  - `code/python/src/oer_aem/identifiability.py`
  - `code/python/src/oer_aem/importance.py`
  - `results/formal/architecture_validation/sensitivity_matrix.csv`
  - `results/formal/architecture_validation/parameter_classification.csv`
  - `results/formal/architecture_validation/synthetic_recovery.json`
- 带符号中心差分和耦合方向：
  - `results/formal/architecture_validation/signed_sensitivity.csv`
  - `results/formal/architecture_validation/coupling_direction.csv`
- 单参数设计实验可恢复 `k0_1`，但多参数动力学常数仍高度耦合。

### 文件总结

现有结果支持“部分参数可恢复”，不支持“全部动力学参数均可由当前数据唯一确定”。热力学参数比动力学常数更稳定。

### 未达成与路径规划

1. 真实中心差分、模式特征拆分和共同可用通道契约已实现；commit
   `cf33eba` 的四模式正式敏感性已通过 schema、有限值、哈希和模式差异验收。
2. 八参数全自由的 36-study 预算校准已 Scientific FAIL，不再启动其
   72-study 正式恢复。
3. 当前待验证的缩减自由集为 `k0_1,k0_2,k0_3,G_OH,G_O`；
   `k0_4/scaling_OOH_OH/A/gamma` 进入固定或窄先验候选。
4. recovery runner 已支持显式自由参数子集；条件恢复中其余参数取每个
   synthetic truth 的对应值，优化器不以真值初始化。
5. 五参数预算 pilot 已 Scientific FAIL：20/50 trials 均不稳定，100 trials
   下 `k0_1` 在四模式均未被 seed 范围覆盖，不启动 72-study 正式恢复。
6. 单参数 objective profile 已完成：20 个 profile 的 truth 均为全局最小，
   但 `k0_1` 在四模式均存在宽广近简并区，从自由参数候选移除。
7. `k0_2,k0_3,G_OH,G_O` 在 hybrid/lockin-only 下进入选择性的两参数
   profile，区分剩余非线性耦合与 TPE 搜索不足。
8. A6 recovery runner 已增加严格job级断点续跑：原子检查点、稳定输入
   哈希、运行级科学指纹和损坏结果拒绝；`oer-wf 0.6.4` 可用明确时间戳恢复。
   A6默认并行度改为8 workers。本机测试、Legion首次smoke和原目录恢复均已通过。
9. 将参数正式分类为固定、窄先验、自由反演、仅范围或不可识别。
10. Gate A6：最小自由参数集通过恢复门后，正式真实数据 TPE 才能启动。
11. commit `a7bc9e4` 的三参数正式合成恢复已完成：基础设施PASS，但科学
    Gate FAIL。72/72 study成功执行，只有47/72个组—参数组合的seed范围覆盖
    真值；无噪声也只有24/36覆盖。`k0_2,k0_3,G_O`不能作为当前正式联合
    自由集，真实数据TPE继续暂停。证据位于
    `results/formal/identifiability/gate-a6-reduced-recovery-a7bc9e4/`。
12. Stage 1 CN 单参数恢复已按冻结 v1 门完成并保持 scientific FAIL。
    后续审计确认 seed 范围覆盖不是可靠精度门，已设计显式 v2：按 mode
    分层约束归一化误差、seed 极差、边界和 study 状态。
13. 现有归档的 v2 离线复核筛出共同候选 `hybrid`；这只允许进入
    Stage 2 多参数 CN 筛选，不构成联合恢复 PASS。通过后仍需 LSODA
    同配置确认。
14. Stage 2 三个两参数 `hybrid` CN 任务均 scientific FAIL，停止
    三参数扩展与 LSODA 复核。54/54 个 study 的真值 objective 都优于
    TPE 最优，说明当前首要缺口是 100-trial TPE 未找到狭窄真值盆地，
    不能直接把失败解释为结构不可识别。
15. 下一步保持 100 次 forward-evaluation 预算和 v2 恢复门不变，比较
    不使用 synthetic truth 初始化的全局—局部混合优化算法。只有新算法
    在预注册代表性基准中优于 TPE，才允许重做完整两参数恢复。

### 纠错与失败路径

- 参数持续命中边界：不继续扩边界，先判定不可识别或先验不合理。
- 两参数响应近共线：固定其中一个、重参数化或只报告组合量。
- 合成数据无法恢复：不得在真实数据中解释该参数的点估计。

---

## A7. 反演执行、证据链与复现

### 目标

保证每次反演可重跑、可中断、可验收，并能追溯到唯一代码和环境。

### 已完成

- TPE 反演核心与结果结构：
  - `code/python/src/oer_aem/inversion.py`
- 实验比较脚本与基础 manifest：
  - `code/python/scripts/compare_feature_objectives.py`
  - `code/python/scripts/build_validation_manifest.py`
  - `results/formal/architecture_validation/run_manifest.json`
- 计算环境分工已确定：
  - Mac：代码、测试、文档和 Git；
  - Legion：正式长计算。
- 本地已实现 `oer-wf 0.6.3` 的任务准备、smoke、systemd 启动、状态、
  同步、通用验收和清理流程，49 项测试通过；新增确定性的 A7 基础设施
  smoke 入口，避免用科学计算失败替代工作流验收。
- wrapper 已支持 `spec_hash` 和跨进程文件信号，能区分
  `SUCCESS`、`FAIL_NUMERICAL` 与 `FAIL_INFRA`。
- DeepSeek 计算交付协议已建立：
  - `documents/specifications/deepseek-compute-delivery-acceptance.md`
  - 强制保存冻结任务规格、原始数据、日志、环境、manifest 和文件哈希；
  - Codex 只在独立验收后接受结果和更新科学结论。

### 未达成与路径规划

1. ✅ Gate A7 已于 2026-07-27 关闭（PASS）：commit `cbbcda5`，
   全链路 doctor→prepare→smoke→run→status→sync→verify 在真实 Legion
   通过，故障注入（数值失败/缺文件/哈希冲突）均按协议正确分类和停止。
2. 将 DeepSeek 协议中的 manifest、handoff 和验收文件生成过程脚本化。

### 纠错与失败路径

- 脚本、解释器和动态库来自不同工作树：结果无效。
- smoke 输出覆盖正式基线：从版本库恢复正式结果，smoke 写入独立目录。
- 进程结束但缺少完整输出：判定失败，不按日志最后一行推断成功。

---

## A8. API 与 Web 外壳

### 目标

在计算核心稳定后，为数据分析和反演提供可操作界面；前端不得拥有独立科学逻辑。

### 已完成

- FastAPI 基础接口及反演任务接口：
  - `code/web/backend/main.py`
  - `code/web/tests/backend/test_analyze_e2e.py`
  - `code/web/tests/backend/test_inversion_api.py`
- React/Vite 基础工程：
  - `code/web/frontend/`

### 未达成与路径规划

1. 等待 A1–A7 的 schema 冻结。
2. API 只封装核心模块，不复制参数变换和特征算法。
3. 增加任务状态、取消、失败原因、结果下载和 provenance 展示。
4. 前端展示损失分解、参数边界、可识别性和置信区间。
5. Gate A8：同一输入通过 CLI 与 API 产生一致结果。

### 纠错与失败路径

- 核心 schema 未冻结：暂停 UI 扩展，避免重复返工。
- API 与 CLI 结果不同：以 Python 核心为唯一实现，删除重复逻辑。
- 界面只展示最优曲线：补充失败、边界和不确定度信息后才可用于科研汇报。

---

# 4. 层级 B：提高反演精度

层级 B 只能在 A1–A7 通过后启动。目标不是让某一次损失更低，而是在同一数据、参数边界、随机种子和计算预算下获得可重复增益。

## B1. 冻结可信基线

### 路径

1. 固定数据版本、M0 模型、LSODA 复算、自由参数集和采样设置。
2. 重算 legacy 基线，不沿用旧 12/32 点混合证据。
3. 保存每种子损失、参数、边界命中、失败数和运行时间。

### 验收

- 基线 manifest 完整；
- 所有模式共享相同预算与初值；
- smoke 与 formal 结果物理隔离。

## B2. 单变量比较特征方法

### 路径

1. 比较 `legacy` 与 `complex_snr`。
2. 比较 `legacy` 与真正的 `lockin_only`。
3. 只有独立模式提供互补信息时，才测试最小 `hybrid`。
4. 每次只改变特征定义，不同时改变网格、参数边界或优化器。

### 验收

- 合成参数恢复误差不劣于 legacy；
- 共同 H1–H3 不显著恶化；
- 边界命中和失败率不增加；
- 增益在多个种子中存在。

## B3. 优化效率

### 路径

1. CN 通过 Gate A3 后用于候选搜索。
2. 最优候选和近优候选使用 LSODA 复算。
3. 再评估 workers、pruner 和 `rtol=1e-5`；每项单独验证。
4. C++ 核心已足够时，不优先投入 Numba RHS。

### 验收

- 加速前后入选参数和下游特征保持门内一致；
- wall time 明确下降；
- 失败率不升高；
- 不用更宽容的数值误差换取表面加速。

## B4. 最小物理扩展

### 路径

只有当冻结的 M0 在多个数据集保留同方向结构残差，且该残差不能由 Ru、Cdl、采样或特征解释时，才允许测试一个新增物理项。

首选顺序：

1. 独立测量或窄先验修正；
2. 最小重构参数；
3. 传质、膜阻或气泡等候选机制；
4. LOM 等更大机理变化仅作为长期方向。

### 验收

- 改善至少出现在多数数据集；
- 复杂度惩罚后仍受支持；
- 新参数在合成数据中可识别；
- 关闭扩展严格恢复 M0。

---

# 5. 层级 C：置信度与科学结论验证

## C1. 数值置信度

### 路径

- LSODA 容差收敛；
- CN 网格收敛；
- 特征网格收敛；
- 重采样和滤波敏感性；
- Mac 与 Legion 关键结果交叉复算。

### 完成定义

数值设置变化引起的误差小于预注册科学差异阈值。

## C2. 优化置信度

### 路径

- 多随机种子；
- 多起点或重复 study；
- 近优参数集合；
- profile likelihood 或 bootstrap；
- 边界命中与参数相关性。

### 完成定义

报告参数区间和耦合，不只报告单个最优值；主要结论不依赖单个 seed。

## C3. 实验置信度

### 路径

- 获取技术重复和独立电极重复；
- 用重复性估计通道权重；
- 比较不同频率、扫描速率和交流幅值；
- 预留独立数据作为最终验证集。

### 完成定义

参数差异大于实验重复性，并能在独立数据上复现。

## C4. 机理结论等级

最终报告必须区分：

1. **实现事实**：由测试证明，例如相位约定和守恒。
2. **数值证据**：由收敛和多种子结果支持。
3. **数据支持的模型判断**：例如 M0 优于当前 M1。
4. **待实验验证的物理假设**：例如表面重构、传质或 LOM。

任何拟合改善都不能单独升级为机理证明。

---

# 6. 总体执行顺序

```text
Gate A1 数据契约
→ Gate A2 物理不变量
→ Gate A3 求解器等价
→ Gate A4 信号稳定性
→ Gate A5 特征与损失冻结
→ Gate A6 自由参数集冻结
→ Gate A7 正式计算证据链
→ 层级 B 精度比较
→ 层级 C 置信度验证
→ Gate A8 Web 交付
```

Web 可以保留基础开发，但不得先于核心 schema 成为科研主线。

---

# 7. 当前已完成内容总表

| 模块 | 当前结论 | 主要文件 | 状态 |
|---|---|---|---|
| 数据基础诊断 | 四组数据可进入进一步验证 | `results/diagnostics/data_quality/` | 部分完成 |
| AEM M0 | Python 正演链已建立 | `code/python/src/oer_aem/physics.py` | 部分完成 |
| 热力学约束 | 标度关系和参数变换已实现 | `code/python/src/oer_aem/thermodynamics.py` | 已实现 |
| LSODA | 参考求解器已建立 | `code/python/src/oer_aem/physics.py` | 已实现 |
| C++ CN | 正式等价性门 FAIL，仅作快速筛选且须 LSODA 确认 | `code/cpp/src/oer_cn_solver.cpp` | 实验后端 |
| 全局谐波 | 幅值和复数特征已实现 | `code/python/src/oer_aem/signal.py` | 已实现 |
| 电位分辨锁相 | 核心相位错误已修复 | `code/python/src/oer_aem/signal.py` | 待真实重采样 |
| 目标函数 | 多模式和分量输出已建立 | `code/python/src/oer_aem/inversion.py` | 待拆分模式 |
| 网格 | 128 点为候选 | `code/python/scripts/compare_feature_grids.py` | 待扩大验证 |
| 可识别性 | 单参数可恢复；两参数 TPE 因未找到真值盆地而 FAIL | `results/formal/identifiability/gate-a6-stage2-cn-732bf5d/acceptance.md` | 待同预算算法比较 |
| M1 重构 | 当前证据拒绝 | `code/python/scripts/compare_reconstruction_model.py` | 已形成否定结果 |
| API | 基础任务接口存在 | `code/web/backend/main.py` | 非当前主线 |
| Web | 基础前端存在 | `code/web/frontend/` | 非当前主线 |

---

# 8. 最近三个可执行里程碑

## 里程碑 1：冻结并验收 Recovery Gate v2

- 保持 v1 历史 FAIL，不静默改变旧任务；
- 对三份 Stage 1 归档完成可复现离线复核；
- 冻结共享 `hybrid` mode 和 Stage 2 配置；
- 提交并推送 v2 实现、测试和科学口径。

## 里程碑 2：同预算优化器诊断

- 在不使用 synthetic truth 初始化的前提下，建立 TPE 与至少一个
  全局—局部混合算法的 100-forward 配对基准；
- 冻结代表性 truth/noise/seed、成功门和失败退出条件；
- 显式记录 truth objective，仅用于区分搜索失败和近等价远端解；
- 新算法未明显优于 TPE时，不重跑完整 Stage 2。

## 里程碑 3：重新关闭 Gate A6

- 只有同预算算法基准通过后，才重做三组两参数 CN 恢复；
- 至少一个 CN 组合通过 v2 后，才执行同配置 LSODA 确认；
- CN 与 LSODA 科学结论不一致时，以 LSODA 为准；
- Gate A6 关闭前继续禁止三参数扩展和真实数据正式 TPE。

---

# 9. 项目级压力测试

## 风险 1：把开发进度误当成科学完成

**失败信号：** 功能已有代码，但缺少独立测试、正式结果或 manifest。
**控制：** 状态只允许“已实现、已验证、正式通过”三级，不使用模糊的“完成”。

## 风险 2：底层接口继续变化导致正式计算作废

**失败信号：** 正式结果之间混用不同采样、后端、参数或损失定义。
**控制：** A1–A7 全部关门后冻结 schema，再进入层级 B。

## 风险 3：高次谐波数值存在但实验不可解析

**失败信号：** 相位随机、相对误差爆炸、结果随重采样漂移。
**控制：** 同时检查幅值强度、噪声、相位稳定性和独立区间，不按“能提取”自动纳入拟合。

## 风险 4：更复杂模型降低损失但参数不可识别

**失败信号：** 新参数命中边界、跨种子漂移或与旧参数完全补偿。
**控制：** 新参数先过合成恢复和敏感性门，再接触真实正式评价。

## 风险 5：计算加速改变科学结论

**失败信号：** CN 与 LSODA 的 H1–H3、峰位或最优参数不一致。
**控制：** CN 只在正式等价性门通过后用于搜索，最终结果由 LSODA 复算。

## 风险 6：缺少重复实验却报告过强置信度

**失败信号：** 只用优化器重复结果代替实验重复性。
**控制：** 数值、优化和实验不确定度分开报告；没有重复数据时明确限制结论等级。

---

# 10. 文档与版本规则

1. `PROJECT_SUMMARY.md`：项目目标、完成定义和总路线。
2. `WORK_STATUS.md`：按时间记录实际完成、测试、结果和提交。
3. `documents/corrections/项目纠错.md`：记录当前项目错误、风险和修复。
4. `documents/plans/`：保存具体阶段实施计划。
5. `results/`：只保存可追溯结果；smoke 与 formal 分目录。
6. 每个验证版本运行相关测试与全量测试，更新文档后单独提交并推送。
7. 未验证建议标为“待验证”；失败结果可以提交，但必须明确标记 FAIL。

---

# 11. 项目完成定义

只有以下条件全部满足，本项目才可声明完成：

- A1–A7 底层架构全部通过；
- 至少一种反演方法在统一预算下完成正式评价；
- 最终候选参数由 LSODA 复算；
- 参数可识别性、边界和区间已报告；
- 数值、优化和实验置信度已分层验证；
- 主要结论在独立或重复数据上得到支持，或明确写出缺失验证；
- CLI/API 结果一致，正式结果具有完整 provenance；
- 文档、测试、结果和 GitHub 提交一致。
