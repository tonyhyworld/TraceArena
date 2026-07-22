"""
账户体系 · 场景包上传

用户上传自己的场景包 zip，服务端解压到临时目录、跑一遍已有的
ScenarioBootKernel.load() + validate() 校验，通过才落到该用户的
私有场景目录（user_data/<user_id>/scenarios/<name>/），不通过则整个
临时目录删除并把具体错误返回给前端。

安全要点：
- zip 内每个 entry 路径必须校验不含 ".."、不是绝对路径，解压后确认
  最终落地路径仍在临时目录之内——防止 zip slip 路径穿越写到任意位置。
- 文件大小上限，避免超大 zip 撑爆磁盘。
"""
from __future__ import annotations

import shutil
import stat
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile

from app.auth.dependencies import require_permission
from app.auth.models import User
from app.auth.permissions import Permission
from app.core.exceptions import ScenarioLoadError
from app.engine.scenario_boot.loader import ScenarioBootKernel
from app.core.path_safety import path_beneath

router = APIRouter(prefix="/scenarios", tags=["scenario-upload"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20MB，场景包只是文本+少量资源清单，够用
MAX_EXTRACTED_BYTES = 100 * 1024 * 1024
_NAME_RE = __import__("re").compile(r"^[A-Za-z0-9_\-]{1,64}$")


def _user_scenarios_root(user_id: str) -> Path:
    return path_beneath("./user_data", user_id, "scenarios")


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    """逐项解压普通文件，拒绝路径穿越、符号链接和特殊文件。"""
    dest_resolved = dest.resolve()
    total_size = sum(info.file_size for info in zf.infolist() if not info.is_dir())
    if total_size > MAX_EXTRACTED_BYTES:
        raise HTTPException(400, "压缩包解压后体积超过 100MB，已拒绝")
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        parts = [part for part in name.split("/") if part]
        mode = info.external_attr >> 16
        file_type = stat.S_IFMT(mode)
        if (
            not parts
            or name.startswith("/")
            or "\x00" in name
            or ":" in parts[0]
            or any(part in {".", ".."} for part in parts)
            or stat.S_ISLNK(mode)
            or file_type not in {0, stat.S_IFREG, stat.S_IFDIR}
        ):
            raise HTTPException(400, f"压缩包内含非法路径，已拒绝: {name}")
        target = dest_resolved.joinpath(*parts).resolve()
        try:
            target.relative_to(dest_resolved)
        except ValueError as exc:
            raise HTTPException(400, f"压缩包内含非法路径，已拒绝: {name}") from exc
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.is_symlink():
            raise HTTPException(400, f"压缩包内含非法路径，已拒绝: {name}")
        with zf.open(info, "r") as source, target.open("wb") as output:
            shutil.copyfileobj(source, output)


def _find_scenario_root(extract_dir: Path) -> Path:
    """zip 里可能是「直接就是场景包内容」或「外面套一层文件夹」，
    找到真正含 manifest.json 的那一层。"""
    if (extract_dir / "manifest.json").is_file():
        return extract_dir
    candidates = [d for d in extract_dir.iterdir() if d.is_dir() and (d / "manifest.json").is_file()]
    if len(candidates) == 1:
        return candidates[0]
    raise HTTPException(400, "压缩包内找不到 manifest.json（应位于场景包根目录）")


@router.post("/upload")
async def upload_scenario(
    file: UploadFile,
    scenario_name: str = Query(..., description="场景包目录名，仅字母数字下划线横杠"),
    overwrite: bool = Query(False),
    user: User = Depends(require_permission(Permission.MANAGE_SCENARIO)),
) -> Dict[str, Any]:
    if not _NAME_RE.match(scenario_name):
        raise HTTPException(400, "scenario_name 只能包含字母/数字/下划线/横杠，长度 1-64")
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, "只接受 .zip 文件")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"文件过大，上限 {MAX_UPLOAD_BYTES // 1024 // 1024}MB")

    user_root = _user_scenarios_root(user.user_id)
    user_root.mkdir(parents=True, exist_ok=True)
    final_dir = path_beneath(user_root, scenario_name)
    if final_dir.exists() and not overwrite:
        raise HTTPException(409, f"场景包 {scenario_name} 已存在，加 overwrite=true 覆盖")

    tmp_dir = path_beneath(user_root, f"tmp_{uuid.uuid4().hex[:10]}")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        import io
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                _safe_extract(zf, tmp_dir)
        except zipfile.BadZipFile:
            raise HTTPException(400, "不是合法的 zip 文件")

        scenario_root = _find_scenario_root(tmp_dir)

        try:
            scenario = ScenarioBootKernel.load(str(scenario_root))
        except ScenarioLoadError as exc:
            raise HTTPException(400, f"场景包结构错误: {exc}")

        warnings: List[str] = ScenarioBootKernel.validate(scenario)
        if warnings:
            raise HTTPException(400, "场景包校验未通过：\n" + "\n".join(warnings[:20]))

        if final_dir.exists():
            shutil.rmtree(final_dir)
        # scenario_root 可能等于 tmp_dir，也可能是 tmp_dir 下的子目录（zip 套了一层）
        shutil.move(str(scenario_root), str(final_dir))
        return {
            "status": "uploaded",
            "scenario_name": scenario_name,
            "manifest_name": scenario.manifest.name,
            "manifest_version": scenario.manifest.version,
        }
    finally:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
