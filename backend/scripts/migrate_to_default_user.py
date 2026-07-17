"""
一次性迁移脚本：把改造前的全局共享数据归到 default 用户桶下。

用法：cd backend && ./.venv/bin/python scripts/migrate_to_default_user.py

做的事：
1. 在 user_data/users.json 里创建 default 账号（随机初始密码，打印到终端）
2. runs/run_* → runs/default/run_*
3. agents_persistent/prince_* → agents_persistent/default/prince_*

幂等：已经迁移过（runs/default/ 已存在）则跳过对应步骤，不会重复搬移或覆盖账号。
"""
from __future__ import annotations

import secrets
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth.store import user_store  # noqa: E402

RUNS_ROOT = Path("./runs")
PERSISTENT_ROOT = Path("./agents_persistent")
DEFAULT_USER_ID = "default"


def migrate_runs() -> None:
    target = RUNS_ROOT / DEFAULT_USER_ID
    if target.exists():
        print(f"[skip] {target} 已存在，跳过 runs 迁移")
        return
    run_dirs = sorted(d for d in RUNS_ROOT.iterdir() if d.is_dir() and d.name.startswith("run_"))
    if not run_dirs:
        print("[skip] 没有待迁移的 run_* 目录")
        target.mkdir(parents=True, exist_ok=True)
        return
    target.mkdir(parents=True, exist_ok=True)
    for d in run_dirs:
        shutil.move(str(d), str(target / d.name))
    print(f"[ok] 迁移 {len(run_dirs)} 个对局目录 → {target}")


def migrate_agents_persistent() -> None:
    target = PERSISTENT_ROOT / DEFAULT_USER_ID
    if target.exists():
        print(f"[skip] {target} 已存在，跳过 agents_persistent 迁移")
        return
    agent_dirs = sorted(
        d for d in PERSISTENT_ROOT.iterdir()
        if d.is_dir() and d.name != DEFAULT_USER_ID
    ) if PERSISTENT_ROOT.exists() else []
    if not agent_dirs:
        print("[skip] 没有待迁移的 agent 长期记忆目录")
        target.mkdir(parents=True, exist_ok=True)
        return
    target.mkdir(parents=True, exist_ok=True)
    for d in agent_dirs:
        shutil.move(str(d), str(target / d.name))
    print(f"[ok] 迁移 {len(agent_dirs)} 个 agent 记忆目录 → {target}")


def ensure_default_account() -> None:
    if user_store.get_by_id(DEFAULT_USER_ID) is not None:
        print("[skip] default 账号已存在")
        return
    password = secrets.token_urlsafe(9)
    user_store.create_user(
        username="default", password=password,
        display_name="默认账号（历史数据归属）", is_admin=True,
        user_id=DEFAULT_USER_ID,
    )
    print("=" * 50)
    print(f"[ok] 已创建 default 账号，初始密码：{password}")
    print("请妥善保存，登录后可自行改密（如无改密接口，找开发者协助）。")
    print("=" * 50)


if __name__ == "__main__":
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    PERSISTENT_ROOT.mkdir(parents=True, exist_ok=True)
    ensure_default_account()
    migrate_runs()
    migrate_agents_persistent()
    print("迁移完成。")
