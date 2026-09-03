# 拯救者本机 Agent 交接说明

> 给在 **LAPTOP-JBG0SNHL 的 WSL 里本地运行**的 agent。
> 你不需要 SSH——你就在这台机器上。
>
> 生成时间：2026-09-03　生成者：Mac 侧 agent　对应 commit `86c1bc3`
> 本文件自包含。`/home/lsy/OER-FTAcV` 当前 checkout 在 `main`（`1becc12`），
> **落后于主线**，里面的 `docs/legion_environment.md` 是旧版，以本文件为准。

---

## 1. 这台机器是干什么的

| 机器 | 职责 |
|---|---|
| MacBook Pro | 写代码、快速测试、文档、Git、结果校验与作图 |
| **拯救者（你在这）** | **正式数值计算**：长时反演、MCMC、参数扫描 |

**你不改代码。** 代码在 Mac 上改完、提交、推送，你只负责取下来跑。
每份正式结果必须能同时追溯到 commit、工作树、解释器、主机。

项目是 OER-FTAcV：用傅里叶变换交流伏安法（FTacV）反演析氧反应动力学参数。
当前主线是低维 Bonke 分子催化模型 + 贝叶斯后验。

---

## 2. 目录结构：只有三个

2026-09-03 刚做过一次彻底清理（8.3 GB → 655 MB），现在 `/home/lsy` 下就这些：

```
/home/lsy/
├── oer-venv/      411 MB   唯一正式解释器 —— 见 §3
├── oer-archive/   184 MB   全部历史计算结果（去重归档）—— 见 §7
└── OER-FTAcV/      59 MB   仓库主 checkout（.venv 是软链）
```

**保持这个样子。** 别在家目录堆散文件；临时文件放 `/tmp`。

---

## 3. 解释器：只有一个，不许改

```
/home/lsy/oer-venv/bin/python
```

```
python 3.11.2
numpy 2.2.6      scipy 1.16.3       matplotlib 3.11.1
optuna 4.9.0     pytest 9.1.1       tqdm 4.69.1        PyYAML 6.0.3
BLAS/LAPACK: scipy-openblas 0.3.29（numpy 与 scipy 共用）
```

其余包（SQLAlchemy / alembic / fastapi / uvicorn / pydantic / starlette /
Mako / colorlog / greenlet）都是 optuna 拖进来的依赖，不直接使用。

**没有装,也不要装**：`cma`、`pints`、`numba`、`cython`、`jax`、`torch`。
（PINTS 那次外部校验在 Mac 侧做，不需要在这装。低维主线用
`scipy.optimize.differential_evolution` 代替 `cma`。）

### `.venv` 是软链，不要动它

```
/home/lsy/OER-FTAcV/.venv -> /home/lsy/oer-venv
```

历史上这里是个**独立的 venv 且版本已经漂移**（numpy 2.4.6 / scipy 1.17.1，
而正式解释器是 2.2.6 / 1.16.3）。仓库里有 5 个脚本的用法说明写着
`.venv/bin/python`，照抄就会静默用不同的数值库跑出"正式"结果。

改成软链之后所有写法都指向同一个解释器，**漂移在结构上不可能发生**。

> **绝对不要**把这个软链换回真实目录，
> **绝对不要**在 `oer-venv` 里 `pip install`／`pip uninstall`／升级任何包。
>
> 如果某个任务确实需要新依赖：**停下来报告，不要自己装。**
> 换掉 numpy/scipy 会让此前所有正式结果失去可比性。

需要临时试包时，另建一个一次性 venv，用完删掉，且**不得用它产出正式结果**。

---

## 4. 系统环境

```
发行版   Debian GNU/Linux 12 (bookworm)，WSL2
内核     6.18.33.1-microsoft-standard-WSL2
CPU      16 逻辑核        内存  7531 MB
根分区   1007 GB，已用 3.6 GB
systemd  已启用，状态 degraded（仅 kmod-static-nodes.service 失败，无影响）
```

工具链：

```
gcc / g++ / gfortran  12.2.0        make 4.3    git 2.39.5
tmux   rsync   ripgrep   curl   wget   xz
python3 3.11.2（系统）  pip 23.0.1  python3-venv
```

**没有**：cmake、clang、R、julia、java、node、`bc`。

