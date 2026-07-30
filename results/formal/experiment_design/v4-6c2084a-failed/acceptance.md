# V4 正式计算失败验收

## 结论

本轮 V4 不通过。正确门状态为 `FAIL_NUMERICAL`，不得发布候选协议排序。
原始工作流记录为 `FAIL_INFRA`，原因是 runner 的失败分类和聚合顺序存在
工程缺陷；该标签不改变 10 个必需正演任务未通过冻结稳态门的数值事实。

## 冻结运行

- task：`6c2084a/v4_experiment_design_lsoda`
- compute commit：`6c2084a2acfc8ea2f52956f924a9193366fbf4e6`
- 远端输出时间戳：`20260730_101301`
- 正式后端：LSODA，失败后允许 BDF
- workers：8
- 主任务：792
- 半步长任务：0

## 验收事实

- 792 个主任务全部落盘；
- 782 个任务成功，10 个任务失败；
- 72 个敏感矩阵中 71 个可构建，1 个失败；
- 失败全部集中在
  `FT8 / candidate 505 / selection rank 1 / existing_ft2`；
- baseline 在 50000 s 后的 RHS 无穷范数为
  `3.24787198706e-07`，高于冻结门 `1e-08`；
- 同一 commit、Legion 环境下独立复算 baseline 得到
  `3.24787198707e-07`，排除一次性并发故障；
- 修复后的只读聚合结果为 `FAIL_NUMERICAL`，选中协议为空。

## 工程根因

1. 稳态初始化以 `RuntimeError` 退出，V4 runner 将其误标为 `INFRA`；
2. 聚合器在处理 `success=false` 前比较空特征名，触发
   `ValueError: forward feature names do not match`；
3. 因聚合阶段崩溃，原运行没有生成完整 recommendation 和 manifest。

修复仅改变失败分类、留痕和续跑 provenance，不放宽稳态门，不删除失败点，
也不把 7/8 或 71/72 覆盖改写为正式通过。

## 原始文件 SHA-256

- `STATUS.json`：
  `e557c2da2b1351eeecf4f681e48329c74bec3a9c6f6b90b672de9b3afd552b4b`
- `condition_catalog.csv`：
  `3f5274ea4f8099ab866368ee38f209e8f4e6215353d5c73c0a8fe2a474ef982c`
- `forward_results.jsonl`：
  `b6e89c169cd24e488d762f01a1fffb12f82b39c9875850183fabdc0f10db3332`
- `task_spec.snapshot.yaml`：
  `e08209d433e16af6c16ea916e0dc27339d1a2faf9e41d2ddbf8519553ff1b1c4`
- `v4_task_spec.json`：
  `2d3f8dc9de7f0eb26abb704a24f830b8b0082ea4c937d2a39a51bcd5ef578713`

## 后续路径

先对失败参数点执行小预算稳态诊断，比较延长松弛、不同初值和电位连续化。
只有新方法在冻结 RHS 门、覆盖度守恒和多路径一致性下通过，才建立 V4.1
新计算提交并重新运行正式设计。否则保留 `FAIL_NUMERICAL`，等待实验恢复后
重新选择参数代表点或补充独立约束。
