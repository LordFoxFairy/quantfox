#!/usr/bin/env bash
# 安装 quantfox 引擎为全局命令（装完在任何目录都能 `quantfox ...`）。幂等，可重复运行。
set -euo pipefail

# 仓库/插件根目录：优先 git，否则按脚本相对位置（scripts/../../.. = 根）
ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel 2>/dev/null || cd "$(dirname "$0")/../../.." && pwd)"

if ! command -v uv >/dev/null 2>&1; then
  echo "❌ 未找到 uv。请先安装：https://docs.astral.sh/uv/getting-started/installation/"
  exit 1
fi

echo "📦 安装 quantfox 引擎为全局命令（uv tool install）..."
uv tool install --force "$ROOT"

echo "✅ 完成。任何目录都能用了，试试："
echo "   quantfox evidence gold --format markdown"
echo "（若提示找不到命令，把 ~/.local/bin 加进 PATH，或跑 uv tool update-shell）"
