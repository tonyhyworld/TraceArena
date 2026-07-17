#!/usr/bin/env bash
set -euo pipefail

# One-command local setup for macOS/Linux. The script is intentionally
# non-destructive: it reuses an existing .venv and never overwrites .env files.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

command -v python3 >/dev/null 2>&1 || {
  echo "错误：需要先安装 Python 3.10+（https://www.python.org/downloads/）" >&2
  exit 1
}
command -v npm >/dev/null 2>&1 || {
  echo "错误：需要先安装 Node.js 20+（https://nodejs.org/）" >&2
  exit 1
}

python_version="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
python3 - "$python_version" <<'PY'
import sys
major, minor = map(int, sys.argv[1].split('.'))
if (major, minor) < (3, 10):
    raise SystemExit(f"错误：TraceArena 需要 Python 3.10+，当前为 Python {major}.{minor}")
PY

node_major="$(node -p 'process.versions.node.split(".")[0]')"
if [ "$node_major" -lt 18 ]; then
  echo "错误：前端需要 Node.js 18+（推荐 20+），当前为 $(node -v)" >&2
  exit 1
fi

if [ ! -d .venv ]; then
  echo "[1/4] 创建 Python 虚拟环境"
  python3 -m venv .venv
else
  echo "[1/4] 复用已有 Python 虚拟环境 .venv"
fi

echo "[2/4] 安装 Python 依赖"
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"

echo "[3/4] 安装前端依赖"
npm ci --prefix frontend

if [ ! -f frontend/.env.local ] && [ -f frontend/.env.example ]; then
  echo "[4/4] 创建 frontend/.env.local（仅复制默认 localhost 配置）"
  cp frontend/.env.example frontend/.env.local
else
  echo "[4/4] 保留已有 frontend/.env.local"
fi

cat <<'EOF'

安装完成。

运行确定性回放：
  source .venv/bin/activate
  PYTHONPATH=backend python backend/scripts/market_replay.py \
    --fixture examples/market_replay/fixture.json \
    --output ./runs/market_replay_demo --locale zh-CN

构建完整前端：
  npm run build --prefix frontend

完整前端的 API/WebSocket 后端要求见 frontend/README.md；无需后端即可体验
frontend/public_demo 或 Hugging Face 公开演示。
EOF
