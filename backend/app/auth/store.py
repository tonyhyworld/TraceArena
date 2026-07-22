"""
账户体系 · 用户表存储

内部小规模团队场景：用一个 JSON 文件当用户表，不引入数据库。
写入用"临时文件 + os.replace"做原子替换，防止并发写坏文件。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional

import bcrypt

from app.auth.models import User, UserRecord
from app.core.path_safety import safe_path_component

logger = logging.getLogger(__name__)

USER_DATA_ROOT = Path(os.environ.get("AIWORLD_USER_DATA_ROOT", "./user_data"))
USERS_FILE = USER_DATA_ROOT / "users.json"

_VALID_USERNAME = re.compile(r"^[a-zA-Z0-9_\-]{3,32}$")


class UserStore:
    """用户表的读写入口。单进程内用一把锁保护，够内部团队规模用。"""

    def __init__(self, path: Path = USERS_FILE):
        self._path = path
        self._lock = Lock()

    def _load(self) -> Dict[str, dict]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as e:
            # 原子写入（tmp + os.replace）理论上不会写出半截文件，走到这里通常意味着
            # 文件被外部破坏。绝不能静默当成空表——否则后续写入会用新数据覆盖、
            # 丢掉全部既有账号。大声告警，交由运维决定是否从备份恢复。
            logger.error(f"[UserStore] 用户表读取失败（疑似损坏）: {self._path}: {e}")
            return {}

    def _save(self, data: Dict[str, dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)  # 原子替换，避免并发写入时读到半截文件

    def create_user(
        self, username: str, password: str, *, display_name: str = "",
        is_admin: bool = False, user_id: Optional[str] = None,
        permissions: Optional[List[str]] = None,
    ) -> User:
        if not _VALID_USERNAME.match(username):
            raise ValueError("用户名只能包含字母/数字/下划线/横杠，长度 3-32")
        with self._lock:
            data = self._load()
            if any(u.get("username") == username for u in data.values()):
                raise ValueError(f"用户名已存在: {username}")
            uid = safe_path_component(
                user_id or f"u_{uuid.uuid4().hex[:12]}", label="user_id"
            )
            password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            record = UserRecord(
                user_id=uid, username=username, password_hash=password_hash,
                display_name=display_name or username, is_admin=is_admin,
                created_at=time.time(), permissions=permissions or [],
            )
            data[uid] = record.model_dump()
            self._save(data)
            return User(**record.model_dump(exclude={"password_hash"}))

    def get_by_username(self, username: str) -> Optional[UserRecord]:
        data = self._load()
        for raw in data.values():
            if raw.get("username") == username:
                return UserRecord(**raw)
        return None

    def get_by_id(self, user_id: str) -> Optional[User]:
        data = self._load()
        raw = data.get(user_id)
        if not raw:
            return None
        return User(**{k: v for k, v in raw.items() if k != "password_hash"})

    def verify_password(self, username: str, password: str) -> Optional[User]:
        """校验用户名+密码，成功返回不含密码哈希的 User，失败返回 None"""
        record = self.get_by_username(username)
        if record is None:
            return None
        if not bcrypt.checkpw(password.encode("utf-8"), record.password_hash.encode("utf-8")):
            return None
        return User(**record.model_dump(exclude={"password_hash"}))

    def user_exists(self, username: str) -> bool:
        return self.get_by_username(username) is not None

    def list_users(self) -> List[User]:
        data = self._load()
        return [
            User(**{k: v for k, v in raw.items() if k != "password_hash"})
            for raw in data.values()
        ]

    def update_permissions(self, user_id: str, permissions: List[str]) -> User:
        """管理员改某个用户的功能权限清单。读-改-写全在锁内完成，避免并发覆盖。"""
        with self._lock:
            data = self._load()
            raw = data.get(user_id)
            if not raw:
                raise ValueError(f"用户不存在: {user_id}")
            raw["permissions"] = permissions
            self._save(data)
            return User(**{k: v for k, v in raw.items() if k != "password_hash"})

    def set_password(self, user_id: str, new_password: str) -> None:
        with self._lock:
            data = self._load()
            raw = data.get(user_id)
            if not raw:
                raise ValueError(f"用户不存在: {user_id}")
            raw["password_hash"] = bcrypt.hashpw(
                new_password.encode("utf-8"), bcrypt.gensalt()
            ).decode("utf-8")
            self._save(data)

    def update_user(
        self,
        user_id: str,
        *,
        display_name: Optional[str] = None,
        permissions: Optional[List[str]] = None,
    ) -> User:
        with self._lock:
            data = self._load()
            raw = data.get(user_id)
            if not raw:
                raise ValueError(f"用户不存在: {user_id}")
            if raw.get("is_admin"):
                raise ValueError("超级管理员不可通过此接口修改")
            if display_name is not None:
                raw["display_name"] = display_name.strip() or raw.get("username", "")
            if permissions is not None:
                raw["permissions"] = permissions
            self._save(data)
            return User(**{k: v for k, v in raw.items() if k != "password_hash"})

    def delete_user(self, user_id: str) -> None:
        with self._lock:
            data = self._load()
            raw = data.get(user_id)
            if not raw:
                raise ValueError(f"用户不存在: {user_id}")
            if raw.get("is_admin"):
                raise ValueError("不能删除超级管理员账号")
            del data[user_id]
            self._save(data)


# 模块级单例：整个进程共用一份用户表句柄
user_store = UserStore()
