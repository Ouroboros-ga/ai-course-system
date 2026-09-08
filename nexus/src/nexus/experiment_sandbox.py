"""NX-T1 实验沙箱客户端：Deep Agents BaseSandbox → 独立执行控制服务的薄映射。

胶水定位：本模块只做协议映射（BaseSandbox 方法 ↔ 控制服务 HTTP），不实现
任何执行内核——不 subprocess、不调度容器、不求解依赖、不管理 Docker。
执行内核是 T1-b 的 SWE-ReX Docker 后端；构建是 repo2docker（候选）。
隔离/取消/清理的真实语义由控制服务提供，本模块只透传并如实映射失败。

fail-closed：控制服务未配置或不可达时抛 ExperimentSandboxError，绝不回落
宿主进程内执行（回落即把不可信命令放到 Nexus 进程，违反 AGENTS.md §4.1.1）。
本模块不依赖 subprocess/os.system 等本地执行原语，回归测试显式断言。

控制服务契约（任务书 §2，内网专用；实现见 T1-b deploy/repro-runtime）：
- PUT /sandboxes/{run_id} → ensure（同 run 幂等，返回 sandbox_id/status）
- POST /sandboxes/{run_id}/operations {operation_id, command, timeout_s}
- GET /sandboxes/{run_id}/operations/{operation_id}（查询/日志游标）
- PUT/GET /sandboxes/{run_id}/files/{path:path}（工作区限定，服务端校验）
- POST /sandboxes/{run_id}/cancel（先停操作，再回收实例）
- GET /sandboxes/{run_id}（生命周期/对账摘要）

operation_id 由调用方所属层稳定生成：本实例内单调（run_id-op-NNNN），
同一次 execute 调用不重新生成；跨重试的稳定性由 T4 图层保证（持久化执行
意图），本模块暴露 last_operation_id / query_operation 供其查询续跑。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from urllib.parse import quote

import httpx
from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox

logger = logging.getLogger("nexus.experiment_sandbox")

TERMINAL_OPERATION_STATUSES = ("succeeded", "failed", "cancelled")

_FILE_MAX_BYTES = 5 * 1024 * 1024
_DEFAULT_POLL_INTERVAL_S = 0.5
_DEFAULT_POLL_DEADLINE_S = 300.0
_HTTP_TIMEOUT_S = 30.0


class ExperimentSandboxError(Exception):
    """沙箱控制面失败：携带机器可读 code（fail-closed，不伪造执行结果）。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def _check_sandbox_path(path: str) -> str:
    """客户端侧路径底线校验（服务端 T1-b  authoritative 再验）。

    只接受绝对路径；拒绝空、NUL 与任何 `..` 段（目录逃逸）。工作区映射由
    控制服务负责，客户端不猜测容器内根目录。
    """
    if not isinstance(path, str) or not path.startswith("/") or "\x00" in path:
        raise ValueError(f"非法沙箱路径：{path!r}（须为绝对路径）")
    segments = [seg for seg in path.split("/") if seg not in ("", ".")]
    if ".." in segments:
        raise ValueError(f"非法沙箱路径：{path!r}（禁止父目录逃逸）")
    return path


def _operation_to_response(operation: dict[str, Any]) -> ExecuteResponse:
    """控制面 operation 记录 → ExecuteResponse（LLM 消费形态）。

    running/unknown 无确定退出码（exit_code=None，truncated=True 由调用方
    决定续查，不盲重发）；终态如实透传 exit_code。
    """
    status = operation.get("status")
    code = operation.get("exit_code")
    if status not in TERMINAL_OPERATION_STATUSES or not isinstance(code, int) \
            or isinstance(code, bool):
        code = None
    return ExecuteResponse(
        output=str(operation.get("output_tail") or ""),
        exit_code=code,
        truncated=bool(operation.get("output_truncated")) or code is None,
    )


