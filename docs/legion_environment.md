# 拯救者（Legion）计算环境配置解释书

最后核实：2026-08-22
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

正式计算解释器（**当前**）：

```
/home/lsy/OER-FTAcV-run-8cf26be/.venv/bin/python
python 3.11.2   numpy 2.2.6   scipy 1.16.3   optuna 4.9.0   matplotlib 3.11.1
不含 cma
```

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

### 根治（需用户在 Windows 上执行一次）

在 Windows 侧常驻一个 WSL 会话即可。把下面内容存成
`C:\Users\lsy.LAPTOP-JBG0SNHL\oer-wsl-keepalive.vbs`：

```vbs
Set sh = CreateObject("WScript.Shell")
sh.Run "wsl.exe -d Debian-Bookworm -u lsy --exec /bin/sh -c ""while true; do sleep 3600; done""", 0, False
```

然后把它放进启动目录：

```
C:\Users\lsy.LAPTOP-JBG0SNHL\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\
```

双击一次即可立即生效，之后每次登录自动运行，窗口隐藏。

验证方法（Mac 上）：

```bash
ssh legion 'pgrep -af "sleep 3600" | head'
```

有输出即生效。此后 `nohup` / `tmux` 才真正可靠。

> 该操作会写入 Windows 启动项，属于主机自身配置，由用户执行；
> agent 不代为安装。

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
4. 由 Mac 持有长连接前台执行（第 3 节）；
5. 脚本必须**逐个数据集落盘**——连接可能中断，且 WORK_STATUS §16 记录过
   末尾统一写 CSV 导致整轮结果只剩表头的事故；
6. 结果 manifest 必须含 `commit` / `worktree` / `interpreter` / `hostname`
   与依赖版本；多分片合并前校验同源（`scripts/merge_low_dim_results.py`）。

并发建议：16 核，四个数据集并发 × 每个 4 条链 = 16 进程，实测内存占用
约 2 GB / 7.5 GB。设置 `OMP_NUM_THREADS=1` 等，避免 BLAS 线程与进程级
并行相乘。

## 6. 已知待整改项

| 项 | 现状 | 计划 |
|---|---|---|
| 解释器嵌在 commit 命名的工作树内 | `run-8cf26be/.venv` | 迁到与 commit 无关的稳定路径，版本逐一钉住并验证数值一致后切换（纠错 §21） |
| 14 个残留 `OER-FTAcV-run-*` 工作树 | 占位、语义误导 | 待当前作业结束后按 `git worktree list` 逐个确认再清理 |
| `sudo` 需密码 | agent 无法装系统包 / 改 `/etc` | 需要系统级改动时由用户执行 |
| systemd `degraded` | 仅 `kmod-static-nodes.service` 失败 | 对计算无影响，暂不处理 |
| 缺 `cma` | 低维主线改用 `scipy.optimize.differential_evolution` | 不再需要，不安装 |

## 7. SSH 输出噪声

每次 SSH 都会带一行 WSL 的 localhost 代理告警（UTF-16 编码，混在
stdout 里）。解析拯救者输出的脚本需要过滤：

```bash
ssh legion 'bash -s' < script.sh 2>&1 | tr -d '\000' | grep -av localhost
```
