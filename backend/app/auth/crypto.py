"""
账户体系 · 静态加密主密钥管理（用于 BYOK API Key 落盘加密）

用户自带的 API Key（BYOK）此前以明文写入 user_data/<user_id>/secrets.json。
虽然该目录已 .gitignore 且权限收紧到 0600，但明文落盘在「磁盘/备份泄露」下仍是
风险。这里引入对称加密（Fernet = AES-128-CBC + HMAC-SHA256 认证）：

- 主密钥只从环境变量 AIWORLD_SECRET_KEY 读取。部署者必须显式持久化该值，
  应用不会把主密钥自动写入本地文件。
- 主密钥本身仍在同机 .env 上，因此这层加密防的是「secrets.json 单独泄露/被误提交/
  进备份」，而非「攻击者已拿到整机」。这是内部工具场景下合理的威胁模型权衡。
"""
from __future__ import annotations

import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

SECRET_KEY_NAME = "AIWORLD_SECRET_KEY"


def _load_key() -> bytes:
    value = os.environ.get(SECRET_KEY_NAME, "").strip()
    if not value:
        raise RuntimeError(
            f"{SECRET_KEY_NAME} must be set to a persistent Fernet key"
        )
    key = value.encode("utf-8")
    try:
        Fernet(key)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f"{SECRET_KEY_NAME} is not a valid Fernet key") from exc
    return key


_cipher: Optional[Fernet] = None


def _get_cipher() -> Fernet:
    global _cipher
    if _cipher is None:
        _cipher = Fernet(_load_key())
    return _cipher


def encrypt(plaintext: str) -> str:
    """明文 → 密文 token（url-safe base64 字符串）"""
    return _get_cipher().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> Optional[str]:
    """密文 token → 明文；不是本密钥签发的合法密文（如旧明文）时返回 None"""
    try:
        return _get_cipher().decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        return None
