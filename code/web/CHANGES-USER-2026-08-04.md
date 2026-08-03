# 本轮优化改动记录（2026-08-04）

对照 `2026-08-03-OER-FTAcV-desktop-app-requirements.md` 复核后所做的具体代码修改。
未改动科学计算逻辑（`oer_aem` 包），只动了工作台展示/接入层的代码。

## 已修复的问题

1. **`.csv` 解析 bug**：前端文件选择器声明支持 `.txt/.csv/.dat`，但解析函数只按
   空白符切分，逗号分隔的真 CSV 会被解析成 NaN 并被过滤掉，导致「导入成功但没有
   数据点」且没有报错。三处内联的解析逻辑（拖放、文件夹批量、下拉选择本地文件）
   已合并成一个 `parseTraceText()`，同时支持空白符/逗号/分号/Tab。

2. **路径穿越风险**：`/api/wf/task` 直接用请求里的 `commit`/`task` 拼接文件路径，
   没有像 `/api/data/analyze-by-file` 那样做 `is_relative_to` 校验，理论上可以用
   `../../` 逃出归档目录读取任意文件。已加 `_safe_archive_path()` 统一校验。

3. **写死的用户目录**：`ARCHIVE_ROOT = Path.home() / "OER-FTAcV-archive"` 在别人的
   机器上会指向别人的用户目录。改为读环境变量 `OER_ARCHIVE_ROOT`，未设置时保留
   原来的默认行为，不影响现有用法。

4. **死代码**：`SampleStep` 组件定义了完整的「样品与电极」页面，但 `App` 的导航
   只有「数据与正演」「项目结果」两步，从未渲染过这个组件（真正用的是嵌在
   `WorkStep` 里的折叠面板）。已删除，避免以后有人以为改了 `SampleStep` 就会生效。

5. **谐波质量的判定阈值不该由前端发明**：之前「严格/标准/宽松」只在浏览器 JS 里
   用两个写死的数字（0.03 / 0.003）做兜底判断，这和需求里「具体阈值由配置与科学
   侧约定」相冲突。现在前端会把 `strictness` 传给后端 `/api/data/analyze`，后端
   通过 `inspect` 检查 `analyze_ftacv_trace` 是否已支持该参数：支持就转发，不支持
   就忽略（不报错）。等科学侧函数加上 strictness 支持后，前端不用再改。
   前端兜底阈值还留着，但注释已标明「一旦后端支持就应删除」。

6. **长任务无法取消**：TPE 反演一旦点击，前端只能等待，容易造成「卡住了到底是
   还在算还是死了」的困惑。加了 `AbortController` + 取消按钮。**这只是让前端停止
   等待**——后端目前是同步阻塞调用，进程本身不会被真正打断；要做到真正可中止/
   可轮询，需要把 `/api/inversion/tpe` 改造成提交+轮询模型（见下面"未做，建议后续
   处理"）。

7. `fetch` 调用普遍没检查 `res.ok` 就直接 `res.json()`——如果后端返回 500 且不是
   JSON（比如反向代理插进来的错误页），`.json()` 会抛出一个和真实错误无关的解析
   异常。`simulate()`、`runInversion()` 已补上 `res.ok` 检查。

8. `import csv` / `import json as _json` 之前散落在文件中间，挪到文件顶部，纯风格
   清理，不影响行为。

## 没有改、但建议你知道的限制

- **前端仍然从 CDN 拉 React/ReactDOM/Babel/ECharts**（`unpkg.com` / `jsdelivr.net`）。
  当前是本机浏览器访问 localhost，能上网所以没问题；但一旦包成 Tauri 桌面应用，
  双击启动时如果机器没联网，白屏且没有明显报错。打包前必须把这几个库下载到本地
  `frontend/vendor/` 一起打进安装包。
- **strictness 是否真正生效取决于 `oer_aem.experimental.analyze_ftacv_trace`
  有没有实现对应参数**——本次没有这个函数的源码，无法直接改科学侧代码，只做了
  接口层面的转发准备。
- **取消反演只是前端体验补丁**，不是真正的任务可中止性。真正的任务模型（提交 /
  查询状态 / 取消 / 取回结果）建议按下面的建议实现。

## 追加（2026-08-04）：strictness 落入科学侧

按用户建议，把谐波质量严格度从"前端兜底阈值"改为科学侧配置：
- `oer_aem/experimental.py`：`analyze_ftacv_trace(trace, strictness=None)` 新增
  参数，映射到 `assess_harmonic_quality(min_relative_rms)`：
  strict→0.03 / standard→0.02（原默认）/ loose→0.005。
- `harmonic_quality` 增加 `strictness` 字段。
- 前端 `suggested()` 删除 0.03/0.003 兜底分支，直接使用科学侧 `fit_harmonics`；
  strictness 切换时重新调用 analyze（用户已实现的 useEffect）。
- 测试：642 passed（strictness=None 保持 standard 向后兼容）。

## 追加（2026-08-04）：提交+轮询任务模型

按架构建议，把 /api/simulate 和 /api/inversion/tpe 从"同步阻塞"改为
"提交 → 轮询 → 取回 → 取消"：

- 后端：
  - `POST /api/simulate`、`POST /api/inversion/tpe` → 提交任务，返回 `{job_id}`
  - `GET /api/jobs/{id}` → `running/done/failed/canceled`，done 附结果
  - `POST /api/jobs/{id}/cancel` → 取消（未开始真正取消，运行中标记丢弃）
  - 计算在 `ProcessPoolExecutor`（2 workers）执行，不阻塞事件循环；
    正演/反演核心抽为 `_run_simulate`/`_run_inversion`（模块级，可 pickle）。
- 前端：正演/反演改为提交 + 轮询 `/api/jobs/{id}`；正演/反演按钮旁加
  「取消」（POST /api/jobs/{id}/cancel）；反演完成后仍自动用 best_params
  提交正演更新右栏图。
- 为以后接远程 SSH（Legion）统一"提交/状态/取消/取回"语义做准备。
- 验证：TestClient submit→poll→done 通过；浏览器 console 无错误。

## 追加（2026-08-04）：远程计算接入（提交正式计算到 Legion）

工作台可提交正式计算到 Legion（经本机 oer-wf CLI，实际在 Legion systemd 执行）：

- 后端：
  - `GET /api/wf/specs`：列出可提交的 task_spec（config/oer-wf/examples）。
  - `POST /api/wf/submit`：`{spec, stage: prepare|smoke|formal}` →
    调本机 `wf prepare/smoke/run`（subprocess），返回每步 JSON 结果。
    属写操作（会在 Legion 启动计算），前端有确认提示。
- 前端：②页新增「提交正式计算」卡——选 spec + stage + 提交 + 显示结果。
- 与任务模型配合：为正式计算提供「提交/状态/取回」入口。

验证：/api/wf/specs 18 个 spec 可读；submit 链路返回 JSON。