另外装了一整套与本项目无关的分子动力学/对接工具（gromacs、lammps、
autodock-vina、openbabel、mpi4py）——**别用，也别删**，可能属于用户的其他工作。

### 你做不了的事

**`sudo` 需要密码。** 你不能装系统包、不能改 `/etc` 下的文件、不能
`apt-get`。碰到需要系统级改动的，写清楚要执行什么命令，交给用户。

---

## 5. 正式计算规程

```bash
cd /home/lsy/OER-FTAcV
git fetch origin <branch>
C=$(git rev-parse --short origin/<branch>)
git worktree add --detach /home/lsy/OER-FTAcV-run-$C origin/<branch>
cd /home/lsy/OER-FTAcV-run-$C

PY=/home/lsy/oer-venv/bin/python

# 1) 先跑全量测试，不过就不要启动计算
PYTHONPATH="$PWD/python" $PY -m pytest python/tests -q
#    基线：118 passed, 9 skipped（commit bb2ba01，约 70 秒）

# 2) 启动
mkdir -p logs
PYTHONPATH="$PWD/python" \
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  setsid nohup $PY -u scripts/<script>.py <args> > logs/run.log 2>&1 &

# 3) 必须确认进程立稳（见 §6.2），再去做别的
```

**规矩**（每一条背后都有过事故）：

1. **不为工作树另装依赖**，一律用 `/home/lsy/oer-venv/bin/python` 全路径；
2. **测试不过就不启动**。曾经在 4 项测试失败的情况下照样起了正式计算；
3. **脚本必须逐个数据集落盘**。曾经在末尾统一写 CSV，中途断掉后整轮结果
   只剩表头；
4. **结果 manifest 必须含** `commit` / `worktree` / `interpreter` /
   `hostname` 与依赖版本；多分片合并前校验同源；
5. **结果同步回仓库后立即 `git worktree remove` 掉执行目录。**
   这条以前一直没做，结果沉积了 51 个工作树 6.12 GB，其中 **96% 是同一批
   文件的重复拷贝**。工作树只是临时执行目录，不是结果的存放地。

并发：16 核，四个数据集并发 × 每个 4 条链 = 16 进程，实测约 2 GB / 7.5 GB。
**务必设 `OMP_NUM_THREADS=1` 等**，否则 BLAS 线程会和进程级并行相乘。

---

## 6. 已知陷阱

这几条都是真踩过的，判断错一次代价是几小时的计算白跑。

### 6.1 WSL 会终止发行版，历史上后台作业活不过 SSH 断开

WSL2 的 **VM** 和**发行版**生命周期是两回事。发行版会在"启动它的那个会话"
退出后被终止，连同该会话派生的所有后台进程——`nohup` 和 `tmux` 一起消失，
日志停在启动行，**没有 traceback，没有输出文件，看起来像"跑完了"**。

**现状：已经解决。** Windows 侧装了常驻会话
（`%UserProfile%\oer-wsl-keepalive.vbs`，已放进启动目录），它在发行版里
留一个 `sleep 3600` 循环（当前 PID 108）。只要它活着，发行版就不会被销毁。

**开工前先确认它还在：**

```bash
pgrep -af "sleep 3600"
```

查不到就**不要启动长时计算**，先报告用户去 Windows 侧重启那个 vbs。

### 6.2 启动竞态：进程没立稳就撒手，照样被收走

即使 keepalive 生效，**在进程完全启动之前断开会话，它仍会被一并收走**。
实测：`nohup` 和 `setsid nohup` 后立即退出，日志都是 0 字节。原因是 Python
完成 import 要一两秒，这段时间进程还没立稳。

失败时 `who -b` 和 pid 1 存活时间都不变——**发行版没重启，是进程本身被收走**，
和 §6.1 是两回事，别搞混。

**所以：启动后必须轮询日志确认有进度输出，再做别的。**

```bash
for i in $(seq 1 24); do
  sleep 5
  grep -aq "<进度关键词>" logs/run.log && { echo running; break; }
done
```

对应地，**长时脚本要尽早打印第一行进度**，不要等第一个数据集算完才输出。

### 6.3 `who -b` 不可靠，别用它判断发行版启动时间

2026-09-03 实测三源互相矛盾：

