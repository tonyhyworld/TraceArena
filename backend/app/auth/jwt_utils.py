"""
账户体系 · JWT 签发与校验

密钥优先读 backend/.env 的 AIWORLD_JWT_SECRET；不存在则生成一次并写回 .env
持久化（不要求每次重启都让旧 token 失效——内部工具场景下这个摩擦没必要）。
"""
from __future__ import annotations

import secrets
import time
from pathlib import Path
from typing import Optional

import jwt

from app.auth.models import User

ENV_PATH = Path(".env")
SECRET_KEY_NAME = "AIWORLD_JWT_SECRET"
ALGORITHM = "HS256"
DEFAULT_EXPIRE_HOURS = 24 * 7  # 内部工具，token 有效期放宽到 7 天


def _load_or_create_secret() -> str:
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(f"{SECRET_KEY_NAME}="):
                val = line.split("=", 1)[1].strip()
                if val:
                    return val
    # 不存在则生成一次并追加写回 .env，保证重启后依然有效
    new_secret = secrets.token_urlsafe(48)
    with ENV_PATH.open("a", encoding="utf-8") as f:
        f.write(f"\n{SECRET_KEY_NAME}={new_secret}\n")
    return new_secret


_SECRET = _load_or_create_secret()


def create_token(user: User, expires_hours: int = DEFAULT_EXPIRE_HOURS) -> str:
    now = time.time()
    payload = {
        "user_id": user.user_id,
        "username": user.username,
        "is_admin": user.is_admin,
        "iat": int(now),
        "exp": int(now + expires_hours * 3600),
    }
    return jwt.encode(payload, _SECRET, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """校验通过返回 payload dict，失败（过期/签名不对/格式错误）返回 None"""
    try:
        return jwt.decode(token, _SECRET, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
