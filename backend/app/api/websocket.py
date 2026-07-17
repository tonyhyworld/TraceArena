"""
WebSocket 连接管理（按用户 + 双频道）

viewer   频道：渲染层订阅，接收 world_snapshot + presentation_segment
operator 频道：运营台订阅，接收全量数据（含 agent_log、秘密事件）

多用户隔离：连接按 user_id 分组，广播只发给该用户自己的连接，
不会把用户 A 的对局广播给用户 B（即使两人同时都开着 viewer 页面）。

客户端连接时指定频道 + token：ws://host/ws?channel=viewer|operator&token=<jwt>
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """管理所有 WebSocket 连接，按 user_id → 频道 分组广播"""

    def __init__(self):
        self._conns: Dict[str, Dict[str, Set[WebSocket]]] = {}
        # 缓存该用户当前登录态的权限快照（user_id → permission set）。
        # WebSocket 命令鉴权用：握手时写入，最后一个连接断开时清理。
        # 存权限集合而非 User 对象，避免持有过期引用；权限变更下次握手即刷新。
        self._perms: Dict[str, Set[str]] = {}
        self._admin: Set[str] = set()

    def _bucket(self, user_id: str) -> Dict[str, Set[WebSocket]]:
        return self._conns.setdefault(user_id, {"viewer": set(), "operator": set()})

    async def connect(
        self,
        ws: WebSocket,
        user_id: str,
        channel: str,
        *,
        permissions: Set[str] | None = None,
        is_admin: bool = False,
    ) -> None:
        await ws.accept()
        ch = channel if channel in ("viewer", "operator") else "viewer"
        self._bucket(user_id)[ch].add(ws)
        # 每次握手都用最新登录态刷新权限快照
        self._perms[user_id] = set(permissions or set())
        if is_admin:
            self._admin.add(user_id)
        else:
            self._admin.discard(user_id)
        logger.info(f"[ws] 新连接 user={user_id} channel={ch}，当前连接数: {self._count()}")

    def disconnect(self, ws: WebSocket, user_id: str) -> None:
        bucket = self._conns.get(user_id)
        if not bucket:
            return
        for conns in bucket.values():
            conns.discard(ws)
        # 该用户已无任何活跃连接时，清理权限快照，避免脏数据长期驻留
        if not any(conns for conns in bucket.values()):
            self._perms.pop(user_id, None)
            self._admin.discard(user_id)
        logger.info(f"[ws] 断开连接 user={user_id}，剩余: {self._count()}")

    def can(self, user_id: str, permission: str) -> bool:
        """WebSocket 命令鉴权：is_admin 绕过；否则查权限快照。

        与 REST 侧 require_permission 语义保持一致。
        """
        if user_id in self._admin:
            return True
        return permission in self._perms.get(user_id, set())

    async def broadcast(self, user_id: str, channel: str, data: Dict[str, Any]) -> None:
        """只广播给该 user_id 自己的连接，不再是全局广播"""
        bucket = self._conns.get(user_id)
        if not bucket:
            return

        targets: Set[WebSocket] = set()
        if channel == "viewer":
            targets = bucket["viewer"] | bucket["operator"]
        elif channel == "operator":
            targets = bucket["operator"]

        if not targets:
            return

        msg = json.dumps(data, ensure_ascii=False, default=str)
        dead: Set[WebSocket] = set()
        for ws in targets:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.disconnect(ws, user_id)

    async def send_to(self, ws: WebSocket, data: Dict[str, Any]) -> None:
        """向单个连接发送消息（用于初始化快照）"""
        try:
            await ws.send_text(json.dumps(data, ensure_ascii=False, default=str))
        except Exception:
            pass

    def _count(self) -> int:
        return sum(len(s) for bucket in self._conns.values() for s in bucket.values())


# 全局连接管理器（由 main.py 创建）——本身不含 user 状态，天然可以是单例
manager: ConnectionManager = ConnectionManager()
