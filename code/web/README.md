# OER 工作台 — 通用反演工作台（前端接入指南）

> 版本：2026-08-04
> 定位：**展示 + 任务编排的工作台**，不内置科学计算。计算由外部程序提供，通过约定 API 接入。
> 适用：本项目的其他 agent，或想复用此界面的其他反演/电化学项目。

---

## 1. 这是什么

一个 **通用反演工作台**：前端（React+ECharts）负责展示，计算由后端 FastAPI 调用你的程序完成。

```
前端 index.html（展示）
   │  fetch
后端 main.py（FastAPI，统一 API 契约）
   │  调用
你的计算程序（模型 / 反演 / 数据分析）
```

- **人**用图形界面操作；
- **agent** 用同一套 API 契约提交任务、读取结果。
- 界面不复制科学逻辑，只展示后端返回的数据。

## 2. 启动

```bash
cd code/web
PYTHONPATH=<你的源码路径> python -m uvicorn backend.main:app --host 0.0.0.0 --port 7100
# 浏览器打开 http://127.0.0.1:7100/
```

**环境变量**：
- `PYTHONPATH`：指向你的科学代码 src（后端 import 所需）。
- `OER_ARCHIVE_ROOT`（可选）：正式结果归档根目录，默认 `~/OER-FTAcV-archive`。
  其他项目用它指向自己的结果目录。

前端是静态单文件 `frontend/index.html`，无构建步骤；后端是 `backend/main.py`。

## 3. 前端页面结构

| 页面 | 功能 |
|------|------|
| ① 数据与正演 | 导入数据（拖放/文件夹，支持 .txt/.csv/.dat）→ 自动识别 → 谐波质量（严格度三档）→ 正演/反演（可取消）→ 图表对比 |
| ② 项目结果 | 项目结论 / 反演摘要 / 参数可识别性 / 拟合质量 / oer-wf 任务（只读） |

## 4. 后端 API 契约

所有 API 返回 JSON。核心请求/响应格式如下（以正演为例）：

```
POST /api/simulate
请求体：{ "G_OH": 1.1, "G_O": 2.7, ..., "E_start": 0.9, "E_end": 2.0, "f": 5.0, "dE": 0.16, "n_points": 16384 }
响应：  { "success": true, "i_total": [...], "tdc": [...], "E_actual": [...],
          "dc": [...], "harmonics": [[...]×7], "coverage_star": [...], ... }
```

| API | 方法 | 用途 | 关键字段 |
|-----|------|------|----------|
| `/api/data/analyze` | POST | 分析上传的数据行 | 请求 `{rows:[[E,i,t]×N], strictness?}`；响应 `meta`(f/dE/v/E窗)、`harmonic_quality`、`E_raw`/`i_raw`/`dc`/`harmonics` |
| `/api/params/defaults` | GET | 默认模型参数 | 参数名→值映射 |
| `/api/simulate` | POST | **提交正演任务** | 请求模型参数；**响应 `{job_id}`**，结果经 `/api/jobs/{id}` 轮询取回 |
| `/api/inversion/tpe` | POST | **提交反演任务** | 请求 `target`+`initial_params`+`fixed_params`+`param_bounds`+`fit_harmonics`+`n_trials`；**响应 `{job_id}`** |
| `/api/jobs/{id}` | GET | 查询任务状态 | `running / done / failed / canceled`；done 附完整结果 |
| `/api/jobs/{id}/cancel` | POST | 取消任务 | 未开始可真正取消；运行中标记 canceled（结果丢弃） |
| `/api/data/samples` | GET | 内置数据文件列表 | （可选，本机数据源） |
| `/api/results/*` | GET | 只读展示归档结果 | 各结果模块 |
| `/api/wf/tasks` `/api/wf/task` | GET | oer-wf 归档任务列表/详情（只读） | 任务状态、run 的 STATUS、结果文件、summary |

**计算任务模型**：`/api/simulate` 和 `/api/inversion/tpe` 是**提交式**接口——
返回 `job_id`，前端轮询 `/api/jobs/{id}` 取结果（长任务不阻塞 HTTP）。计算在
进程池（ProcessPoolExecutor）执行，不阻塞事件循环。为以后接远程 SSH（Legion）
统一"提交→轮询→取回→取消"语义做准备。

**strictness（谐波质量严格度）**：前端把 `strictness`（strict/standard/loose）传给
`/api/data/analyze`。科学侧 `analyze_ftacv_trace` 已支持该参数（三档阈值
strict=0.03/standard=0.02/loose=0.005 相对 H1），谐波阈值由科学侧决定。

## 5. 接入你自己的计算程序

三步：

1. **实现后端 API**：在 `backend/main.py` 里新增/修改路由，调用你的程序，返回与上面契约一致的 JSON。
   - 正演返回 `i_total`/`tdc`/`dc`/`harmonics`/`coverage_*`
   - 反演返回 `best_params`/`best_value`/`history`/`fit_quality`
   - 数据识别返回 `meta`/`harmonic_quality`/`E_raw`/`i_raw`
2. **前端调用**：前端已按契约 fetch 这些 API，字段名一致即可直接显示，无需改前端。
3. **展示**：图表自动渲染（总电流/功率谱/覆盖度/DC/各阶谐波）。

**约定**：
- 实验数据三列 `[E, i, t]`（V, A, s），由你的识别代码判定 f/dE/扫速。
- 谐波质量：后端返回 `harmonic_quality`（每阶 `relative_rms`/`fit`），前端据此建议拟合通道。
- 反演：前端传 `target`（实验 dc/harmonics/tafel）+ 参数边界，后端跑优化并返回历史。

## 6. 通用扩展点

| 想加什么 | 做法 |
|----------|------|
| 新数据源 | 后端加 `/api/data/*`，返回标准 `rows` 或分析结果 |
| 新模型 | 后端 `/api/simulate` 换成你的正演器 |
| 新反演算法 | 后端 `/api/inversion/*` 换成你的优化器，保持 `best_params`/`history` 格式 |
| 新结果展示 | 后端加 `/api/results/*`，前端在②页加卡片 |

## 6.5 打包成 macOS 桌面 App

`src-tauri/` 下有一份 Tauri 项目骨架，能把这个工作台包成双击启动的 `.app`。
具体编译步骤、会踩的坑、以及这版做了哪些 macOS 视觉调整，看
[`README-APP.md`](./README-APP.md)。

## 7. 边界

- 界面只展示，不做科学结论升级。
- 正式长计算建议在远程（如 Legion）通过 `oer-wf` 工作流执行，网页用于快速诊断。
- Gate 判定由计算侧给出，界面不自行宣称通过。
