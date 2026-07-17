"""
账户体系 · 登录接口

内部白名单场景：不做自助注册，账号由管理员用 scripts/create_user.py 预先创建。
"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.dependencies import get_current_user
from app.auth.jwt_utils import create_token
from app.auth.models import User
from app.auth.store import user_store

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user_id: str
    username: str
    display_name: str
    is_admin: bool
    permissions: List[str] = []


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest) -> LoginResponse:
    user = user_store.verify_password(body.username, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_token(user)
    return LoginResponse(
        token=token, user_id=user.user_id, username=user.username,
        display_name=user.display_name, is_admin=user.is_admin,
        permissions=user.permissions,
    )


@router.get("/me", response_model=User)
async def me(user: User = Depends(get_current_user)) -> User:
    return user


class ChangePasswordRequest(BaseModel):
    new_password: str


@router.patch("/me/password")
async def change_my_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
) -> dict:
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 位")
    user_store.set_password(user.user_id, body.new_password)
    return {"status": "ok"}
