"""G3 Judge0 代码沙箱客户端

以独立、可回滚的本地 Docker 服务提供代码编译和运行，不在主应用进程执行学生代码。
后端通过此客户端调用 Judge0 API，每道题独立限制资源。
默认关闭网络，禁止在线安装依赖。
沙箱不可用时学习主流程可正常降级。
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Judge0 语言 ID 映射（仅允许课程声明的语言）
ALLOWED_LANGUAGES: dict[str, int] = {
    "python3": 71,
    "c": 50,
    "cpp": 54,
    "java": 62,
    "javascript": 63,
    "go": 60,
    "rust": 73,
    "csharp": 51,
    "ruby": 72,
    "php": 68,
}
MAX_RESULT_TEXT_CHARS = 100_000


class SubmissionStatus(str, Enum):
    """Judge0 提交状态"""
    IN_QUEUE = "in_queue"
    PROCESSING = "processing"
    ACCEPTED = "accepted"
    WRONG_ANSWER = "wrong_answer"
    TIME_LIMIT_EXCEEDED = "time_limit_exceeded"
    MEMORY_LIMIT_EXCEEDED = "memory_limit_exceeded"
    RUNTIME_ERROR = "runtime_error"
    COMPILATION_ERROR = "compilation_error"
    INTERNAL_ERROR = "internal_error"
    SANDBOX_UNAVAILABLE = "sandbox_unavailable"


# Judge0 status.id -> 我们的语义
JUDGE0_STATUS_MAP: dict[int, SubmissionStatus] = {
    1: SubmissionStatus.IN_QUEUE,
    2: SubmissionStatus.PROCESSING,
    3: SubmissionStatus.ACCEPTED,
    4: SubmissionStatus.WRONG_ANSWER,
    5: SubmissionStatus.TIME_LIMIT_EXCEEDED,
    6: SubmissionStatus.MEMORY_LIMIT_EXCEEDED,
    7: SubmissionStatus.RUNTIME_ERROR,
    8: SubmissionStatus.COMPILATION_ERROR,
    9: SubmissionStatus.INTERNAL_ERROR,
    13: SubmissionStatus.INTERNAL_ERROR,
    14: SubmissionStatus.INTERNAL_ERROR,
}


@dataclass(frozen=True)
class SandboxResourceLimits:
    """每道题独立的资源限制"""
    cpu_time_limit: int = 5          # 秒
    cpu_extra_time: float = 1.0     # 超时额外等待
    wall_time_limit: int = 10       # 墙钟时间
    memory_limit: int = 128000      # KB
    stack_limit: int = 64000         # KB
    max_processes: int = 30         # 最大进程/线程数
    max_file_size: int = 1024       # KB
    enable_network: bool = False    # 始终关闭


@dataclass
class SandboxResult:
    """代码执行结果"""
    status: SubmissionStatus
    stdout: str = ""
    stderr: str = ""
    compile_output: str = ""
    time: Optional[float] = None    # 秒
    memory: Optional[int] = None     # KB
    exit_code: Optional[int] = None
    message: str = ""
    token: str = ""

    @property
    def is_accepted(self) -> bool:
        return self.status == SubmissionStatus.ACCEPTED

    @property
    def is_error(self) -> bool:
        return self.status in (
            SubmissionStatus.RUNTIME_ERROR,
            SubmissionStatus.COMPILATION_ERROR,
            SubmissionStatus.INTERNAL_ERROR,
        )

    @property
    def is_timeout(self) -> bool:
        return self.status == SubmissionStatus.TIME_LIMIT_EXCEEDED

    @property
    def is_memory_exceeded(self) -> bool:
        return self.status == SubmissionStatus.MEMORY_LIMIT_EXCEEDED

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "compile_output": self.compile_output,
            "time": self.time,
            "memory": self.memory,
            "exit_code": self.exit_code,
            "message": self.message,
        }


class SandboxUnavailableError(Exception):
    """沙箱不可用时的降级异常"""
    pass


class SandboxClient:
    """Judge0 沙箱客户端

    不允许前端直接调用 Judge0。
    不允许题目携带任意 shell、Docker、网络权限。
    """

    def __init__(
        self,
        base_url: str = "",
        authn_token: str = "",
        timeout: int = 30,
    ):
        self.base_url = base_url or settings.JUDGE0_API_URL
        self.authn_token = authn_token or settings.JUDGE0_AUTHN_TOKEN
        self.timeout = timeout or settings.JUDGE0_QUEUE_TIMEOUT
        self._enabled = settings.JUDGE0_ENABLED

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.authn_token:
            headers[settings.JUDGE0_AUTHN_HEADER] = self.authn_token
        if settings.JUDGE0_AUTHZ_TOKEN:
            headers[settings.JUDGE0_AUTHZ_HEADER] = settings.JUDGE0_AUTHZ_TOKEN
        return headers

    def submit_code(
        self,
        source_code: str,
        language: str,
        stdin: str = "",
        expected_output: str = "",
        limits: Optional[SandboxResourceLimits] = None,
    ) -> SandboxResult:
        """提交代码到 Judge0 执行

        Args:
            source_code: 源代码
            language: 语言名称（必须在 ALLOWED_LANGUAGES 中）
            stdin: 标准输入
            expected_output: 期望输出（用于自动判定）
            limits: 资源限制（默认使用配置值）

        Returns:
            SandboxResult: 执行结果

        Raises:
            SandboxUnavailableError: 沙箱不可用时抛出
            ValueError: 语言不允许或参数无效
        """
        if not self._enabled:
            return SandboxResult(
                status=SubmissionStatus.SANDBOX_UNAVAILABLE,
                message="代码沙箱未启用，学习主流程正常降级",
            )

        if language not in ALLOWED_LANGUAGES:
            raise ValueError(
                f"语言 '{language}' 不在允许列表中。"
                f"允许的语言: {list(ALLOWED_LANGUAGES.keys())}"
            )

        language_id = ALLOWED_LANGUAGES[language]
        limits = limits or SandboxResourceLimits(
            cpu_time_limit=settings.JUDGE0_DEFAULT_CPU_TIME_LIMIT,
            memory_limit=settings.JUDGE0_DEFAULT_MEMORY_LIMIT,
            wall_time_limit=settings.JUDGE0_DEFAULT_WALL_TIME_LIMIT,
            max_processes=settings.JUDGE0_DEFAULT_MAX_PROCESSES,
            max_file_size=settings.JUDGE0_DEFAULT_MAX_FILE_SIZE,
        )

        # 构建 Judge0 提交请求
        payload: dict[str, Any] = {
            "language_id": language_id,
            "source_code": base64.b64encode(source_code.encode()).decode(),
            "stdin": base64.b64encode(stdin.encode()).decode() if stdin else "",
            "cpu_time_limit": limits.cpu_time_limit,
            "cpu_extra_time": limits.cpu_extra_time,
            "wall_time_limit": limits.wall_time_limit,
            "memory_limit": limits.memory_limit,
            "stack_limit": limits.stack_limit,
            "max_processes_and_or_threads": limits.max_processes,
            "max_file_size": limits.max_file_size,
            # Judge0 1.13.1 bundles isolate 1.8.1, whose cgroup mode expects
            # the legacy cgroup-v1 cpuacct/memory hierarchy. Ubuntu 22.04
            # defaults to cgroup v2, so aggregate cgroup limits fail before
            # the source file is staged. Per-process RLIMIT enforcement works
            # on cgroup v2; max_processes plus the Worker container's hard
            # memory/PID ceilings bound aggregate Demo-host consumption.
            "enable_per_process_and_thread_time_limit": True,
            "enable_per_process_and_thread_memory_limit": True,
            "enable_network": False,  # 始终关闭网络
            "number_of_runs": 1,
            "redirect_stderr_to_stdout": False,
        }

        if expected_output:
            payload["expected_output"] = base64.b64encode(expected_output.encode()).decode()

        try:
            with httpx.Client(timeout=self.timeout) as client:
                # 提交并等待结果
                response = client.post(
                    f"{self.base_url}/submissions",
                    json=payload,
                    params={"base64_encoded": "true", "wait": "true"},
                    headers=self._headers(),
                )
                response.raise_for_status()
                data = response.json()

            return self._parse_result(data)

        except httpx.ConnectError:
            logger.warning("Judge0 沙箱连接失败，降级处理")
            return SandboxResult(
                status=SubmissionStatus.SANDBOX_UNAVAILABLE,
                message="代码沙箱不可用，学习主流程正常降级",
            )
        except httpx.TimeoutException:
            logger.warning("Judge0 沙箱超时")
            return SandboxResult(
                status=SubmissionStatus.TIME_LIMIT_EXCEEDED,
                message="沙箱执行超时",
            )
        except Exception:
            logger.exception("Judge0 沙箱请求失败")
            return SandboxResult(
                status=SubmissionStatus.INTERNAL_ERROR,
                message="沙箱内部错误",
            )

    def health_check(self) -> bool:
        """检查 Judge0 沙箱是否可用"""
        if not self._enabled:
            return False
        try:
            with httpx.Client(timeout=5) as client:
                response = client.get(
                    f"{self.base_url}/system_info",
                    headers=self._headers(),
                )
                return response.status_code == 200
        except Exception:
            return False

    def _parse_result(self, data: dict[str, Any]) -> SandboxResult:
        """解析 Judge0 返回结果"""
        status_id = data.get("status", {}).get("id", 0)
        status = JUDGE0_STATUS_MAP.get(status_id, SubmissionStatus.INTERNAL_ERROR)

        def _decode(val: Optional[str]) -> str:
            if not val:
                return ""
            try:
                result = base64.b64decode(val).decode(errors="replace")
            except Exception:
                result = val
            if len(result) > MAX_RESULT_TEXT_CHARS:
                return result[:MAX_RESULT_TEXT_CHARS] + "\n[output truncated]"
            return result

        return SandboxResult(
            status=status,
            stdout=_decode(data.get("stdout")),
            stderr=_decode(data.get("stderr")),
            compile_output=_decode(data.get("compile_output")),
            time=float(data["time"]) if data.get("time") else None,
            memory=int(data["memory"]) if data.get("memory") else None,
            exit_code=data.get("exit_code"),
            message=data.get("message", ""),
            token=data.get("token", ""),
        )


# 全局单例
sandbox_client = SandboxClient()
