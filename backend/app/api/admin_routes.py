"""
账户体系 · 用户/权限管理接口

只有 `is_admin` 能创建账号、改别人的权限——这是权限体系的根节点，不做成
可下放的权限（下放会形成提权链条：被授权者可以给自己勾满权限）。

不提供"设为管理员"的操作：超管身份变更只走后端手动改数据，不放进 UI，
避免误操作产生多个超管。
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_user, require_admin
from app.auth.models import User
from app.auth.permissions import ALL_PERMISSION_KEYS, PERMISSION_CATALOG
from app.auth.store import user_store

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/permissions/catalog")
async def permissions_catalog(user: User = Depends(get_current_user)):
    """权限清单本身不敏感，登录即可读——管理页面靠它渲染勾选框。"""
    return PERMISSION_CATALOG


@router.get("/users")
async def list_users(admin: User = Depends(require_admin)) -> List[User]:
    return user_store.list_users()


class CreateUserRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""
    permissions: List[str] = []


@router.post("/users")
async def create_user(body: CreateUserRequest, admin: User = Depends(require_admin)) -> User:
    invalid = set(body.permissions) - set(ALL_PERMISSION_KEYS)
    if invalid:
        raise HTTPException(400, f"未知权限: {sorted(invalid)}")
    try:
        return user_store.create_user(
            username=body.username, password=body.password,
            display_name=body.display_name, permissions=body.permissions,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))


class UpdatePermissionsRequest(BaseModel):
    permissions: List[str]


class UpdateUserRequest(BaseModel):
    display_name: Optional[str] = None
    permissions: Optional[List[str]] = Field(default=None)


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str, body: UpdateUserRequest, admin: User = Depends(require_admin),
) -> User:
    target = user_store.get_by_id(user_id)
    if target is None:
        raise HTTPException(404, "用户不存在")
    if target.is_admin:
        raise HTTPException(400, "超级管理员不可编辑")
    if body.permissions is not None:
        invalid = set(body.permissions) - set(ALL_PERMISSION_KEYS)
        if invalid:
            raise HTTPException(400, f"未知权限: {sorted(invalid)}")
    try:
        return user_store.update_user(
            user_id,
            display_name=body.display_name,
            permissions=body.permissions,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.patch("/users/{user_id}/permissions")
async def update_user_permissions(
    user_id: str, body: UpdatePermissionsRequest, admin: User = Depends(require_admin),
) -> User:
    target = user_store.get_by_id(user_id)
    if target is None:
        raise HTTPException(404, "用户不存在")
    if target.is_admin:
        raise HTTPException(400, "管理员权限不可通过此接口修改")
    invalid = set(body.permissions) - set(ALL_PERMISSION_KEYS)
    if invalid:
        raise HTTPException(400, f"未知权限: {sorted(invalid)}")
    return user_store.update_permissions(user_id, body.permissions)


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str, admin: User = Depends(require_admin),
) -> dict:
    if admin.user_id == user_id:
        raise HTTPException(400, "不能删除当前登录账号")
    target = user_store.get_by_id(user_id)
    if target is None:
        raise HTTPException(404, "用户不存在")
    if target.is_admin:
        raise HTTPException(400, "不能删除超级管理员")
    try:
        user_store.delete_user(user_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"status": "deleted", "user_id": user_id}


class SetPasswordRequest(BaseModel):
    new_password: str


@router.patch("/users/{user_id}/password")
async def reset_user_password(
    user_id: str, body: SetPasswordRequest, admin: User = Depends(require_admin),
) -> dict:
    if len(body.new_password) < 6:
        raise HTTPException(400, "密码至少 6 位")
    target = user_store.get_by_id(user_id)
    if target is None:
        raise HTTPException(404, "用户不存在")
    user_store.set_password(user_id, body.new_password)
    return {"status": "ok"}
