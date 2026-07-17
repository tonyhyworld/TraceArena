"""
账户体系 · FastAPI 依赖注入

get_current_user 支持两种取 token 的方式：
- HTTP 请求：Authorization: Bearer <token> header
- WebSocket 握手：?token=<token> query 参数（浏览器原生 WS API 不支持自定义 header）
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException, Query

from app.auth.jwt_utils import decode_token
from app.auth.models import User
from app.auth.store import user_store


def _user_from_payload(payload: Optional[dict]) -> Optional[User]:
    if not payload:
        return None
    user = user_store.get_by_id(payload.get("user_id", ""))
    return user


async def get_current_user(
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
) -> User:
    """HTTP 路由用：Authorization header 优先，其次 query token"""
    raw = None
    if authorization and authorization.lower().startswith("bearer "):
        raw = authorization[7:].strip()
    elif token:
        raw = token
    if not raw:
        raise HTTPException(status_code=401, detail="未登录：缺少 token")
    payload = decode_token(raw)
    user = _user_from_payload(payload)
    if user is None:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    return user


def decode_ws_token(token: Optional[str]) -> Optional[User]:
    """WebSocket 端点用：握手阶段拿不到 FastAPI Depends，手动校验 token"""
    if not token:
        return None
    payload = decode_token(token)
    return _user_from_payload(payload)


def require_permission(perm: str):
    """功能权限依赖工厂。is_admin 账号绕过所有检查（视为拥有全部权限）。"""
    async def _dep(user: User = Depends(get_current_user)) -> User:
        if user.is_admin or perm in user.permissions:
            return user
        raise HTTPException(status_code=403, detail=f"无权限: {perm}")
    return _dep


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
