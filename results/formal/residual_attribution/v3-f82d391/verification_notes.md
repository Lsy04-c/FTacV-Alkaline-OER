# V3 正式验证说明

- compute commit：`f82d3918647bc0d414af912d294b467b02f047d6`
- TaskSpec hash：`sha256:d98bd972dcdfba7d8412028dc84bde49fb2bc01a0963839f65c310218b9ea921`
- 正式输出：48/48 job 成功，FT2、FT3、FT4、FT8 各 12 个候选
- 正式科学门：冻结 Legion 工作树、单数值库线程，独立 validator
  `PASS`
- 严格复算：四组最近候选均以 LSODA 重算通过，见 `acceptance.md`

Mac 的冻结 commit 工作树重建出相同候选 ID 和顺序，但五个
`selection_min_distance` 与 Legion 相差 1 ULP（`1.11e-16`）。
当前 validator 对完整 JSON 做精确比较，因此 Mac `wf verify` 报
`selection mismatch`。该结果是验证器可移植性假阴性，不覆盖冻结
Legion PASS；项目没有调整选择规则、求解器容差或科学门槛。

实验预处理一手记录、独立固定参数约束和新增实验条件在本阶段保持
`deferred`。本目录结果不得解释为真实参数估计或机理证明。
