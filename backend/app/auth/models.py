"""
账户体系 · 用户模型

内部白名单场景：账号由管理员用一次性脚本创建（scripts/create_user.py），
不做自助注册。密码用 bcrypt 哈希存储，永不明文落盘。
"""
from __future__ import annotations

import time
from typing import List, Optional

from pydantic import BaseModel, Field


class User(BaseModel):
    """单个用户账号（对外可见字段，不含密码哈希）"""
    user_id: str
    username: str
    display_name: str = ""
    is_admin: bool = False
    created_at: float = Field(default_factory=time.time)
    # 功能权限：细粒度勾选清单，key 见 app/auth/permissions.py。
    # is_admin=True 的账号绕过所有权限检查，这个字段对它无意义。
    permissions: List[str] = Field(default_factory=list)


class UserRecord(User):
    """存储态：额外带密码哈希，仅 UserStore 内部使用，不对外返回"""
    password_hash: str