```
who -b              2026-08-23 01:33     <- 比 VM 启动还早 6 天
/proc/stat btime    2026-08-29 16:02:13
ps -o lstart= -p 1  Sat Aug 29 16:02:15
uptime              up 5 days 7 h
```

`who -b` 读 `utmp`，而 **WSL 重启发行版时不保证重写 utmp**。

**正确判据：**

| 想知道 | 用什么 |
|---|---|
| VM 什么时候起的 | `uptime`、`/proc/stat` 的 `btime` |
| **发行版**什么时候起的 | **`ps -o lstart= -p 1`** |

`who -b` 只能作旁证；与另外两者不一致时，**以另外两者为准**。

### 6.4 `find -size -1M` 是个陷阱

`find -size` 按单位**向上取整后**再比较，任何 ≥1 字节的文件都会被取整成
1M，所以 `-size -1M`（严格小于 1 个单位）**实际只匹配 0 字节文件**。

归档时用它选"小于 1MB 的文件"，249 个只选中 6 个，差点让 222 个文件跟着
`rm -rf` 一起消失。

**改用字节比较：**

```bash
find DIR -type f -printf '%s\t%p\n' | awk -F'\t' '$1<=1048576 {print $2}'
```

### 6.5 不可逆删除前必须对账

上面那次是靠 `249 = 21 + 228` 这一步对账才发现漏归档的。

> **任何 `rm -rf` 之前，归档的文件计数必须与原始计数逐个对齐并断言相等。**
> 计数不符就停下，不要删。

### 6.6 输出里的 WSL 噪声

WSL 有时会往 stdout 混进一行 localhost 代理告警（UTF-16 编码）。解析命令
输出的脚本要过滤：

```bash
... 2>&1 | tr -d '\000' | grep -av localhost
```

---

## 7. 历史结果都在归档里

`/home/lsy/oer-archive/`（184 MB）装着此前**全部** 6828 个结果文件，
原始体积 6.12 GB。之所以能压到 184 MB，是因为 521 个大文件按 sha256
**只有 17 份唯一内容**——其余全是同一批文件在 51 个工作树之间的重复拷贝。

```
oer-archive/
├── large/<sha256>              17 份唯一大文件，按内容 hash 命名
├── large-manifest.tsv          sha256 / size / 原始路径
├── results-small.tar.gz        6307 个 <=1MB 文件，保留完整路径结构
├── wf-preserved-small.tar.gz   _wf_preserved_results 的 228 个文件
├── misc-orphans.tar.gz         168 个散落文件（含 oer-wf 源码）
└── worktree-meta.tar.gz        16 个工作树根下的 log/manifest
```

**复原任意一份大文件：**

```bash
grep '<原始路径片段>' /home/lsy/oer-archive/large-manifest.tsv
cp /home/lsy/oer-archive/large/<sha256> <目标路径>
```

需要注意：这批结果里，`signed_sensitivity.csv` / `sensitivity_matrix.csv`
属于**已被撤回**的 CV 可辨识性方法那条线（项目纠错 §10），是中间产物，
**不要拿它们当结论用**。

**归档只增不删。** 要清理请先报告。

---

## 8. 主线现状（背景，供判断用）

- 正式反演用 **LSODA**；C 语言的 Crank-Nicolson 加速两轮都没通过等价性门，
  **不启用**。
- AEM 5 步模型已**降级**为待更多数据支持的扩展模型（未删除）。
- 2026-08-22 夜间那轮正式反演的**后验作废**——似然把相关的包络点当成了
  独立样本，导致后验过窄且不可采样。修正后须先过合成数据回收验证，
  再重跑真实数据。
- 可辨识性用 **profile likelihood**，不用 MCMC 后验宽度也不用交叉验证 CV。
- 真实数据反演目前**卡在 Ru（未补偿电阻）没有实测值**上，需要用户做 EIS。

---

## 9. 遇到下列情况，停下来报告，不要自己决定

1. 需要 `pip install` 任何东西；
2. 需要 `sudo`；
3. 想改动或删除 `oer-venv`、`oer-archive`、`.venv` 软链；
4. `pgrep -af "sleep 3600"` 查不到 keepalive；
5. 测试不是 `118 passed, 9 skipped`（或该 commit 的已知基线）；
6. 任何不可逆删除，且归档计数对不上；
7. 磁盘可用空间低于 50 GB。
