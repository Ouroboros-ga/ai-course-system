"""SWE-ReX Docker 后端薄适配（T1-b）：run 级实例生命周期＋命令/文件原语。

只做三件事（ verified against swe-rex==1.4.0 installed source, not docs memory）：
1. 按 run 创建/启停 DockerDeployment（python_standalone_dir=None 跳过重型构建；
   资源/网络/清理经 docker_args 由部署配置传入，本模块不编排策略）；
2. execute/upload/read/write 原语透传 RemoteRuntime，失败如实映射；
3. 取消＝停止容器（run 级；操作级 session 中断属 T4，见下）。

不做的事：不解析依赖、不求解环境、不管理镜像、不调度多机、不实现
通用容器平台。隔离/配额的真实语义由 Docker 守护进程＋传入的 docker_args
提供，本模块只透传配置并记录实际生效值（核验见 test_live_docker）。

注意：swe-rex 的 run_in_session 会话语义本批不用——operation 模型与
一次性 execute() 一一对应；长会话语义随 T4 实验图需要再评估。
取消语义：停止容器即终止其内全部进程（无残留由 stop+remove 保证）；
这比"中断单个命令"粗，但与任务书"先取消运行操作，再回收实例"一致。
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from typing import Any, Callable

logger = logging.getLogger("repro_runtime.swerex_adapter")


def _docker_cli(*args: str) -> tuple[int, str]:
    """docker CLI 直调（仅 kill/rm/inspect 类管理动作，不跑任务命令）。

    任务命令永远走 RemoteRuntime；本函数只为"容器不配合时"的强制回收。
    无 CLI 时抛 DockerBackendUnavailableError（调用方如实映射）。
    """
    try:
        completed = subprocess.run(
            ["docker", *args], capture_output=True, text=True, timeout=30)
    except FileNotFoundError as error:
        raise DockerBackendUnavailableError(
            "DOCKER_CLI_MISSING", "宿主无 docker CLI，无法强制回收"
        ) from error
    except subprocess.TimeoutExpired as error:
        raise DockerBackendUnavailableError(
            "DOCKER_TIMEOUT", f"docker 命令超时：{' '.join(args)[:80]}"
        ) from error
    return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


class DockerBackendUnavailableError(Exception):
    """Docker/部署层失败（镜像缺失、守护进程不可达、启动超时等）。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