class HttpSandboxBackend(BaseSandbox):
    """面向独立执行控制服务的 BaseSandbox 实现（薄 Adapter）。

    所有文件操作（ls/read/write/edit/grep/glob）经基类 funnel 到
    execute()/upload_files()/download_files()，因此本类只需实现这三个原语
    ＋ id。同步方法供 FilesystemMiddleware 同步路径，异步方法供 agent 循环。
    """

    def __init__(
        self, *, run_id: str, base_url: str = "", token: str = "",
        timeout_s: float = _HTTP_TIMEOUT_S,
        poll_interval_s: float = _DEFAULT_POLL_INTERVAL_S,
        default_poll_deadline_s: float = _DEFAULT_POLL_DEADLINE_S,
        transport: Any = None,
    ) -> None:
        self._run_id = (run_id or "").strip()[:64]
        self._base_url = (base_url or "").rstrip("/")
        self._token = token or ""
        self._timeout_s = max(1.0, float(timeout_s or _HTTP_TIMEOUT_S))
        self._poll_interval_s = max(0.05, float(poll_interval_s))
        self._default_deadline_s = max(1.0, float(default_poll_deadline_s))
        self._transport = transport
        self._op_seq = 0
        self._sandbox_id = ""
        self._ensured = False
        # T4 图层续跑用：最近一次 execute 提交/查询的 operation_id。
        self.last_operation_id = ""
        # T5-1：提交日志（operation_id, command），供执行器把工具结果
        # 精确归因到 control operation（并行调用下 last_operation_id 会错位）。
        self.submitted_ops: list[tuple[str, str]] = []

    @property
    def id(self) -> str:
        return f"experiment-sandbox:{self._run_id or 'unbound'}"

    # -- 传输层 ---------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _require_configured(self) -> str:
        if not self._base_url or not self._run_id:
            raise ExperimentSandboxError(
                "SANDBOX_NOT_CONFIGURED",
                "执行控制服务未配置（base_url/run_id 缺失）；不得执行，不得回落宿主。",
            )
        return self._base_url

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        base = self._require_configured()
        try:
            with httpx.Client(transport=self._transport,
                              timeout=httpx.Timeout(self._timeout_s, connect=5.0)) as client:
                response = client.post(f"{base}{path}", json=payload,
                                       headers=self._headers())
        except Exception as error:  # noqa: BLE001 - 传输失败如实抛
            raise ExperimentSandboxError(
                "SANDBOX_UNAVAILABLE",
                f"执行控制服务不可达（{type(error).__name__}）；未执行任何命令。",
            ) from error
        return self._read_json(response, path)

    async def _apost(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        base = self._require_configured()
        try:
            async with httpx.AsyncClient(
                    transport=self._transport,
                    timeout=httpx.Timeout(self._timeout_s, connect=5.0)) as client:
                response = await client.post(f"{base}{path}", json=payload,
                                             headers=self._headers())
        except Exception as error:  # noqa: BLE001
            raise ExperimentSandboxError(
                "SANDBOX_UNAVAILABLE",
                f"执行控制服务不可达（{type(error).__name__}）；未执行任何命令。",
            ) from error
        return self._read_json(response, path)

    def _put(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        base = self._require_configured()
        try:
            with httpx.Client(transport=self._transport,
                              timeout=httpx.Timeout(self._timeout_s, connect=5.0)) as client:
                response = client.put(f"{base}{path}", json=payload,
                                      headers=self._headers())
        except Exception as error:  # noqa: BLE001
            raise ExperimentSandboxError(
                "SANDBOX_UNAVAILABLE",
                f"执行控制服务不可达（{type(error).__name__}）。",
            ) from error
        return self._read_json(response, path)

    async def _aput(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        base = self._require_configured()
        try:
            async with httpx.AsyncClient(
                    transport=self._transport,
                    timeout=httpx.Timeout(self._timeout_s, connect=5.0)) as client:
                response = await client.put(f"{base}{path}", json=payload,
                                            headers=self._headers())
        except Exception as error:  # noqa: BLE001
            raise ExperimentSandboxError(
                "SANDBOX_UNAVAILABLE",
                f"执行控制服务不可达（{type(error).__name__}）。",
            ) from error
        return self._read_json(response, path)

    async def _aget(self, path: str) -> tuple[int, dict[str, Any]]:
        base = self._require_configured()
        try:
            async with httpx.AsyncClient(
                    transport=self._transport,
                    timeout=httpx.Timeout(self._timeout_s, connect=5.0)) as client:
                response = await client.get(f"{base}{path}", headers=self._headers())
        except Exception as error:  # noqa: BLE001
            raise ExperimentSandboxError(
                "SANDBOX_UNAVAILABLE",
                f"执行控制服务不可达（{type(error).__name__}）。",
            ) from error
        try:
            data = response.json()
        except ValueError:
            data = {}
        return response.status_code, data if isinstance(data, dict) else {}

    def _get(self, path: str) -> tuple[int, dict[str, Any]]:
        base = self._require_configured()
        try:
            with httpx.Client(transport=self._transport,
                              timeout=httpx.Timeout(self._timeout_s, connect=5.0)) as client:
                response = client.get(f"{base}{path}", headers=self._headers())
        except Exception as error:  # noqa: BLE001
            raise ExperimentSandboxError(
                "SANDBOX_UNAVAILABLE",
                f"执行控制服务不可达（{type(error).__name__}）。",
            ) from error
        try:
            data = response.json()
        except ValueError:
            data = {}
        return response.status_code, data if isinstance(data, dict) else {}

    @staticmethod
    def _read_json(response: Any, path: str) -> dict[str, Any]:
        if response.status_code >= 400:
            raise ExperimentSandboxError(
                "SANDBOX_REQUEST_REJECTED",
                f"执行控制服务拒绝请求（HTTP {response.status_code} {path}）；未执行。",
            )
        try:
            data = response.json()
        except ValueError as error:
            raise ExperimentSandboxError(
                "SANDBOX_BAD_RESPONSE", "执行控制服务返回非 JSON。"
            ) from error
        if not isinstance(data, dict):
            raise ExperimentSandboxError(
                "SANDBOX_BAD_RESPONSE", "执行控制服务返回非对象 JSON。"
            )
        return data

    # -- 实例生命周期 ----------------------------------------------------

    def _ensure_sandbox(self) -> str:
        """幂等 ensure（PUT，同 run 重复返回原实例）；结果缓存，失败即抛。"""
        if self._ensured and self._sandbox_id:
            return self._sandbox_id
        data = self._put(f"/sandboxes/{quote(self._run_id, safe='')}", {})
        sandbox_id = str(data.get("sandbox_id") or "")
        if not sandbox_id:
            raise ExperimentSandboxError(
                "SANDBOX_ENSURE_FAILED", "执行控制服务未返回 sandbox_id。"
            )
        self._sandbox_id = sandbox_id
        self._ensured = True
        return sandbox_id

    async def _aensure_sandbox(self) -> str:
        if self._ensured and self._sandbox_id:
            return self._sandbox_id
        data = await self._aput(f"/sandboxes/{quote(self._run_id, safe='')}", {})
        sandbox_id = str(data.get("sandbox_id") or "")
        if not sandbox_id:
            raise ExperimentSandboxError(
                "SANDBOX_ENSURE_FAILED", "执行控制服务未返回 sandbox_id。"
            )
        self._sandbox_id = sandbox_id
        self._ensured = True
        return sandbox_id

    def _new_operation_id(self) -> str:
        self._op_seq += 1
        return f"{self._run_id}-op-{self._op_seq:04d}"

    # -- 命令执行 ----------------------------------------------------------

    def execute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        """提交命令并等待终态；超时返回当前尾部（exit_code=None），不重发。

        调用方凭 last_operation_id + query_operation() 续查/取消。超时参数
        即轮询截止（None → 默认截止）；HTTP 超时不等同进程已停止。
        """
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command 不能为空")
        self._ensure_sandbox()
        operation_id = self._new_operation_id()
        self.last_operation_id = operation_id
        self.submitted_ops.append((operation_id, command))
        data = self._post(
            f"/sandboxes/{quote(self._run_id, safe='')}/operations",
            {"operation_id": operation_id, "command": command,
             "timeout_s": timeout},
        )
        operation = data.get("operation") if isinstance(data.get("operation"), dict) else data
        if str(operation.get("operation_id") or "") != operation_id:
            raise ExperimentSandboxError(
                "SANDBOX_ID_MISMATCH",
                "控制服务返回的 operation_id 与提交不一致；结果不可信，未重试。",
            )
        if str(operation.get("status") or "") in TERMINAL_OPERATION_STATUSES:
            return _operation_to_response(operation)
        deadline = timeout if timeout and timeout > 0 else self._default_deadline_s
        end = time.monotonic() + max(deadline, self._poll_interval_s)
        last: dict[str, Any] = operation
        while True:
            _, current = self._get(
                f"/sandboxes/{quote(self._run_id, safe='')}/operations/{quote(operation_id, safe='')}")
            if current:
                last = current
            if str(last.get("status") or "") in TERMINAL_OPERATION_STATUSES:
                return _operation_to_response(last)
            if time.monotonic() >= end:
                # 超时≠停止：返回当前尾部，调用方用同一 id 续查/取消。
                tail = _operation_to_response(last)
                return ExecuteResponse(output=tail.output, exit_code=None, truncated=True)
            time.sleep(self._poll_interval_s)

    async def aexecute(
        self,
        command: str,
        *,
        timeout: int | None = None,  # noqa: ASYNC109 - 转发给后端的语义参数
    ) -> ExecuteResponse:
        """execute 的真异步实现（不经过 to_thread 直转同步版）。"""
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command 不能为空")
        await self._aensure_sandbox()
        operation_id = self._new_operation_id()
        self.last_operation_id = operation_id
        self.submitted_ops.append((operation_id, command))
        data = await self._apost(
            f"/sandboxes/{quote(self._run_id, safe='')}/operations",
            {"operation_id": operation_id, "command": command,
             "timeout_s": timeout},
        )
        operation = data.get("operation") if isinstance(data.get("operation"), dict) else data
        if str(operation.get("operation_id") or "") != operation_id:
            raise ExperimentSandboxError(
                "SANDBOX_ID_MISMATCH",
                "控制服务返回的 operation_id 与提交不一致；结果不可信，未重试。",
            )
        if str(operation.get("status") or "") in TERMINAL_OPERATION_STATUSES:
            return _operation_to_response(operation)
        deadline = timeout if timeout and timeout > 0 else self._default_deadline_s
        end = time.monotonic() + max(deadline, self._poll_interval_s)
        last: dict[str, Any] = operation
        while True:
            _, current = await self._aget(
                f"/sandboxes/{quote(self._run_id, safe='')}/operations/{quote(operation_id, safe='')}")
            if current:
                last = current
            if str(last.get("status") or "") in TERMINAL_OPERATION_STATUSES:
                return _operation_to_response(last)
            if time.monotonic() >= end:
                tail = _operation_to_response(last)
                return ExecuteResponse(output=tail.output, exit_code=None, truncated=True)
            await asyncio.sleep(self._poll_interval_s)

    async def query_operation(self, operation_id: str) -> dict[str, Any]:
        """按 id 查询操作（结果/日志游标）；供超时续查与 T5 对账。

        控制服务无此操作 → status=unknown（诚实未知，不重放执行）。
        """
        operation_id = (operation_id or "").strip()[:128]
        if not operation_id:
            raise ValueError("operation_id 不能为空")
        status, data = await self._aget(
            f"/sandboxes/{quote(self._run_id, safe='')}/operations/{quote(operation_id, safe='')}")
        if status == 404 or not data:
            return {"operation_id": operation_id, "status": "unknown",
                    "exit_code": None, "output_tail": "", "output_truncated": False}
        data.setdefault("operation_id", operation_id)
        return data

    async def cancel(self) -> dict[str, Any]:
        """取消运行操作并回收实例（run 级；重复返回同一终态由服务端保证）。"""
        return await self._apost(
            f"/sandboxes/{quote(self._run_id, safe='')}/cancel", {})

    async def sandbox_status(self) -> dict[str, Any]:
        """生命周期/活跃 operation/资源与日志摘要（T5 对账用）。"""
        _, data = await self._aget(f"/sandboxes/{quote(self._run_id, safe='')}")
        return data

    # -- 文件传输 ------------------------------------------------------------

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """批量上传（逐文件 PUT；path 限定工作区，服务端再验）。"""
        responses: list[FileUploadResponse] = []
        for path, content in files or []:
            responses.append(self._upload_one(path, content))
        return responses

    def _upload_one(self, path: str, content: bytes) -> FileUploadResponse:
        try:
            safe_path = _check_sandbox_path(path)
        except ValueError as error:
            return FileUploadResponse(path=str(path), error=str(error))
        if not isinstance(content, (bytes, bytearray)):
            return FileUploadResponse(path=safe_path, error="content 须为字节")
        if len(content) > _FILE_MAX_BYTES:
            return FileUploadResponse(
                path=safe_path,
                error=f"文件过大（>{_FILE_MAX_BYTES} 字节）；正式交付走 Artifact 通道",
            )
        try:
            self._ensure_sandbox()
        except ExperimentSandboxError as error:
            return FileUploadResponse(path=safe_path, error=f"{error.code}：{error}")
        base = self._require_configured()
        try:
            with httpx.Client(transport=self._transport,
                              timeout=httpx.Timeout(self._timeout_s, connect=5.0)) as client:
                response = client.put(
                    f"{base}/sandboxes/{quote(self._run_id, safe='')}"
                    f"/files{quote(safe_path, safe='/')}",
                    content=bytes(content),
                    headers={"Authorization": f"Bearer {self._token}"} if self._token else {},
                )
        except Exception as error:  # noqa: BLE001
            return FileUploadResponse(
                path=safe_path, error=f"上传失败（{type(error).__name__}）")
        if response.status_code >= 400:
            detail = ""
            try:
                detail = str(response.json().get("detail") or response.json().get("code") or "")
            except ValueError:
                detail = response.text[:120]
            return FileUploadResponse(
                path=safe_path, error=f"服务端拒绝（HTTP {response.status_code}）{detail}")
        return FileUploadResponse(path=safe_path, error=None)

    async def aupload_files(
        self, files: list[tuple[str, bytes]]
    ) -> list[FileUploadResponse]:
        """upload_files 的真异步实现。"""
        responses: list[FileUploadResponse] = []
        for path, content in files or []:
            try:
                safe_path = _check_sandbox_path(path)
            except ValueError as error:
                responses.append(FileUploadResponse(path=str(path), error=str(error)))
                continue
            if not isinstance(content, (bytes, bytearray)):
                responses.append(FileUploadResponse(path=safe_path, error="content 须为字节"))
                continue
            if len(content) > _FILE_MAX_BYTES:
                responses.append(FileUploadResponse(
                    path=safe_path,
                    error=f"文件过大（>{_FILE_MAX_BYTES} 字节）；正式交付走 Artifact 通道"))
                continue
            try:
                await self._aensure_sandbox()
            except ExperimentSandboxError as error:
                responses.append(FileUploadResponse(
                    path=safe_path, error=f"{error.code}：{error}"))
                continue
            base = self._require_configured()
            try:
                async with httpx.AsyncClient(
                        transport=self._transport,
                        timeout=httpx.Timeout(self._timeout_s, connect=5.0)) as client:
                    response = await client.put(
                        f"{base}/sandboxes/{quote(self._run_id, safe='')}"
                        f"/files{quote(safe_path, safe='/')}",
                        content=bytes(content),
                        headers={"Authorization": f"Bearer {self._token}"} if self._token else {},
                    )
            except Exception as error:  # noqa: BLE001
                responses.append(FileUploadResponse(
                    path=safe_path, error=f"上传失败（{type(error).__name__}）"))
                continue
            if response.status_code >= 400:
                detail = ""
                try:
                    detail = str(response.json().get("detail") or response.json().get("code") or "")
                except ValueError:
                    detail = response.text[:120]
                responses.append(FileUploadResponse(
                    path=safe_path,
                    error=f"服务端拒绝（HTTP {response.status_code}）{detail}"))
                continue
            responses.append(FileUploadResponse(path=safe_path, error=None))
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """批量下载（逐文件 GET；超限/缺失如实错误，不截断冒充完整）。"""
        return [self._download_one(path) for path in paths or []]

    def _download_one(self, path: str) -> FileDownloadResponse:
        try:
            safe_path = _check_sandbox_path(path)
        except ValueError as error:
            return FileDownloadResponse(path=str(path), content=None, error=str(error))
        try:
            self._ensure_sandbox()
        except ExperimentSandboxError as error:
            return FileDownloadResponse(path=safe_path, content=None,
                                        error=f"{error.code}：{error}")
        status, data, raw = self._download_raw(safe_path)
        if status == 404:
            return FileDownloadResponse(path=safe_path, content=None,
                                        error="file_not_found")
        if status != 200 or raw is None:
            detail = str(data.get("detail") or data.get("code") or "")[:120]
            return FileDownloadResponse(
                path=safe_path, content=None,
                error=f"下载失败（HTTP {status}）{detail}")
        if len(raw) > _FILE_MAX_BYTES:
            return FileDownloadResponse(path=safe_path, content=None,
                                        error="file_too_large")
        return FileDownloadResponse(path=safe_path, content=raw, error=None)

    def _download_raw(self, safe_path: str) -> tuple[int, dict[str, Any], bytes | None]:
        base = self._require_configured()
        try:
            with httpx.Client(transport=self._transport,
                              timeout=httpx.Timeout(self._timeout_s, connect=5.0)) as client:
                response = client.get(
                    f"{base}/sandboxes/{quote(self._run_id, safe='')}"
                    f"/files{quote(safe_path, safe='/')}",
                    headers={"Authorization": f"Bearer {self._token}"} if self._token else {},
                )
        except Exception as error:  # noqa: BLE001
            return 0, {"code": type(error).__name__}, None
        try:
            data = response.json()
            if isinstance(data, dict) and isinstance(data.get("content_b64"), str):
                import base64

                return response.status_code, data, base64.b64decode(data["content_b64"])
        except ValueError:
            pass
        if response.status_code == 200:
            return 200, {}, bytes(response.content)
        try:
            data = response.json()
        except ValueError:
            data = {}
        return response.status_code, data if isinstance(data, dict) else {}, None

    async def adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """download_files 的真异步实现。"""
        out: list[FileDownloadResponse] = []
        for path in paths or []:
            try:
                safe_path = _check_sandbox_path(path)
            except ValueError as error:
                out.append(FileDownloadResponse(path=str(path), content=None,
                                                error=str(error)))
                continue
            try:
                await self._aensure_sandbox()
            except ExperimentSandboxError as error:
                out.append(FileDownloadResponse(path=safe_path, content=None,
                                                error=f"{error.code}：{error}"))
                continue
            base = self._require_configured()
            try:
                async with httpx.AsyncClient(
                        transport=self._transport,
                        timeout=httpx.Timeout(self._timeout_s, connect=5.0)) as client:
                    response = await client.get(
                        f"{base}/sandboxes/{quote(self._run_id, safe='')}"
                        f"/files{quote(safe_path, safe='/')}",
                        headers={"Authorization": f"Bearer {self._token}"} if self._token else {},
                    )
            except Exception as error:  # noqa: BLE001
                out.append(FileDownloadResponse(
                    path=safe_path, content=None,
                    error=f"下载失败（{type(error).__name__}）"))
                continue
            if response.status_code == 404:
                out.append(FileDownloadResponse(path=safe_path, content=None,
                                                error="file_not_found"))
                continue
            if response.status_code != 200:
                try:
                    detail = str(response.json().get("detail") or "")[:120]
                except ValueError:
                    detail = response.text[:120]
                out.append(FileDownloadResponse(
                    path=safe_path, content=None,
                    error=f"下载失败（HTTP {response.status_code}）{detail}"))
                continue
            raw = bytes(response.content)
            if len(raw) > _FILE_MAX_BYTES:
                out.append(FileDownloadResponse(path=safe_path, content=None,
                                                error="file_too_large"))
                continue
            out.append(FileDownloadResponse(path=safe_path, content=raw, error=None))
        return out
