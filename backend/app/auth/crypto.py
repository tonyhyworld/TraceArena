"""
账户体系 · 静态加密主密钥管理（用于 BYOK API Key 落盘加密）

用户自带的 API Key（BYOK）此前以明文写入 user_data/<user_id>/secrets.json。
虽然该目录已 .gitignore 且权限收紧到 0600，但明文落盘在「磁盘/备份泄露」下仍是
风险。这里引入对称加密（Fernet = AES-128-CBC + HMAC-SHA256 认证）：

- 主密钥优先读 backend/.env 的 AIWORLD_SECRET_KEY；不存在则生成一次并写回 .env
  持久化（与 JWT 密钥同款做法，避免重启后旧密文解不开）。
- 主密钥本身仍在同机 .env 上，因此这层加密防的是「secrets.json 单独泄露/被误提交/
  进备份」，而非「攻击者已拿到整机」。这是内部工具场景下合理的威胁模型权衡。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

ENV_PATH = Path(".env")
SECRET_KEY_NAME = "AIWORLD_SECRET_KEY"


def _load_or_create_key() -> bytes:
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(f"{SECRET_KEY_NAME}="):
                val = line.split("=", 1)[1].strip()
                if val:
                    return val.encode("utf-8")
    # 不存在则生成一次并追加写回 .env，保证重启后依然能解开旧密文
    new_key = Fernet.generate_key()
    with ENV_PATH.open("a", encoding="utf-8") as f:
        f.write(f"\n{SECRET_KEY_NAME}={new_key.decode('utf-8')}\n")
    return new_key


_cipher: Optional[Fernet] = None


def _get_cipher() -> Fernet:
    global _cipher
    if _cipher is None:
        _cipher = Fernet(_load_or_create_key())
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