class SwerexDockerAdapter:
    """单个 run 的 DockerDeployment 生命周期持有者。

    deployment_factory 供测试注入 Fake（签名与 DockerDeployment 构造一致）；
    生产路径直接构造真实 DockerDeployment。
    """

    def __init__(
        self,
        *,
        run_id: str,
        image: str,
        docker_args: list[str] | None = None,
        startup_timeout_s: float = 180.0,
        pull: str = "missing",
        deployment_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.run_id = (run_id or "").strip()[:64]
        self.image = (image or "").strip()
        self.docker_args = list(docker_args or [])
        self.startup_timeout_s = max(10.0, float(startup_timeout_s or 180.0))
        if pull not in ("never", "missing", "always"):
            raise ValueError(f"未知 pull 策略：{pull!r}")
        self.pull = pull
        self._factory = deployment_factory
        self._deployment: Any = None
        self._started = False

    @property
    def container_name(self) -> str | None:
        if self._deployment is None:
            return None
        return self._deployment.container_name

    def _build_deployment(self) -> Any:
        if self._factory is not None:
            return self._factory(
                image=self.image,
                docker_args=self.docker_args,
                startup_timeout=self.startup_timeout_s,
                pull=self.pull,
            )
        from swerex.deployment.docker import DockerDeployment

        return DockerDeployment(
            image=self.image,
            docker_args=self.docker_args,
            startup_timeout=self.startup_timeout_s,
            pull=self.pull,
            python_standalone_dir=None,
            remove_container=True,
        )

    async def start(self) -> str:
        """启动实例；返回容器名。已启动则幂等返回现容器名。"""
        if self._started and self._deployment is not None:
            return str(self._deployment.container_name or "")
        if not self.image:
            raise DockerBackendUnavailableError("IMAGE_MISSING", "任务镜像未配置")
        self._deployment = self._build_deployment()
        try:
            await self._deployment.start()
        except Exception as error:  # noqa: BLE001 - 部署失败如实映射
            self._deployment = None
            raise DockerBackendUnavailableError(
                "DEPLOYMENT_START_FAILED",
                f"实例启动失败（{type(error).__name__}）：{str(error)[:200]}",
            ) from error
        self._started = True
        name = str(self._deployment.container_name or "")
        logger.info("run %s container started: %s", self.run_id, name)
        return name

    async def stop(self) -> None:
        """停止并回收实例；幂等（未启动/已停止直接返回）。"""
        deployment, self._deployment = self._deployment, None
        self._started = False
        if deployment is None:
            return
        try:
            await deployment.stop()
        except Exception as error:  # noqa: BLE001 - 回收失败记日志，不抛
            logger.warning("run %s container stop failed: %s", self.run_id, error)

    async def kill(self) -> None:
        """强制回收（kill-first）：不经过容器内协作，直接停容器。

        用于取消路径——容器内服务可能正被长执行占住（如 close 排队），
        此时优雅 stop 会挂起；kill 走 daemon 面，永不等待容器配合。
        幂等：容器已无则直接返回。
        """
        name = self.container_name
        self._deployment = None
        self._started = False
        if not name:
            return
        code, out = _docker_cli("kill", name)
        if code != 0 and "No such container" not in out:
            logger.warning("run %s docker kill rc=%s: %s", self.run_id, code,
                           out[:200])
        code, out = _docker_cli("rm", "-f", name)
        if code != 0 and "No such container" not in out:
            logger.warning("run %s docker rm rc=%s: %s", self.run_id, code,
                           out[:200])

    async def image_digest(self) -> str:
        """容器实际镜像 ID（sha256:…）；无 docker CLI/容器时返回空串。

        用于配方如实记录镜像来源（tag 可被重指，digest 不会）。
        """
        name = self.container_name
        if not name:
            return ""
        try:
            code, out = _docker_cli("inspect", "--format", "{{.Image}}", name)
        except DockerBackendUnavailableError:
            return ""
        text = (out or "").strip()
        if code != 0 or not text:
            return ""
        return text.splitlines()[-1].strip()[:128]

    async def resolve_real_path(self, path: str) -> str:
        """容器内 `readlink -f` 解析真实路径（symlink 逃逸校验用）。

        路径不存在时 GNU readlink -f 仍返回解析后的字面路径（exit 0）；
        解析失败（无 CLI/容器）抛 DockerBackendUnavailableError，调用方如实映射。
        """
        import shlex

        if self._deployment is None:
            raise DockerBackendUnavailableError(
                "NOT_STARTED", "实例未启动；先 start() 再解析路径")
        result = await self.execute(
            f"readlink -f -- {shlex.quote(path)}", timeout_s=30.0)
        if result["exit_code"] != 0:
            raise DockerBackendUnavailableError(
                "RESOLVE_FAILED",
                f"路径解析失败（exit={result['exit_code']}）：{result['output'][:200]}")
        lines = [line.strip() for line in str(result["output"]).splitlines() if line.strip()]
        return lines[-1] if lines else path

    async def is_alive(self) -> bool:
        if self._deployment is None:
            return False
        try:
            return bool(await self._deployment.is_alive())
        except Exception:  # noqa: BLE001 - 存活探针失败即视为不存活
            return False

    async def execute(
        self, command: str, timeout_s: float | None = None
    ) -> dict[str, Any]:
        """一次性执行命令；返回 {"output", "exit_code", "truncated"}。

        output 为 stdout＋stderr 合并（stderr 非空时标注段落）；执行超过
        timeout 由远端中止（exit_code 如实返回，不伪装成功）。
        """
        if self._deployment is None:
            raise DockerBackendUnavailableError(
                "NOT_STARTED", "实例未启动；先 start() 再执行")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command 不能为空")
        from swerex.runtime.abstract import Command

        try:
            response = await self._deployment.runtime.execute(
                Command(command=command,
                        timeout=timeout_s if timeout_s and timeout_s > 0 else None,
                        shell=True))
        except Exception as error:  # noqa: BLE001
            raise DockerBackendUnavailableError(
                "EXECUTE_FAILED",
                f"命令提交/执行失败（{type(error).__name__}）：{str(error)[:200]}",
            ) from error
        stdout = str(response.stdout or "")
        stderr = str(response.stderr or "")
        output = stdout + (f"\n[stderr]\n{stderr}" if stderr else "")
        return {"output": output, "exit_code": response.exit_code,
                "truncated": False}

    async def write_text(self, path: str, content: str) -> None:
        """写文本文件（UTF-8）；失败抛 DockerBackendUnavailableError。"""
        if self._deployment is None:
            raise DockerBackendUnavailableError(
                "NOT_STARTED", "实例未启动；先 start() 再传文件")
        from swerex.runtime.abstract import WriteFileRequest

        try:
            await self._deployment.runtime.write_file(
                WriteFileRequest(path=path, content=content))
        except Exception as error:  # noqa: BLE001
            raise DockerBackendUnavailableError(
                "WRITE_FAILED",
                f"写文件失败（{type(error).__name__}）：{str(error)[:200]}",
            ) from error

    async def read_text(self, path: str) -> str:
        """读文本文件；失败抛 DockerBackendUnavailableError。"""
        if self._deployment is None:
            raise DockerBackendUnavailableError(
                "NOT_STARTED", "实例未启动；先 start() 再读文件")
        from swerex.runtime.abstract import ReadFileRequest

        try:
            response = await self._deployment.runtime.read_file(
                ReadFileRequest(path=path))
        except Exception as error:  # noqa: BLE001
            raise DockerBackendUnavailableError(
                "READ_FAILED",
                f"读文件失败（{type(error).__name__}）：{str(error)[:200]}",
            ) from error
        return str(response.content or "")

    async def read_bytes(self, path: str, max_bytes: int = 1048576) -> bytes:
        """读字节（经 base64＋execute 原语，不依赖远端下载接口）。

        远端 1.4.0 只提供文本 read_file；二进制走“容器内 base64 编码后取
        回解码”，只用已验证的 execute 原语。超限抛 file_too_large 风格错误。
        """
        import base64
        import shlex

        if self._deployment is None:
            raise DockerBackendUnavailableError(
                "NOT_STARTED", "实例未启动；先 start() 再读文件")
        result = await self.execute(
            f"base64 -w0 {shlex.quote(path)}", timeout_s=60.0)
        if result["exit_code"] != 0:
            output = result["output"]
            if "no such file" in output.lower():
                raise DockerBackendUnavailableError(
                    "READ_FAILED", f"file_not_found: {path}")
            raise DockerBackendUnavailableError(
                "READ_FAILED",
                f"读文件失败（exit={result['exit_code']}）：{output[:200]}",
            )
        try:
            raw = base64.b64decode(result["output"].strip())
        except Exception as error:  # noqa: BLE001
            raise DockerBackendUnavailableError(
                "READ_FAILED", f"读文件解码失败：{type(error).__name__}"
            ) from error
        if len(raw) > max_bytes:
            raise DockerBackendUnavailableError(
                "file_too_large",
                f"文件过大（>{max_bytes} 字节）；正式交付走 Artifact 通道",
            )
        return raw

    async def upload_bytes(self, target_path: str, data: bytes) -> None:
        """上传字节（经服务侧 staging 中转，用后清理；staging 不进容器）。"""
        if self._deployment is None:
            raise DockerBackendUnavailableError(
                "NOT_STARTED", "实例未启动；先 start() 再传文件")
        from swerex.runtime.abstract import UploadRequest

        staging_dir = os.path.join(tempfile.gettempdir(), "repro-runtime-staging")
        os.makedirs(staging_dir, exist_ok=True)
        staging_path = os.path.join(
            staging_dir, f"{self.run_id.replace('/', '_')}_{os.urandom(4).hex()}")
        try:
            with open(staging_path, "wb") as handle:
                handle.write(bytes(data))
            try:
                await self._deployment.runtime.upload(
                    UploadRequest(source_path=staging_path,
                                  target_path=target_path))
            except Exception as error:  # noqa: BLE001
                raise DockerBackendUnavailableError(
                    "UPLOAD_FAILED",
                    f"上传失败（{type(error).__name__}）：{str(error)[:200]}",
                ) from error
        finally:
            try:
                os.remove(staging_path)
            except OSError:
                pass

    # -- 会话原语（F3）：run 级受控 shell（pexpect REPL 在任务容器内） ----
    # 只做上游公开 API 的薄透传：create/run/interrupt/close/probe，不实现
    # 任何调度、PTY 或输出解析内核。会话按 run 隔离（名含 run_id），同一会
    # 话内命令天然串行——并发限制由服务层 per-run 会话锁保证，本模块不加锁。

    def _require_deployment(self) -> Any:
        if self._deployment is None:
            raise DockerBackendUnavailableError(
                "NOT_STARTED", "实例未启动；先 start() 再操作会话")
        return self._deployment

    async def create_session(self, session: str) -> str:
        """建会话；已存在抛 SESSION_EXISTS（调用方据此幂等）。"""
        from swerex.exceptions import SessionExistsError
        from swerex.runtime.abstract import CreateBashSessionRequest

        deployment = self._require_deployment()
        try:
            response = await deployment.runtime.create_session(
                CreateBashSessionRequest(session=session))
        except SessionExistsError as error:
            raise DockerBackendUnavailableError(
                "SESSION_EXISTS", f"会话已存在：{session}") from error
        except Exception as error:  # noqa: BLE001
            raise DockerBackendUnavailableError(
                "SESSION_CREATE_FAILED",
                f"建会话失败（{type(error).__name__}）：{str(error)[:200]}",
            ) from error
        return str(response.output or "")

    async def run_in_session(
        self, session: str, command: str, timeout_s: float | None = None,
    ) -> dict[str, Any]:
        """会话内执行；超时抛 SESSION_TIMEOUT（命令仍在跑，未杀）。

        check 固定 silent：非零退出如实返回 exit_code，不抛；返回
        {"output", "exit_code"}（exit_code 为 None 仅解析失败时）。
        """
        from swerex.exceptions import CommandTimeoutError, SessionDoesNotExistError
        from swerex.runtime.abstract import BashAction

        deployment = self._require_deployment()
        try:
            observation = await deployment.runtime.run_in_session(
                BashAction(command=command, session=session,
                           timeout=timeout_s, check="silent"))
        except CommandTimeoutError as error:
            raise DockerBackendUnavailableError(
                "SESSION_TIMEOUT",
                f"会话命令超时未回显（仍在跑）：{str(error)[:160]}",
            ) from error
        except SessionDoesNotExistError as error:
            raise DockerBackendUnavailableError(
                "SESSION_MISSING", f"会话不存在：{session}") from error
        except Exception as error:  # noqa: BLE001
            raise DockerBackendUnavailableError(
                "SESSION_RUN_FAILED",
                f"会话执行失败（{type(error).__name__}）：{str(error)[:200]}",
            ) from error
        return {"output": str(observation.output or ""),
                "exit_code": observation.exit_code}

    async def interrupt_session(
        self, session: str, timeout_s: float = 2.0, n_retry: int = 3,
    ) -> dict[str, Any]:
        """中断会话当前命令；返回中断时输出（exit_code 恒 0，无判定意义）。

        中断了什么、停没停由调用方经探活＋标记确认，本原语不做结论。
        """
        from swerex.exceptions import SessionDoesNotExistError
        from swerex.runtime.abstract import BashInterruptAction

        deployment = self._require_deployment()
        try:
            observation = await deployment.runtime.run_in_session(
                BashInterruptAction(session=session, timeout=timeout_s,
                                    n_retry=n_retry))
        except SessionDoesNotExistError as error:
            raise DockerBackendUnavailableError(
                "SESSION_MISSING", f"会话不存在：{session}") from error
        except Exception as error:  # noqa: BLE001 - 含中断超时（停不下来）
            raise DockerBackendUnavailableError(
                "SESSION_INTERRUPT_FAILED",
                f"会话中断失败（{type(error).__name__}）：{str(error)[:200]}",
            ) from error
        return {"output": str(observation.output or "")}

    async def probe_session(self, session: str, timeout_s: float = 2.0) -> bool:
        """探活：空命令短超时回显即 shell 空闲 True；超时即仍忙 False。

        shell 串行语义使本探针成为"前序命令已结束"的设施级证明（结合完成
        标记采信终态，防实验代码伪造成功）。
        """
        from swerex.exceptions import CommandTimeoutError, SessionDoesNotExistError

        try:
            await self.run_in_session(session, ":", timeout_s=timeout_s)
        except DockerBackendUnavailableError as error:
            if error.code in ("SESSION_TIMEOUT", "SESSION_MISSING"):
                return False
            raise
        except Exception:  # noqa: BLE001 - 探针失败按不空闲处理，不抛
            return False
        return True

    async def close_session(self, session: str) -> None:
        """关会话；不存在即幂等返回（不抛）。"""
        from swerex.exceptions import SessionDoesNotExistError
        from swerex.runtime.abstract import CloseBashSessionRequest

        deployment = self._require_deployment()
        try:
            await deployment.runtime.close_session(
                CloseBashSessionRequest(session=session))
        except SessionDoesNotExistError:
            return
        except Exception as error:  # noqa: BLE001
            raise DockerBackendUnavailableError(
                "SESSION_CLOSE_FAILED",
                f"关会话失败（{type(error).__name__}）：{str(error)[:200]}",
            ) from error
