#!/usr/bin/env bash
# 安装/更新 money 引擎依赖。幂等，可重复运行。
set -euo pipefail

ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
cd "$ROOT"

if ! command -v uv >/dev/null 2>&1; then
  echo "❌ 未找到 uv。请先安装：https://docs.astral.sh/uv/getting-started/installation/"
  exit 1
fi

echo "📦 同步 money 引擎依赖（uv sync）..."
uv sync

echo "✅ money 引擎就绪。试试："
echo "   uv run money evidence gold --format markdown"
