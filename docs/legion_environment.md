# 拯救者（Legion）计算环境配置解释书

最后核实：2026-08-22（keepalive 已验证；解释器已迁移）
适用主机：Lenovo Legion，`LAPTOP-JBG0SNHL`，Windows + WSL2
维护约定：**本文件所述任何一项被改动，都必须同步更新本文件。**

> 本文件不记录任何凭据、密钥或私有地址。敏感值另见
> `docs/environment_resolved_state.md`（不得复制进本文件或提交历史）。

---

## 1. 分工

| 机器 | 职责 |
|---|---|
| MacBook Pro | 代码、快速测试、文档、Git、结果校验与作图 |
| 拯救者 | 正式数值计算（长时反演、MCMC、扫描） |

拯救者不做代码修改；Mac 不做正式计算。每份正式结果必须能同时追溯到
commit、工作树、解释器与主机。

## 2. 环境现状

```
主机名        LAPTOP-JBG0SNHL
发行版        Debian-Bookworm (WSL2)
普通用户      lsy
CPU           16 逻辑核（WSL 内 nproc）
内存          约 7.5 GB（WSL 内 free -m）
根分区        约 1 TB，可用 946 GB
systemd       已启用（/etc/wsl.conf 中 boot.systemd=true），状态 degraded
              仅 kmod-static-nodes.service 失败，对计算无影响
sudo          需要密码 —— agent 无法安装系统包或改 /etc 下的文件
```

正式计算解释器（**当前，2026-08-22 起**）：

```
/home/lsy/oer-venv/bin/python
python 3.11.2   numpy 2.2.6   scipy 1.16.3   optuna 4.9.0   matplotlib 3.11.1
不含 cma
```

它由旧路径 `/home/lsy/OER-FTAcV-run-8cf26be/.venv` 原样 `cp -a` 而来。
迁移理由见第 6 节。等价性验证：

| 检查 | 结果 |
|---|---|
| 版本 | 四项依赖版本完全一致 |
| 数值 | 同一正演的电流数组 sha256 **逐位相同**（`66edbf19…1eb640`） |
| 测试 | 新解释器上 `python/tests` 107 passed |

旧路径**保留未删**，但不再作为正式解释器。任何脚本、文档或 manifest 中
出现 `run-8cf26be/.venv` 都应视为过期引用。

## 3. 关键限制：WSL 会终止发行版，后台作业活不过 SSH 断开

**这是本机最容易踩、且最贵的坑。** 在拯救者上用 `nohup ... &` 或
`tmux new-session -d` 启动的长时计算，会在 SSH 连接关闭后**全部消失**，
日志停在启动行，没有 traceback，没有输出文件——看起来像"跑完了"。

### 机制

WSL2 的 **VM** 与 **发行版** 生命周期是两回事：

* `vmIdleTimeout` 管 VM，当前生效值 86400000 ms（24 h），**不是原因**；
* 发行版在"启动它的那个会话"退出后被终止，连同该会话派生的所有后台
  进程一起。`nohup` 和 `tmux` 都在发行版内部，一起消失；
* 没有发行版级别的超时开关可调。

### 排除掉的错误归因

| 假设 | 实测 | 结论 |
|---|---|---|
| `vmIdleTimeout` 太短 | 生效配置为 24 h | 否 |
| `logind` 杀用户进程 | `busctl` 读出 `KillUserProcesses=false` | 否 |
| 未开 linger | `loginctl show-user lsy` → `Linger=yes` | 否 |
| VM 被销毁 | `uptime` = up 1 day 1:26 | 否，VM 没重启 |
| 发行版被销毁 | `who -b` = 15:50；作业 PID 为 113–116 | **是**，PID 命名空间全新 |

诊断口诀：**`uptime` 看 VM，`who -b` 和 PID 大小看发行版。**

### 当前做法（已验证有效）

由 Mac 持有一条长连接前台执行：

```bash
ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=2000 legion \
    'bash /home/lsy/OER-FTAcV-run-<commit>/run_all.sh'
```

连接在，发行版就在。代价：Mac 必须保持联网、不休眠；断线即中断计算。
因此**脚本必须逐步落盘**（见第 5 节）。

