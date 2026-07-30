# V3 DC/H1–H3 残差归因设计

状态：已批准，待实现

日期：2026-07-30

上游正式证据：
`results/formal/conditional_reachability/v2-fbda4cf/`

## 1. 目标

在 V2 已确认四组数据均为 `NOT_REACHED_WITHIN_LIBRARY` 后，定位冻结 M0
相对 FT2、FT3、FT4、FT8 的残差结构。V3 回答“模型在哪些通道和电位区域
持续偏离实验，以及哪些已测试参数方向能改变偏差”，不执行真实参数反演。

## 2. 固定边界

- 使用现有四组 FTacV 数据和当前已登记的单位、RHE 标尺与列顺序。
- 一手仪器预处理记录、独立固定参数测量和新增实验条件留到恢复实验后；
  它们不阻断 V3，但相关归因必须标为“待实验补充”。
- 不改变 V2 的模型、参数边界、特征网格、阈值或分类。
- 正式后端只允许 LSODA，明确求解失败后可按 V2 契约回退 BDF。
- 不运行真实数据 TPE，不把任何候选称为真实参数。
- FT2、FT3、FT4、FT8 分开报告；FT4 不因频率为 1 Hz 被排除。

## 3. 方案选择

采用“冻结代表候选集合 + V2 全量标量证据”的组合方案。

未采用的方案：

- 单一最近候选：计算快，但结论依赖一个参数点，违反 V3 验收要求。
- 重新扩充大参数库：尚未定位模型缺口，额外计算不能保证改变结论。
- 机器学习代理：512 个独立参数点仅适合探索性基线，且没有可达正样本。

## 4. 输入

V3 只读取 V2 正式目录中的冻结文件：

- `task_spec.json`
- `parameter_library.csv`
- `targets.json`
- `base_results.jsonl`
- `stress_results.jsonl`
- `summary.json`
- `run_manifest.json`

V3 任务规格保存这些文件的 SHA-256。任一哈希变化立即停止。

## 5. 代表候选选择

每个数据集独立选择 12 个候选：

1. 只保留 `success=true` 的 base 候选；
2. 按 `(score, candidate_id)` 升序取前 64 个作为候选池；
3. 第一个固定为最近候选；
4. 在五维归一化参数坐标中，使用确定性 greedy maximin 依次选择其余候选；
5. 每一步最大化候选到已选集合的最小欧氏距离；距离并列时依次选择
   `score` 更小、`candidate_id` 更小者。

该规则兼顾当前最近区域和参数多样性。selection 文件保存池、选择顺序、
距离和 V2 分数，独立 validator 必须重建完全相同的结果。

## 6. 正演和残差

每组 12 个候选，共 48 个正式正演 job。每个 job：

1. 从 V2 的 `encoded_params` 重建物理参数；
2. 使用 V2 相同的实验采样匹配、128 点电位网格和 hybrid 特征；
3. 调用 `OERPhysics.solve_ode_system_detailed`；
4. 保存 solver、fallback、稳态阶段、RHS、运行时间和失败原因；
5. 提取 DC、global complex H1–H3 和 lock-in H1–H3；
6. 统一使用 `实验 - 模拟`：
   - DC：有符号归一化残差；
   - 幅值：实验幅值减模拟幅值，再除实验通道峰值；
   - 相位：`angle(exp(1j * (phase_exp - phase_sim)))`；
   - lock-in 只在 V2 冻结的共同有效掩码内评价。

不把幅值和相位合并为一个总残差。

## 7. 电位分区和汇总

沿 V2 的 128 点 `e_grid`，按点数固定分为：

- low：索引 `< ceil(0.2 * n_grid)`；
- mid：索引从 `ceil(0.2 * n_grid)` 到 `floor(0.8 * n_grid) - 1`；
- high：索引 `>= floor(0.8 * n_grid)`。

每个数据集、候选、通道和区间保存：

- signed mean；
- median；
- RMSE；
- median absolute error；
- 正残差比例。

跨 12 个候选汇总：

- 中位残差；
- 25%–75% 区间；
- 残差符号一致率；
- 最近候选值；
- 最近候选是否位于代表集合四分位区间内。

