#!/bin/bash
# OER-FTAcV Web 工作台开发服务器启动脚本
# 依次选择可用的 Python 解释器（优先 Kimi Work 托管运行时，含 fastapi/uvicorn 依赖）
set -e
cd "$(dirname "$0")"

MANAGED_PY="/Users/liushiyu/Library/Application Support/kimi-desktop/daimon-share/daimon/runtime/python/.venv/bin/python"

if [ -x "$MANAGED_PY" ] && "$MANAGED_PY" -c "import fastapi, uvicorn" 2>/dev/null; then
  PY="$MANAGED_PY"
elif command -v python3 >/dev/null 2>&1 && python3 -c "import fastapi, uvicorn" 2>/dev/null; then
  PY="python3"
elif command -v python >/dev/null 2>&1 && python -c "import fastapi, uvicorn" 2>/dev/null; then
  PY="python"
else
  echo "[dev.sh] 未找到带 fastapi/uvicorn 的 Python，请先安装: pip install -r requirements.txt" >&2
  exit 1
fi

echo "[dev.sh] 使用解释器: $PY"
exec "$PY" -m uvicorn backend.main:app --host 0.0.0.0 --port 7100 "$@"