> **该做法已于 2026-08-22 停用**——keepalive 验证通过后，改用 `nohup`
> 即可（见下）。此段保留作为 keepalive 失效时的应急手段。

### 根治：Windows 侧常驻会话（**已安装，2026-08-22**）

在 Windows 上常驻一个 WSL 会话即可。脚本位于
`%UserProfile%\oer-wsl-keepalive.vbs`，并已复制进当前用户的启动目录：

```vbs
Set sh = CreateObject("WScript.Shell")
sh.Run "wsl.exe -d Debian-Bookworm -u lsy --exec /bin/sh -c ""while true; do sleep 3600; done""", 0, False
```

安装用的 PowerShell（普通权限，不需要管理员）：

```powershell
$vbs = Join-Path $env:UserProfile 'oer-wsl-keepalive.vbs'
# ... 写入上述内容 ...
Copy-Item $vbs (Join-Path ([Environment]::GetFolderPath('Startup')) 'oer-wsl-keepalive.vbs') -Force
Start-Process wscript.exe -ArgumentList "`"$vbs`"" -WindowStyle Hidden
```

用 `$env:UserProfile` 与 `GetFolderPath('Startup')` 而非硬编码路径，可自动
避开第 4 节的双配置文件陷阱。

**验证结果：通过（2026-08-22）。** 方法是种一个故意不带 `nohup` 的标记
进程，然后断开全部 SSH 会话 3 分钟以上再回连：

```
                    断开前                    断开 3 分钟后
who -b              2026-08-22 15:50          2026-08-22 15:50      <- 未变
keepalive           pid 307                   pid 307  存活
marker (setsid)     pid 386                   pid 386  存活
pid 1 age           -                         01:00:03              <- 发行版未重启
```

附带印证了第 3 节的诊断口诀：同一时刻 `/proc/stat` 的 `btime` 为
2026-08-21 14:33（**VM** 启动），而 `who -b` 为 2026-08-22 15:50
（**发行版**启动），两者相差一天——这正是当初误判的根源。

结论：keepalive 生效，`nohup` 与 `tmux` 现在可靠。正式计算**不再需要**
Mac 持有长连接。

## 4. Windows 侧配置：两个用户配置文件，别改错

`/mnt/c/Users/` 下同时存在 `lsy` 与 `lsy.LAPTOP-JBG0SNHL`，两者都有
`.wslconfig`：

| 路径 | 内容 | 是否生效 |
|---|---|---|
| `C:\Users\lsy\.wslconfig` | `vmIdleTimeout=-1`, `memory=8GB`, `processors=6`（每行带尾随空格） | **否** |
| `C:\Users\lsy.LAPTOP-JBG0SNHL\.wslconfig` | `vmIdleTimeout=86400000` | **是** |

生效的是后者，由 PowerShell `[Environment]::GetFolderPath("UserProfile")`
确认。佐证：未生效的那份写了 `processors=6`，而 WSL 内 `nproc` 为 16。

**改 WSL 资源配置后必须复核**：

```bash
ssh legion 'nproc; free -m | awk "NR==2{print \$2}"'
```

改 `.wslconfig` 需要 `wsl --shutdown` 才生效，会杀掉一切正在跑的计算——
**只在没有作业时做。**

## 5. 正式计算规程

1. Mac 上提交并推送代码；
2. 拯救者上按 commit 建独立工作树，**不为它另装依赖**：

   ```bash
   cd /home/lsy/OER-FTAcV
   git fetch origin <branch>
   git worktree add --detach /home/lsy/OER-FTAcV-run-<short> origin/<branch>
   ```

3. 用第 2 节的钉住解释器先跑全量测试，通过后才启动计算；
4. 用 `setsid nohup ... &` 启动，**并且在断开 SSH 之前必须确认进程已经
   立起来**（见下方"启动竞态"）。断开数分钟后再回连确认一次——这是唯一能
   区分"正在跑"和"已被收走"的方法；
5. 脚本必须**逐个数据集落盘**——连接可能中断，且 WORK_STATUS §16 记录过
   末尾统一写 CSV 导致整轮结果只剩表头的事故；
6. 结果 manifest 必须含 `commit` / `worktree` / `interpreter` / `hostname`
   与依赖版本；多分片合并前校验同源（`scripts/merge_low_dim_results.py`）。

### 启动竞态：断开太快会杀掉刚起的进程

即使 keepalive 已生效、发行版不会重启，**在进程完全启动之前断开 SSH，
它仍会被一并收走**。实测三次：

| 启动方式 | 启动后是否等待 | 结果 |
|---|---|---|
| `nohup python ... &` 后立即退出 | 否 | 日志 0 字节，进程消失 |
| `setsid nohup python ... &` 后立即退出 | 否 | 日志 0 字节，进程消失 |
| `nohup sh -c ... &` + `sleep 4` | 是 | 存活 |
| `setsid nohup python ... &` + `sleep 25` | 是 | 存活，跑到结束 |

失败时 `who -b` 与 pid 1 存活时间均不变——**发行版没有重启，是进程本身
被收走**，与第 3 节那个发行版销毁问题是两回事。原因是 Python 完成 import
需要一两秒，这段时间里进程还没真正立稳。

因此启动脚本必须**轮询日志确认有进度输出后再退出**，例如：

```bash
PYTHONPATH=... setsid nohup "$PY" -u script.py > logs/run.log 2>&1 &
for i in $(seq 1 12); do
  sleep 5
  grep -q "进度标志" logs/run.log && { echo running; exit 0; }
