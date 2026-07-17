#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -x .venv/bin/python ]; then
  echo "未找到 .venv，请先运行 ./scripts/install.sh" >&2
  exit 1
fi
if [ ! -x frontend/node_modules/.bin/vite ]; then
  echo "未找到前端依赖，请先运行 ./scripts/install.sh" >&2
  exit 1
fi

if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
fi

backend_pid=""
frontend_pid=""
cleanup() {
  [ -n "$frontend_pid" ] && kill "$frontend_pid" 2>/dev/null || true
  [ -n "$backend_pid" ] && kill "$backend_pid" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "启动 AI World OS: http://127.0.0.1:8001"
(cd backend && AIWORLD_CONFIG=./framework.public.yaml PYTHONPATH=. ../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001) &
backend_pid=$!

echo "启动完整前端: http://127.0.0.1:5173"
(npm run dev --prefix frontend -- --host 127.0.0.1) &
frontend_pid=$!

echo "首次使用请另开终端创建本地账号："
echo "  cd backend && ../.venv/bin/python scripts/create_user.py"
echo "按 Ctrl-C 同时停止前后端。"
# Bash 3.2 on macOS has no `wait -n`; waiting on both keeps this launcher
# portable. Ctrl-C triggers the trap and stops both child processes.
wait "$backend_pid" "$frontend_pid"
