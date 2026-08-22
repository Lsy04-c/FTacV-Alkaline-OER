#!/usr/bin/env bash
# 构建低维模型的 C Crank-Nicolson 求解器。
#
# 刻意不使用 -ffast-math：实测对速度无可测收益、对误差无影响，
# 保留 IEEE 语义换取跨平台可复现（docs/solver_acceleration_feasibility.md 第 5 节）。
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/cpp/mc_cn_solver.c"
case "$(uname -s)" in
  Darwin) OUT="$ROOT/cpp/libmccn.dylib" ;;
  Linux)  OUT="$ROOT/cpp/libmccn.so" ;;
  *)      OUT="$ROOT/cpp/libmccn.dll" ;;
esac
CC_BIN="${CC:-cc}"
"$CC_BIN" -O3 -shared -fPIC -o "$OUT" "$SRC" -lm
echo "built: $OUT"
"$CC_BIN" --version | head -1