done
echo "WARNING: 未确认启动"
```

对应地，长时脚本应尽早输出第一行进度，不要等第一个数据集算完才打印。

并发建议：16 核，四个数据集并发 × 每个 4 条链 = 16 进程，实测内存占用
约 2 GB / 7.5 GB。设置 `OMP_NUM_THREADS=1` 等，避免 BLAS 线程与进程级
并行相乘。

## 6. 已知待整改项

| 项 | 状态 | 说明 |
|---|---|---|
| 解释器嵌在 commit 命名的工作树内 | **已解决** | 迁到 `/home/lsy/oer-venv`，逐位等价已验证（第 2 节） |
| WSL 后台作业活不过 SSH 断开 | **已解决** | keepalive 已装并验证（第 3 节） |
| 工作树沉积 | **未解决，不建议自动清理** | 见下 |
| `sudo` 需密码 | 不变 | 需要系统级改动时由用户执行 |
| systemd `degraded` | 不处理 | 仅 `kmod-static-nodes.service` 失败，对计算无影响 |
| 缺 `cma` | 不安装 | 低维主线已改用 `scipy.optimize.differential_evolution` |

### 工作树沉积：为什么没有自动清理

`git worktree list` 共 **43 项**（16 个顶层 `OER-FTAcV-run-*`，26 个嵌套在
`OER-FTAcV/worktrees/<commit>/<name>` 下）。按"无未提交改动 + 无未跟踪文件 +
`results/` 为空"逐个判定：

```
KEEP(pinned)   3    main / run-ce4f7d6 / run-8cf26be
HAS-CONTENT   40    全部含未跟踪文件、未提交改动或结果文件
SAFE-REMOVE    0
```

合计 **6441 个结果文件**存放在这些工作树里，且不在仓库中。删除工作树会
一并销毁它们，因此**不做自动清理**。示例（结果文件数最多的几个）：

```
worktrees/6400989/a6_recovery_k0_123          508
worktrees/c7a9ee1/formal-v2-no-tafel          498
worktrees/c45fb18/a6_sampler_screen           498
worktrees/10abd5f/objective-profiles-formal   498
```

另注：`/home/lsy/OER-FTAcV-run-3e08bdd` 的 HEAD 实际是 `d174110`，
**目录名与 commit 已经对不上**，不能按名字推断内容。

处理建议（需用户判断，逐个确认后再动）：

1. 结合纠错 §19 的追溯提醒，先确认哪些是完整跑完的结果、哪些是被发行版
   销毁而截断的；
2. 有价值的同步回仓库 `results/` 或归档；
3. 确认无价值后再 `git worktree remove`；
4. 此后正式计算的结果一律同步回仓库，工作树只作临时执行目录。

## 7. SSH 输出噪声

每次 SSH 都会带一行 WSL 的 localhost 代理告警（UTF-16 编码，混在
stdout 里）。解析拯救者输出的脚本需要过滤：

```bash
ssh legion 'bash -s' < script.sh 2>&1 | tr -d '\000' | grep -av localhost
```
