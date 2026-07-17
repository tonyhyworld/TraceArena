"""
交互式建号脚本：内部白名单场景下，管理员在服务器上手动跑这个脚本建账号。
不暴露成 HTTP 接口，避免任何白名单外的人能建号。

用法：cd backend && ./.venv/bin/python scripts/create_user.py
"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth.permissions import ALL_PERMISSION_KEYS  # noqa: E402
from app.auth.store import user_store  # noqa: E402


def main() -> None:
    print("=== AI世界 · 建号 ===")
    username = input("用户名（字母/数字/下划线/横杠，3-32 位）: ").strip()
    display_name = input("显示名（留空则用用户名）: ").strip()
    is_admin = input("是否管理员？(y/N): ").strip().lower() == "y"
    permissions: list = []
    if not is_admin:
        grant_all = input("是否授予全部功能权限？(y/N，之后仍可在运营台「用户管理」页面调整): ").strip().lower() == "y"
        permissions = list(ALL_PERMISSION_KEYS) if grant_all else []
    password = getpass.getpass("密码: ")
    password2 = getpass.getpass("确认密码: ")
    if password != password2:
        print("[error] 两次密码不一致")
        sys.exit(1)
    if len(password) < 6:
        print("[error] 密码至少 6 位")
        sys.exit(1)
    try:
        user = user_store.create_user(
            username=username, password=password,
            display_name=display_name, is_admin=is_admin,
            permissions=permissions,
        )
    except ValueError as exc:
        print(f"[error] {exc}")
        sys.exit(1)
    print(f"[ok] 已创建账号 {user.username}（user_id={user.user_id}）")


if __name__ == "__main__":
    main()