对每个通道和电位区间，以 12 个候选各自的 signed mean 判断方向。当至少
9/12 个候选同号时，记为“ensemble sign-consistent”；否则记为
“candidate-dependent”。signed mean 恰为 0 时不计入任一方向。

## 8. 参数方向证据

不新增 ODE 压力任务。使用 V2 已冻结的两类证据：

1. 全部成功 base 行：计算五个 diagnostic 参数与每个标量误差分量的
   Spearman 相关；同时报告样本数和符号，不作因果解释。
2. 全部 stress 行：按数据集、固定参数和正/负扰动比较相对 anchor 的
   指标变化；保留 anchor ID，不把相关行当成独立参数样本。

只有当方向在多个 anchor 上一致时，才能写“该固定参数方向与残差变化
一致”。其余结果写“补偿方向不稳定”。

## 9. 归因证据表

每个数据集至少生成以下五类记录：

| 类别 | V3 允许的结论 |
|---|---|
| 模型项 | 多候选、多个相关通道出现同向残差，且已测参数方向不能消除 |
| 背景项 | 只记录与低电位 DC 偏差一致的现象，不直接证明背景来源 |
| 元数据项 | 本阶段统一标为“待实验补充”，不作排除或确认 |
| 参数补偿 | V2 base/stress 证据显示某参数方向稳定降低特定残差 |
| 未解释 | 证据冲突、候选依赖或缺少独立约束 |

每条记录必须包含支持证据、替代解释、未验证条件和证据等级。禁止强制
每个残差只有一个原因。

## 10. 输出契约

正式输出目录包含：

- `v3_task_spec.json`
- `selection.json`
- `residual_curves.jsonl`
- `residual_matrix.csv`
- `parameter_associations.csv`
- `stress_directions.csv`
- `attribution_evidence.csv`
- `summary.json`
- `run_manifest.json`
- `STATUS.json`
- `acceptance.md`

写入使用临时文件加原子替换。`residual_curves.jsonl` 支持按 job 续跑；
恢复时必须校验 compute commit、输入哈希、任务规格哈希和完整 job 集合。

## 11. 独立验收

validator 不信任 runner 的汇总，必须独立完成：

- 输入文件和正式 provenance 哈希检查；
- 4 × 12 选择集合重建；
- 48 个唯一 job、四个数据集和 12 个候选覆盖；
- 数组 shape、有限值、相位范围和有效掩码检查；
- 统一残差符号抽查和全部汇总重算；
- base Spearman 与 stress 方向表重算；
- 五类证据表字段和替代解释检查；
- 每组最近候选在冻结 Legion 单线程环境下重新正演一遍。

正式 PASS 要求 48 个 job 均成功。若代表候选发生合法 LSODA→BDF 回退，
可保留，但必须在结果中显式记录。

validator rerun 必须从冻结 compute worktree 启动，并显式恢复
`OMP_NUM_THREADS=1`、`OPENBLAS_NUM_THREADS=1`、`MKL_NUM_THREADS=1`
和 `NUMEXPR_NUM_THREADS=1`。Mac 跨平台复算只作为可移植性诊断，不替代
正式 Legion 验收。

## 12. 压力测试和停止条件

- 选择规则若因不足 64 个成功候选无法执行，停止。
- 任一数据集少于 12 个成功正演，停止，不用其他数据集补足。
- V2 文件哈希、commit 或参数坐标不一致，停止。
- 实验与模拟 feature grid 不一致，停止。
- 相位未使用圆周残差，停止。
- 残差方向随候选集合大幅翻转时，结论降级为 candidate-dependent。
- 固定参数不确定度覆盖 diagnostic 参数效应时，不提出参数加密。
- 不因 V3 结果事后改变 V2 阈值或重新命名 V2 分类。

## 13. 完成标准

- 四组分别生成残差矩阵、电位分辨曲线和归因证据；
- 结论不依赖单一候选；
- 实验待补项被明确推迟但不伪装成已解决；
- 正式 validator 和四组 rerun 通过；
- 项目总览、进度和纠错同步；
- 只有验收通过的正式证据提交并推送。
