# V2 条件可达性正式验收

## 结论

- 正式计算和同环境独立 validator：`PASS`。
- 四组数据均分类为 `NOT_REACHED_WITHIN_LIBRARY`。
- 该结论仅表示冻结的 M0、512 个 Sobol 候选和 16 个固定输入压力场景未达到
  预注册特征门；不等价于证明 M0 在连续参数空间中不可达，也不产生真实参数估计。

## 冻结条件

- compute commit：`fbda4cff248f498b29e1c054aaab2fcaab24e40f`
- TaskSpec hash：
  `sha256:1e724f82e337a2ab67bc2dc4ad9374475405ebedfec068a20eb86b9ad739dc9d`
- 后端：LSODA，失败后仅允许 BDF 回退
- 并行：8 workers；OMP、OpenBLAS、MKL、NumExpr 各 1 线程
- 任务：2048 base + 512 stress，共 2560
- 正式运行时间：7548.53 s
- provenance：`dirty=false`

## 数据集结果

| 数据集 | base 成功 | stress 成功 | 最近候选 | 最近分数 | 扩库改进 | 分类 |
|---|---:|---:|---:|---:|---:|---|
| FT2 | 501/512 | 128/128 | 289 | 15.5203 | 6.484% | NOT_REACHED_WITHIN_LIBRARY |
| FT3 | 512/512 | 128/128 | 484 | 10.4393 | 2.418% | NOT_REACHED_WITHIN_LIBRARY |
| FT4 | 511/512 | 128/128 | 249 | 5.2607 | 0% | NOT_REACHED_WITHIN_LIBRARY |
| FT8 | 512/512 | 128/128 | 226 | 6.4683 | 0% | NOT_REACHED_WITHIN_LIBRARY |

所有 base 和 stress 任务中 `passed=true` 的数量均为 0；所有固定输入压力
场景也未改变分类。

## 验收分层

1. systemd 为 `inactive/dead`、`Result=success`、退出码 0；
   `STATUS.json` 为 `SUCCESS`。
2. 九个冻结产物、CSV schema、有限值、STATUS provenance 全部通过。
3. 独立 validator 重建 2048 base 和 512 stress job 集合、payload/hash、
   评分和四组分类。
4. 在正式 Legion 环境、冻结 commit 和单线程数值变量下，四组最近候选
   LSODA `rerun-best` 全部通过；证据见 `acceptance.md`。

## 跨平台限制

在 Mac 冻结 worktree 中复算时，逐指标 `1e-8` 等值门失败，见
`acceptance.macos-frozen-env.md`。在未恢复单线程变量的 Legion 进程中也会
出现同类漂移；最大观测绝对差约 `1.36e-5`，最大相对差约 `4.07e-5`。
恢复正式单线程变量后，Legion 同环境复算精确通过。

因此本阶段把正式环境验收记为 PASS，同时把跨平台逐指标复现记为独立的
工作流可移植性问题。未修改科学阈值或事后放宽复算容差。

## 下一步

进入 V3 残差归因：按 FT2/FT3/FT4/FT8 分解 DC、H1–H3 幅值、相位和电位
位置残差，识别共同模型缺口与数据集特异偏差。V3 完成前不启动真实参数反演，
也不把最近候选解释为真实参数。
