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

router = APIRouter(prefix="/scenarios", tags=["scenario-upload"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20MB，场景包只是文本+少量资源清单，够用
_NAME_RE = __import__("re").compile(r"^[A-Za-z0-9_\-]{1,64}$")


def _user_scenarios_root(user_id: str) -> Path:
    return Path("./user_data") / user_id / "scenarios"


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    """解压前逐条校验 entry 路径，防 zip slip（写到 dest 之外）"""
    dest_resolved = dest.resolve()
    for info in zf.infolist():
        name = info.filename
        if name.startswith("/") or name.startswith("\\") or ".." in Path(name).parts:
            raise HTTPException(400, f"压缩包内含非法路径，已拒绝: {name}")
        target = (dest / name).resolve()
        if dest_resolved != target and dest_resolved not in target.parents:
            raise HTTPException(400, f"压缩包内含非法路径，已拒绝: {name}")
    zf.extractall(dest)


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
    final_dir = user_root / scenario_name
    if final_dir.exists() and not overwrite:
        raise HTTPException(409, f"场景包 {scenario_name} 已存在，加 overwrite=true 覆盖")

    tmp_dir = user_root / f".tmp_{uuid.uuid4().hex[:10]}"
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
