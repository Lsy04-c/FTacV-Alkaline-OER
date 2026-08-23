#!/usr/bin/env bash
# 在拯救者上启动正式计算：建工作树 → 跑测试 → 启动 → 确认立稳 → 轮询 → 同步回来。
#
# 把今天踩过的坑固化成流程（docs/legion_environment.md、docs/项目纠错.md §19/§22）：
#   - 发行版会在最后一个会话退出后被销毁 => 依赖 Windows 侧 keepalive
#   - 进程未立稳就断开 SSH 会被一并收走 => 必须轮询确认有进度输出再退出
#   - Python 输出会被缓冲 => 一律加 -u
#   - 结果只在末尾统一写会丢失整轮 => 脚本自身须逐步落盘
#
# 用法：
#   scripts/run_remote.sh <分支> "<相对仓库根的命令>" <进度关键词> <结果子目录>
# 例：
#   scripts/run_remote.sh claude/xxx \
#     "scripts/fit_molecular_catalysis.py --datasets FT8 --outdir results/low_dim_bonke/FT8" \
#     "CMA-ES" results/low_dim_bonke/FT8
set -euo pipefail

BRANCH="${1:?需要分支名}"
CMD="${2:?需要要执行的命令}"
MARKER="${3:?需要进度关键词}"
RESULT_DIR="${4:-}"
HOST="${LEGION_HOST:-legion}"
PY="${LEGION_PY:-/home/lsy/oer-venv/bin/python}"
LOCAL_ROOT="$(git rev-parse --show-toplevel)"

# 先在远端把 commit 解析出来并固定下来。原先在同步阶段做嵌套命令替换，
# 而那一步在数小时后才执行——真出错时整轮结果都取不回来。
ssh -o BatchMode=yes "$HOST" "cd /home/lsy/OER-FTAcV && git fetch --quiet origin '$BRANCH' && git rev-parse --short 'origin/$BRANCH'" \
  > /tmp/oer_remote_commit 2>/dev/null
COMMIT="$(tr -d '\000' < /tmp/oer_remote_commit | grep -av localhost | tail -1 | tr -d '[:space:]')"
[ -n "$COMMIT" ] || { echo "无法解析远端 commit"; exit 1; }
REMOTE_WT="/home/lsy/OER-FTAcV-run-$COMMIT"
echo "远端 commit=$COMMIT  worktree=$REMOTE_WT"

ssh -o BatchMode=yes "$HOST" bash -s <<REMOTE
set -eu
cd /home/lsy/OER-FTAcV
WT="$REMOTE_WT"
[ -d "\$WT" ] || git worktree add --quiet --detach "\$WT" "origin/$BRANCH"
cd "\$WT"; mkdir -p logs

# 测试不过就不启动。首次使用时这里只打印结果不拦截，结果是在 4 项测试
# 失败的情况下照样起了正式计算——正式计算的前提是代码可信。
if ! PYTHONPATH="\$WT/python" "$PY" -m pytest python/tests -q > /tmp/oer_remote_tests.log 2>&1; then
  echo "远端测试未通过，拒绝启动正式计算："
  grep -E "^FAILED|passed|failed" /tmp/oer_remote_tests.log | tail -8
  exit 2
fi
tail -1 /tmp/oer_remote_tests.log

LOG="logs/remote_\$(date +%H%M%S).log"
: > "\$LOG"
echo "\$LOG" > logs/.last
PYTHONPATH="\$WT/python" OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  setsid nohup "$PY" -u $CMD >> "\$LOG" 2>&1 &

# 纠错 §22：必须确认进程立稳再断开 SSH
for i in \$(seq 1 24); do
  sleep 5
  if grep -aq "$MARKER" "\$LOG" 2>/dev/null; then
    echo "confirmed running after \$((i*5))s: \$(grep -a "$MARKER" "\$LOG" | tail -1)"
    exit 0
  fi
done
echo "WARNING: 120s 内未见进度关键词 '$MARKER'"
tail -5 "\$LOG"
exit 1
REMOTE

echo "--- 轮询直至结束 ---"
while true; do
  n=$(ssh -o BatchMode=yes -o ConnectTimeout=30 "$HOST" \
        "pgrep -fc '$(echo "$CMD" | awk '{print $1}')' 2>/dev/null || echo 0" \
        2>/dev/null | tr -d '\000' | grep -av localhost | tail -1 || echo "")
  [ -z "$n" ] && { sleep 60; continue; }          # 暂时性 ssh 失败不当作结束
  [ "$n" = "0" ] && break
  sleep 120
done
echo "远程作业已结束"

if [ -n "$RESULT_DIR" ]; then
  mkdir -p "$LOCAL_ROOT/$RESULT_DIR"
  for f in $(ssh -o BatchMode=yes "$HOST" "ls '$REMOTE_WT/$RESULT_DIR' 2>/dev/null" \
      2>/dev/null | tr -d '\000' | grep -av localhost); do
    ssh -o BatchMode=yes "$HOST" "cat '$REMOTE_WT/$RESULT_DIR/$f'" \
      2>/dev/null | tr -d '\000' | grep -av "localhost 代理" > "$LOCAL_ROOT/$RESULT_DIR/$f"
    echo "  同步 $RESULT_DIR/$f"
  done
fi
