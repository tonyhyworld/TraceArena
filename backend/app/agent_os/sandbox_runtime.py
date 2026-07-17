"""Lightweight per-agent sandbox and Python environment management.

The sandbox is an AI World runtime boundary, not a hostile multi-tenant
security container. Each agent gets an isolated workspace, Python environment,
capability registry, environment variables, execution process and audit log.
It never receives direct World Kernel mutation APIs.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import platform
import re
import resource
import shutil
import subprocess
import sys
import time
import venv
from pathlib import Path
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


_PYTHON_AUDIT_GUARD = r'''"""Injected by AI World before untrusted agent code starts."""
import os
import sys

_READ_ROOTS = tuple(
    os.path.realpath(item)
    for item in os.environ.get("AI_WORLD_SANDBOX_READ_ROOTS", "").split(os.pathsep)
    if item
)
_WRITE_ROOTS = tuple(
    os.path.realpath(item)
    for item in os.environ.get("AI_WORLD_SANDBOX_WRITE_ROOTS", "").split(os.pathsep)
    if item
)
_NETWORK = os.environ.get("AI_WORLD_SANDBOX_NETWORK", "0") == "1"
_BLOCKED_IMPORTS = {"ctypes", "cffi", "subprocess", "multiprocessing", "pty"}


def _inside(path, roots):
    if isinstance(path, int):
        return True
    try:
        resolved = os.path.realpath(os.fspath(path))
    except (TypeError, ValueError):
        return False
    for root in roots:
        try:
            if os.path.commonpath((resolved, root)) == root:
                return True
        except ValueError:
            continue
    return False


def _require(path, roots, operation):
    if not _inside(path, roots):
        raise PermissionError("agent_sandbox_denied:%s" % operation)


def _audit(event, args):
    if event == "open" and args:
        path = args[0]
        mode = str(args[1] if len(args) > 1 else "r")
        write = any(flag in mode for flag in ("w", "a", "+", "x"))
        _require(path, _WRITE_ROOTS if write else _READ_ROOTS, "open")
        return
    if event in {"os.remove", "os.rmdir", "os.mkdir", "os.chdir", "os.chmod", "os.chown", "os.truncate"} and args:
        _require(args[0], _WRITE_ROOTS, event)
        return
    if event in {"os.rename", "os.replace"} and len(args) >= 2:
        _require(args[0], _WRITE_ROOTS, event)
        _require(args[1], _WRITE_ROOTS, event)
        return
    if event.startswith("subprocess.") or event in {"os.system", "os.posix_spawn", "pty.spawn"} or event.startswith("os.exec"):
        raise PermissionError("agent_sandbox_denied:subprocess")
    if not _NETWORK and event in {"socket.connect", "socket.connect_ex", "socket.bind", "socket.getaddrinfo"}:
        raise PermissionError("agent_sandbox_denied:network")
    if event == "import" and args:
        root = str(args[0] or "").split(".", 1)[0]
        if root in _BLOCKED_IMPORTS:
            raise PermissionError("agent_sandbox_denied:import:" + root)


sys.addaudithook(_audit)
'''


_PACKAGE_SPEC_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]*"
    r"(?:\[[A-Za-z0-9_,.-]+\])?"
    r"(?:(?:==|>=|<=|~=|>|<)[A-Za-z0-9.*+!_-]+)?$"
)
_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class SandboxPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: Literal["auto", "sandbox_exec", "python_audit", "process"] = "auto"
    allow_network: bool = False
    allow_package_install: bool = False
    command_timeout_sec: float = Field(default=30.0, gt=0)
    install_timeout_sec: float = Field(default=120.0, gt=0)
    max_output_bytes: int = Field(default=131072, ge=1024)


class SandboxCommandResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    command_kind: str
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    errors: List[str] = Field(default_factory=list)
    duration_ms: int = Field(default=0, ge=0)


class AgentProcessSandbox:
    """Independent workspace and Python environment for one agent."""

    def __init__(self, root: Path, agent_id: str, policy: SandboxPolicy):
        self.agent_id = agent_id
        self.root = root.resolve()
        self.policy = policy
        self.home_dir = self.root / "home"
        self.workspace_dir = self.root / "workspace"
        self.cache_dir = self.root / "cache"
        self.policy_dir = self.root / ".policy"
        self.venv_dir = self.root / ".venv"
        self.capabilities_path = self.root / "capabilities.json"
        self.operations_path = self.root / "operations.jsonl"
        for path in (self.home_dir, self.workspace_dir, self.cache_dir, self.policy_dir):
            path.mkdir(parents=True, exist_ok=True)
        self.backend = self._resolve_backend(policy.backend)
        # 首次执行 python 前用真实策略跑一次健康检查（_resolve_backend 的
        # 探针只测 (allow default)，检不出真实 deny-default profile 的问题——
        # 真实发生过：profile 缺少解释器真身所在目录的读权限，所有 agent
        # 代码瞬间以 exit 71 死亡且无任何输出，agent 完全无法自解释）。
        self._backend_health_checked = False
        if self.backend == "process":
            logger.warning(
                "[AgentSandbox] agent=%s 使用轻量进程隔离；工作区和虚拟环境独立，"
                "但不具备容器级文件系统安全边界",
                agent_id,
            )

    @property
    def python_path(self) -> Path:
        name = "python.exe" if os.name == "nt" else "python"
        folder = "Scripts" if os.name == "nt" else "bin"
        return self.venv_dir / folder / name

    @property
    def isolation_scope(self) -> str:
        return "agent"

    def list_capabilities(self) -> List[Dict[str, object]]:
        if not self.capabilities_path.is_file():
            return []
        try:
            payload = json.loads(self.capabilities_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return list(payload) if isinstance(payload, list) else []

    def register_capability(self, capability: Dict[str, object]) -> None:
        capability_id = str(capability.get("capability_id") or "").strip()
        if not capability_id:
            raise ValueError("capability_id_required")
        current = {
            str(item.get("capability_id")): item
            for item in self.list_capabilities()
            if isinstance(item, dict) and item.get("capability_id")
        }
        current[capability_id] = dict(capability)
        self.capabilities_path.write_text(
            json.dumps(
                list(current.values()), ensure_ascii=False, indent=2, default=str
            ),
            encoding="utf-8",
        )
        self._record_operation("capability_registered", {"capability_id": capability_id})

    async def ensure_python_environment(self) -> Path:
        if self.python_path.is_file():
            return self.python_path

        def _create() -> None:
            # 不预装 pip：每个 agent 沙箱都带全套 pip 会让每局 run 目录
            # 膨胀十几 MB 纯样板文件。真正需要装包时（install_python）
            # 再用 ensurepip 补，一次性成本相同。
            builder = venv.EnvBuilder(with_pip=False, clear=False, symlinks=True)
            builder.create(self.venv_dir)

        await asyncio.to_thread(_create)
        if not self.python_path.is_file():
            raise RuntimeError("python_environment_creation_failed")
        return self.python_path

    async def _ensure_pip(self, python: Path) -> Optional[SandboxCommandResult]:
        """venv 默认不带 pip；首次装包前补装。失败返回失败结果，成功返回 None。"""
        probe = await self._run_command(
            [str(python), "-c", "import pip"],
            command_kind="python_run",
            timeout_sec=min(15.0, self.policy.command_timeout_sec),
            network=False,
        )
        if probe.ok:
            return None
        bootstrap = await self._run_command(
            [str(python), "-m", "ensurepip", "--upgrade", "--default-pip"],
            command_kind="python_install",
            timeout_sec=self.policy.install_timeout_sec,
            network=False,
        )
        if bootstrap.ok:
            return None
        bootstrap.errors.append("pip_bootstrap_failed")
        return bootstrap

    async def install_python(self, packages: List[str]) -> SandboxCommandResult:
        if not self.policy.allow_package_install:
            # 拒绝也要留痕——排障时"没有任何 python_install 记录"曾被误判
            # 为"从未尝试安装"。
            self._record_operation(
                "python_install",
                {"packages": list(packages or []), "ok": False,
                 "errors": ["package_install_disabled"]},
            )
            return SandboxCommandResult(
                ok=False,
                command_kind="python_install",
                errors=["package_install_disabled"],
            )
        specs = [str(item or "").strip() for item in packages]
        invalid = [item for item in specs if not _PACKAGE_SPEC_RE.fullmatch(item)]
        if not specs or invalid:
            return SandboxCommandResult(
                ok=False,
                command_kind="python_install",
                errors=[f"invalid_package_spec:{item}" for item in (invalid or specs)],
            )
        python = await self.ensure_python_environment()
        await self.ensure_backend_health()
        pip_failure = await self._ensure_pip(python)
        if pip_failure is not None:
            self._record_operation(
                "python_install",
                {"packages": specs, "ok": False, "errors": pip_failure.errors},
            )
            return pip_failure
        result = await self._run_command(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-input",
                *specs,
            ],
            command_kind="python_install",
            timeout_sec=self.policy.install_timeout_sec,
            network=self.policy.allow_network,
        )
        if result.ok:
            freeze = await self._run_command(
                [str(python), "-m", "pip", "freeze"],
                command_kind="python_freeze",
                timeout_sec=self.policy.command_timeout_sec,
                network=False,
            )
            if freeze.ok:
                (self.root / "requirements.lock").write_text(
                    freeze.stdout, encoding="utf-8"
                )
            for spec in specs:
                package_name = re.split(r"[<>=~!]", spec, maxsplit=1)[0]
                self.register_capability({
                    "capability_id": f"python:{package_name}",
                    "kind": "python_package",
                    "name": package_name,
                    "install_spec": spec,
                    "source": "private_python_environment",
                })
        self._record_operation(
            "python_install",
            {"packages": specs, "ok": result.ok, "errors": result.errors},
        )
        return result

    async def ensure_backend_health(self) -> None:
        """用真实执行策略跑一次最小 python，坏后端自动降级。

        sandbox_exec 的 profile 在某些机器上会拦死解释器本体（表现为任何
        脚本瞬间退出、stdout/stderr 全空），此时降级到 python_audit——
        仍有文件/网络/子进程审计边界，但不依赖 OS 级 profile。
        """
        if self._backend_health_checked:
            return
        self._backend_health_checked = True
        if self.backend not in ("sandbox_exec", "python_audit"):
            return
        python = await self.ensure_python_environment()
        probe = await self._run_command(
            [str(python), "-c", "print('sandbox_ok')"],
            command_kind="python_run",
            timeout_sec=min(10.0, self.policy.command_timeout_sec),
            network=False,
        )
        if probe.ok and "sandbox_ok" in probe.stdout:
            return
        if self.backend == "sandbox_exec":
            logger.warning(
                "[AgentSandbox] agent=%s sandbox_exec 健康检查失败"
                "（exit=%s stderr=%r），自动降级 python_audit",
                self.agent_id, probe.exit_code, probe.stderr[:200],
            )
            self.backend = "python_audit"
            self._record_operation(
                "sandbox_backend_fallback",
                {"from": "sandbox_exec", "to": "python_audit",
                 "probe_exit": probe.exit_code},
            )
            retry = await self._run_command(
                [str(python), "-c", "print('sandbox_ok')"],
                command_kind="python_run",
                timeout_sec=min(10.0, self.policy.command_timeout_sec),
                network=False,
            )
            if retry.ok and "sandbox_ok" in retry.stdout:
                return
            probe = retry
        logger.error(
            "[AgentSandbox] agent=%s 沙箱后端 %s 健康检查仍失败"
            "（exit=%s），agent 代码路线不可用",
            self.agent_id, self.backend, probe.exit_code,
        )

    async def run_python_file(
        self,
        relative_path: str,
        args: Optional[List[str]] = None,
    ) -> SandboxCommandResult:
        script = self._workspace_path(relative_path)
        if not script.is_file():
            return SandboxCommandResult(
                ok=False,
                command_kind="python_run",
                errors=[f"script_not_found:{relative_path}"],
            )
        await self.ensure_backend_health()
        python = await self.ensure_python_environment()
        result = await self._run_command(
            [str(python), str(script), *(args or [])],
            command_kind="python_run",
            timeout_sec=self.policy.command_timeout_sec,
            network=self.policy.allow_network,
        )
        if (
            not result.ok
            and not (result.stdout or "").strip()
            and not (result.stderr or "").strip()
        ):
            # 无任何输出的失败大概率是沙箱环境问题而非用户代码问题——
            # 如实告知，agent 才不会在"改代码"上白白打转。
            result.errors.append("sandbox_environment_failure_suspected")
        self._record_operation(
            "python_run",
            {"path": relative_path, "ok": result.ok, "errors": result.errors},
        )
        return result

    def write_workspace_file(self, relative_path: str, content: str) -> Path:
        path = self._workspace_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self._record_operation(
            "workspace_write",
            {"path": str(path.relative_to(self.workspace_dir))},
        )
        return path

    def snapshot(self) -> Dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "sandbox_id": f"sandbox:{self.agent_id}",
            "scope": self.isolation_scope,
            "backend": self.backend,
            "isolation_enforced": self.backend in {"sandbox_exec", "python_audit"},
            "security_level": (
                "os_policy" if self.backend == "sandbox_exec"
                else "python_audit_policy" if self.backend == "python_audit"
                else "cooperative_process"
            ),
            "network_allowed": self.policy.allow_network,
            "package_install_allowed": self.policy.allow_package_install,
            "limitations": (
                [] if self.backend == "sandbox_exec" else
                ["no_kernel_namespace_boundary", "python_execution_only"]
                if self.backend == "python_audit" else
                ["no_container_filesystem_boundary"]
            ),
            "workspace": str(self.workspace_dir),
            "python_environment": str(self.venv_dir),
            "capabilities": self.list_capabilities(),
            "requirements_lock": str(self.root / "requirements.lock"),
        }

    def _workspace_path(self, relative_path: str) -> Path:
        raw = Path(str(relative_path or ""))
        if raw.is_absolute():
            raise ValueError("absolute_workspace_path_forbidden")
        resolved = (self.workspace_dir / raw).resolve()
        if resolved != self.workspace_dir and self.workspace_dir not in resolved.parents:
            raise ValueError("workspace_path_escape")
        return resolved

    async def _run_command(
        self,
        command: List[str],
        *,
        command_kind: str,
        timeout_sec: float,
        network: bool,
    ) -> SandboxCommandResult:
        actual = list(command)
        if self.backend == "sandbox_exec":
            actual = [
                "/usr/bin/sandbox-exec",
                "-p",
                self._macos_profile(network=network),
                *actual,
            ]
        guarded_python = self.backend == "python_audit" and command_kind == "python_run"
        if guarded_python:
            self._install_python_audit_guard()
        env = {
            "HOME": str(self.home_dir),
            "TMPDIR": str(self.cache_dir),
            "XDG_CACHE_HOME": str(self.cache_dir),
            "PIP_CACHE_DIR": str(self.cache_dir / "pip"),
            "PATH": str(self.python_path.parent),
            "PYTHONUNBUFFERED": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "LANG": "C.UTF-8",
        }
        if guarded_python:
            read_roots = (
                self.root,
                Path(sys.base_prefix).resolve(),
                Path(sys.prefix).resolve(),
            )
            env.update({
                "PYTHONPATH": str(self.policy_dir),
                "AI_WORLD_SANDBOX_READ_ROOTS": os.pathsep.join(
                    str(path) for path in read_roots
                ),
                "AI_WORLD_SANDBOX_WRITE_ROOTS": str(self.root),
                "AI_WORLD_SANDBOX_NETWORK": "1" if network else "0",
            })
        started = time.monotonic()
        try:
            process = await asyncio.create_subprocess_exec(
                *actual,
                cwd=str(self.workspace_dir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
                preexec_fn=self._resource_limits(timeout_sec),
            )
            stdout_raw, stderr_raw = await asyncio.wait_for(
                process.communicate(), timeout=timeout_sec
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return SandboxCommandResult(
                ok=False,
                command_kind=command_kind,
                errors=[f"timeout>{timeout_sec}s"],
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        except Exception as exc:
            return SandboxCommandResult(
                ok=False,
                command_kind=command_kind,
                errors=[str(exc)],
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        limit = self.policy.max_output_bytes
        stdout = stdout_raw[:limit].decode("utf-8", errors="replace")
        stderr = stderr_raw[:limit].decode("utf-8", errors="replace")
        errors = [] if process.returncode == 0 else [f"exit_code:{process.returncode}"]
        return SandboxCommandResult(
            ok=process.returncode == 0,
            command_kind=command_kind,
            exit_code=process.returncode,
            stdout=stdout,
            stderr=stderr,
            errors=errors,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    def _install_python_audit_guard(self) -> None:
        guard = self.policy_dir / "sitecustomize.py"
        if not guard.is_file() or guard.read_text(encoding="utf-8") != _PYTHON_AUDIT_GUARD:
            guard.write_text(_PYTHON_AUDIT_GUARD, encoding="utf-8")

    def _resource_limits(self, timeout_sec: float):
        max_output = max(self.policy.max_output_bytes, 1024 * 1024)

        def apply() -> None:
            cpu = max(1, int(math.ceil(timeout_sec)))
            resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
            resource.setrlimit(resource.RLIMIT_FSIZE, (max_output * 8, max_output * 8))
            resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
            if hasattr(resource, "RLIMIT_NPROC"):
                resource.setrlimit(resource.RLIMIT_NPROC, (16, 16))

        return apply

    def _record_operation(self, operation: str, payload: Dict[str, object]) -> None:
        record = {
            "timestamp": time.time(),
            "agent_id": self.agent_id,
            "operation": operation,
            "payload": payload,
        }
        with self.operations_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def _macos_profile(self, *, network: bool) -> str:
        readable = {
            self.root,
            Path(sys.base_prefix).resolve(),
            Path("/System"),
            Path("/usr"),
            Path("/Library/Frameworks"),
            Path("/private/etc"),
            Path("/dev"),
        }
        # 解释器真身所在的安装根也必须可读：venv 的 python 是符号链，
        # 真身可能在 /Library/Developer/CommandLineTools 等不在默认名单
        # 的位置——缺了它，deny-default 下解释器根本起不来（任何脚本
        # 瞬间死亡、无输出）。取真身与 base_prefix 的公共祖先，通用覆盖。
        try:
            real_python = Path(os.path.realpath(str(self.python_path)))
            real_prefix = Path(os.path.realpath(sys.base_prefix))
            if real_python.exists():
                readable.add(real_python.parent)
                common = os.path.commonpath(
                    [str(real_python), str(real_prefix)]
                )
                if common and common != os.sep:
                    readable.add(Path(common))
        except (OSError, ValueError):
            pass
        read_rules = " ".join(
            f'(subpath "{str(path).replace(chr(34), "")}")'
            for path in sorted(readable, key=str)
            if path.exists()
        )
        network_rule = "(allow network*)" if network else ""
        return (
            "(version 1) "
            "(deny default) "
            "(allow process*) "
            "(allow signal (target self)) "
            "(allow sysctl-read) "
            f"(allow file-read* {read_rules}) "
            f'(allow file-write* (subpath "{self.root}") '
            f'(subpath "{self.cache_dir}")) '
            f"{network_rule}"
        )

    @staticmethod
    def _resolve_backend(requested: str) -> str:
        if requested != "auto":
            return requested
        if platform.system() == "Darwin" and shutil.which("sandbox-exec"):
            try:
                probe = subprocess.run(
                    [
                        "/usr/bin/sandbox-exec",
                        "-p",
                        "(version 1) (allow default)",
                        "/usr/bin/true",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                    check=False,
                )
                if probe.returncode == 0:
                    return "sandbox_exec"
            except (OSError, subprocess.SubprocessError):
                pass
        return "python_audit"


class AgentSandboxRegistry:
    """Owns exactly one process sandbox per participating agent."""

    def __init__(self, root: Path, policy: SandboxPolicy):
        self.root = root.resolve()
        self.policy = policy
        self._items: Dict[str, AgentProcessSandbox] = {}

    def create(self, agent_id: str) -> AgentProcessSandbox:
        if not _AGENT_ID_RE.fullmatch(str(agent_id or "")):
            raise ValueError(f"invalid_agent_id:{agent_id}")
        if agent_id in self._items:
            return self._items[agent_id]
        sandbox = AgentProcessSandbox(
            self.root / agent_id,
            agent_id=agent_id,
            policy=self.policy,
        )
        self._items[agent_id] = sandbox
        return sandbox

    def get(self, agent_id: str) -> Optional[AgentProcessSandbox]:
        return self._items.get(agent_id)

    def all(self) -> List[AgentProcessSandbox]:
        return list(self._items.values())
