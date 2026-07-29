# OER-FTAcV 项目工作规则

更新日期：2026-07-29

当前状态入口：`PROJECT_SUMMARY.md`
当前行动计划：
`documents/plans/2026-07-29-vacation-and-post-experiment-roadmap.md`

当前科学边界：A1 为 `FAIL_METADATA`，A6 为 `FAIL_RECOVERY`，正式真实
数据反演仍被禁止。项目当前只进行条件模型分析、残差归因和实验信息设计。

## 1. 版本更新规则

本项目每完成一版明确更新，都需要同步到 GitHub。

当前远程仓库：

```text
origin git@github.com:Lsy04-c/FTacV-Alkaline-OER.git
branch codex/reclassify-project
```

每版更新的基本流程：

```bash
git status --short
git diff
.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q
.venv/bin/python -m pytest code/web/tests/backend -q
git add <本次实际修改文件>
git commit -m "<type(scope): summary>"
git push origin codex/reclassify-project
```

如果测试耗时过长或依赖缺失，必须在提交说明或回复中明确写出：

```text
哪些测试已运行
哪些测试未运行
未运行原因
当前风险
```

不要把无关文件、临时图、用户未确认的实验输出混入提交。

### Python 测试环境

项目依赖安装在仓库根目录的 `.venv`。不要依赖终端是否已经激活虚拟环境，也不要直接调用全局 `pytest`。统一使用：

```bash
.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q
```

`code/python/scripts/run_tests.py` 会优先选择 `.venv/bin/python`，从而保证 Codex、VS Code 和普通终端使用同一套依赖。

## 2. 建议压力测试规则

本项目是科研代码项目。对项目方向、算法、机理解释或实验设计提出建议时，必须同时做两类压力测试。

### 2.1 对建议本身的压力测试

每个建议至少回答：

1. 这个建议解决的具体问题是什么？
2. 它依赖哪些假设？
3. 哪些假设最可能不成立？
4. 如果失败，最明显的失败信号是什么？
5. 是否会破坏机理可解释性？
6. 是否会显著增加计算成本？
7. 是否能用合成数据或已有实验数据验证？

### 2.2 对用户执行路径的压力测试

每个建议还要回答：

1. 刘拾玉现在是否有数据、时间、设备或代码条件执行？
2. 是否偏离当前责任范围？
3. 是否需要老师、师兄或实验条件额外支持？
4. 是否能拆成一周内可完成的小任务？
5. 完成后能否形成可展示结果？

如果一个建议不能通过这些问题，应降级为“后续方向”，不能作为当前主线。

## 3. 科研项目的工程边界

本项目不能只追求拟合曲线。核心目标是：

```text
实验 FTacV 数据
-> 微观动力学模型
-> 参数反演
-> 敏感性判断
-> 解释反应中真正重要的因素
```

因此，任何新增功能必须至少服务以下目标之一：

- 提高模型物理正确性；
- 提高参数可辨识性；
- 降低反演计算成本；
- 改善实验数据接入和复现；
- 改善结果可视化和汇报；
- 明确排除不可识别或不可解释的参数。

不接受只提高拟合分数、但削弱机理解释的黑箱改动。

## 4. 当前最优先路线

当前优先级由 `PROJECT_SUMMARY.md` 和唯一当前计划维护：

1. 补录已知元数据，但不伪造预处理信息；
2. 用四组数据做条件模型可达性；
3. 分解 DC/H1–H3 残差和参数补偿；
4. 设计恢复实验后的最小信息矩阵；
5. 新实验通过元数据、敏感性和 A6-v2 后才进入正式反演。

Web 和现有 TPE 接口保留，但不作为当前科研主线。

## 5. 保留的开发 skill

为减少上下文负担，只保留对当前项目有直接价值的 skill：

```text
find-skills
executing-plans
systematic-debugging
test-driven-development
verification-before-completion
finishing-a-development-branch
vercel-react-best-practices
chem-ai-research
```

使用原则：

- 写新功能或修 bug：优先使用 TDD。
- 遇到失败：先做系统调试，找到根因再修。
- 完成前：必须做验证。
- 涉及前端：使用 Vercel React 习惯作为辅助。
- 涉及科研机理/化学 AI：可使用 chem-ai-research。

skill 只在任务触发时读取，不主动把所有 skill 放进上下文。
