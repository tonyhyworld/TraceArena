"""
账户体系 · JWT 签发与校验

密钥只从环境变量 AIWORLD_JWT_SECRET 读取。部署者必须显式提供长期随机值，
避免应用在可被误备份或误提交的文件中自动落盘认证密钥。
"""
from __future__ import annotations

import os
import time
from typing import Optional

import jwt

from app.auth.models import User

SECRET_KEY_NAME = "AIWORLD_JWT_SECRET"
ALGORITHM = "HS256"
DEFAULT_EXPIRE_HOURS = 24 * 7  # 内部工具，token 有效期放宽到 7 天


def _get_secret() -> str:
    value = os.environ.get(SECRET_KEY_NAME, "").strip()
    if len(value) < 32:
        raise RuntimeError(
            f"{SECRET_KEY_NAME} must be set to a private random value of at least 32 characters"
        )
    return value


def create_token(user: User, expires_hours: int = DEFAULT_EXPIRE_HOURS) -> str:
    now = time.time()
    payload = {
        "user_id": user.user_id,
        "username": user.username,
        "is_admin": user.is_admin,
        "iat": int(now),
        "exp": int(now + expires_hours * 3600),
    }
    return jwt.encode(payload, _get_secret(), algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """校验通过返回 payload dict，失败（过期/签名不对/格式错误）返回 None"""
    try:
        return jwt.decode(token, _get_secret(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
