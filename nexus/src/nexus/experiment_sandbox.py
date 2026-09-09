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


_WORKSPACE_ROOT = "/workspace"


def _check_sandbox_path(path: str, root: str = _WORKSPACE_ROOT) -> str:
    """客户端侧路径底线校验（服务端 authoritative 再验）。

    只接受绝对路径；拒绝空、NUL 与任何 `..` 段（目录逃逸）；并要求落在任务
    工作区根内（任务书 §2：path 限定任务工作区，遍历/symlink 逃逸拒绝）。
    """
    if not isinstance(path, str) or not path.startswith("/") or "\x00" in path:
        raise ValueError(f"非法沙箱路径：{path!r}（须为绝对路径）")
    segments = [seg for seg in path.split("/") if seg not in ("", ".")]
    if ".." in segments:
        raise ValueError(f"非法沙箱路径：{path!r}（禁止父目录逃逸）")
    normalized_root = "/" + (root or _WORKSPACE_ROOT).strip("/")
    if path != normalized_root and not path.startswith(normalized_root + "/"):
        raise ValueError(
            f"非法沙箱路径：{path!r}（须位于任务工作区 {normalized_root} 内）")
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


def _operation_ref_note(operation_id: str, elapsed_s: float, session: bool) -> str:
    """F3：在途 op 引用注记（模型跟进凭据；exit None 不得当失败重跑）。

    会话操作 → 可 describe 续查、可 interrupt 中断；一次性在途 → 只能等
    待完成（无中断语义），不得重发。
    """
    if session:
        return (
            f"\n[operation {operation_id} 仍在运行（约 {elapsed_s:.0f}s）。"
            "用 describe_operation 续查增量输出，或 interrupt_operation 中断后"
            "继续排错；不要把“未出退出码”当失败重发同一命令。]")
    return (
        f"\n[operation {operation_id} 仍在运行（约 {elapsed_s:.0f}s，一次性执行"
        "无中断语义）。等待其完成，不要重发；完成后退出码以续查为准。]")


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
        scope_hash: str = "",
        resources: dict[str, Any] | None = None,
        workspace_root: str = _WORKSPACE_ROOT,
        transport: Any = None,
        initial_seq: int = 0,
        fencing: str = "",
    ) -> None:
        self._run_id = (run_id or "").strip()[:64]
        self._base_url = (base_url or "").rstrip("/")
        self._token = token or ""
        self._timeout_s = max(1.0, float(timeout_s or _HTTP_TIMEOUT_S))
        self._poll_interval_s = max(0.05, float(poll_interval_s))
        self._default_deadline_s = max(1.0, float(default_poll_deadline_s))
        # §2：ensure 携带授权 scope_hash（同 run 异 hash → 控制面 409）与
        # 已确认的资源声明（服务端据此派生容器限额）。
        self._scope_hash = (scope_hash or "").strip()[:128]
        self._resources = dict(resources or {})
        self._workspace_root = "/" + (workspace_root or _WORKSPACE_ROOT).strip("/")
        self._transport = transport
        # F2：序号由持久意图派生（调用方传 run 现 attempt_no），Backend 重建
        # 不归零——否则新命令复用旧 operation_id，控制面返回旧记录吞掉新命令。
        self._op_seq = max(0, int(initial_seq or 0))
        # F2：执行 fencing（租约持有者的单调令牌；控制面拒绝旧 token 新提交）。
        self._fencing = (fencing or "").strip()[:128]
        self._sandbox_id = ""
        self._ensured = False
        # T4 图层续跑用：最近一次 execute 提交/查询的 operation_id。
        self.last_operation_id = ""
        # T5-1：提交日志（operation_id, command），供执行器把工具结果
        # 精确归因到 control operation（并行调用下 last_operation_id 会错位）。
        self.submitted_ops: list[tuple[str, str]] = []
        # F3：最近一次提交的运行态（operation_id→ 是否会话在途）。
        # 图层据此决定 attempt 延迟落盘（在途不记完成）与 op 引用注入。
        self.last_operation_running = False
        self.last_operation_session = False

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
            detail = ""
            try:
                body = response.json()
                if isinstance(body, dict):
                    detail = str(body.get("detail") or "")
            except ValueError:
                detail = ""
            # F2：同 id 不同请求 → 调用方必须先对账（query），不得重跑。
            if response.status_code == 409 and "OPERATION_ID_CONFLICT" in detail:
                raise ExperimentSandboxError("OPERATION_ID_CONFLICT", detail[:300])
            # F2：旧 token 新提交被拒 → 调用方先对账，由现持有者提交。
            if response.status_code == 409 and "FENCING_REJECTED" in detail:
                raise ExperimentSandboxError("FENCING_REJECTED", detail[:300])
            # F4：构建器未交付 → 调用方按构建路线 fail-closed（不等同基础镜像）。
            if response.status_code == 501 and "BUILDER_NOT_CONFIGURED" in detail:
                raise ExperimentSandboxError("BUILDER_NOT_CONFIGURED", detail[:300])
            raise ExperimentSandboxError(
                "SANDBOX_REQUEST_REJECTED",
                f"执行控制服务拒绝请求（HTTP {response.status_code} {path}）；未执行。"
                + (f"（{detail[:160]}）" if detail else ""),
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

    def _ensure_payload(self) -> dict[str, Any]:
        """ensure 请求体：授权 scope_hash ＋ 已确认资源（§2）。"""
        payload: dict[str, Any] = {}
        if self._scope_hash:
            payload["scope_hash"] = self._scope_hash
        if self._resources:
            payload["resources"] = dict(self._resources)
        return payload

    def _ensure_sandbox(self) -> str:
        """幂等 ensure（PUT，同 run 同 scope 返回原实例）；结果缓存，失败即抛。"""
        if self._ensured and self._sandbox_id:
            return self._sandbox_id
        data = self._put(f"/sandboxes/{quote(self._run_id, safe='')}",
                         self._ensure_payload())
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
        data = await self._aput(f"/sandboxes/{quote(self._run_id, safe='')}",
                                self._ensure_payload())
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

    def reset_seq(self, seq: int) -> int:
        """F2：恢复后把序号对齐到已落盘 attempt（只增不减，不复用旧 id）。"""
        try:
            target = max(0, int(seq or 0))
        except (TypeError, ValueError):
            return self._op_seq
        if target > self._op_seq:
            self._op_seq = target
        return self._op_seq

    def set_fencing(self, fencing: str) -> str:
        """F2：设置本次执行的 fencing（租约令牌；随提交携带）。"""
        self._fencing = (fencing or "").strip()[:128]
        return self._fencing

    async def rotate_fencing(self) -> dict[str, Any]:
        """F2：把控制面 run fencing 轮换为本次令牌（恢复接管后新持有者调用）。

        终态/未知 run → 控制面 404/409，调用方如实处理，不伪装接管。
        旧控制面无此端点（404）→ FENCING_UNSUPPORTED，调用方可降级为
        无 fencing 旧语义（控制面忽略未知字段），并记日志留痕。
        """
        if not self._fencing:
            raise ExperimentSandboxError(
                "FENCING_EMPTY", "本次无 fencing 令牌，不得轮换控制面。")
        try:
            data = await self._apost(
                f"/sandboxes/{quote(self._run_id, safe='')}/fencing",
                {"fencing": self._fencing})
        except ExperimentSandboxError as error:
            if "HTTP 404" in str(error):
                raise ExperimentSandboxError(
                    "FENCING_UNSUPPORTED",
                    "控制面无 fencing 端点（旧版本），按无 fencing 语义执行。") from error
            raise
        if str(data.get("fencing") or "") != self._fencing:
            raise ExperimentSandboxError(
                "FENCING_ROTATE_MISMATCH", "控制面返回的 fencing 与提交不一致。")
        return data

    @staticmethod
    def _route_session(command: str) -> bool:
        """F3：语义路由（安装/下载/实验执行等关联命令走会话）。

        environment/target → 会话（保持 cd/环境状态，串行，可中断）；
        probe/diagnostic/verification/file_tool → 一次性（独立无状态）。
        不仅按 timeout 判断；分类失败默认一次性（fail-closed 小 blast）。
        """
        try:
            from nexus import experiment_contracts as contracts_module

            return contracts_module.classify_operation(command or "") in (
                "environment", "target")
        except Exception:  # noqa: BLE001 - 分类不可用即一次性
            return False

    def _prepare_submit(
        self, command: str, timeout: int | None, session: bool = False,
    ) -> tuple[str, dict[str, Any], Any | None]:
        """F2：提交前意图登记，返回 (operation_id, payload, 终态缓存)。

        - 新意图 → prepared 落盘后才允许 submit（登记失败即抛，不执行）；
        - 同 id 同请求且意图已终态 → 返回缓存响应，不再 submit（不重复执行）；
        - 同 id 不同请求 → OPERATION_ID_CONFLICT（旧进程无退出证明不得重跑，
          调用方先 query 对账）。
        F3：session 标记随 payload 下传（会话执行＋增量＋可中断）。
        """
        from nexus import experiment_operations as operations_module

        # 多态 id（含重放 nonce 后缀）：先取 id 再登记，意图键与提交 id 一致。
        operation_id = self._new_operation_id()
        try:
            prepared = operations_module.prepare_intent(
                run_id=self._run_id, seq=int(self._op_seq), command=command,
                timeout_s=timeout, operation_id=operation_id)
        except Exception as error:
            code = getattr(error, "code", type(error).__name__)
            raise ExperimentSandboxError(
                code, f"操作意图登记失败，未提交执行：{error}") from error
        payload = {
            "operation_id": operation_id, "command": command,
            "timeout_s": timeout,
            "request_hash": operations_module.request_hash(command, timeout),
            "session": bool(session),
        }
        if self._fencing:
            payload["fencing"] = self._fencing
        if prepared.get("deduped") and str(
                prepared["intent"].get("status") or "") in (
                    "succeeded", "failed", "cancelled", "timed_out"):
            cached = _operation_to_response({
                "status": prepared["intent"]["status"],
                "exit_code": prepared["intent"].get("exit_code"),
                "output_tail": prepared["intent"].get("output_tail") or "",
                "output_truncated": True,
            })
            return operation_id, payload, cached
        return operation_id, payload, None

    @staticmethod
    def _track_intent(run_id: str, operation_id: str, status: str, *,
                      exit_code: int | None = None, output_tail: str = "") -> None:
        """意图状态推进（best-effort：失败只记日志，不推翻执行结果）。"""
        try:
            from nexus import experiment_operations as operations_module

            operations_module.set_intent_status(
                run_id, operation_id, status,
                exit_code=exit_code, output_tail=output_tail)
        except Exception as error:  # noqa: BLE001
            logger.warning("intent track failed for %s: %s",
                           operation_id, type(error).__name__)

    # -- 命令执行 ----------------------------------------------------------

    def execute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        """提交命令并等待终态；超时返回当前尾部（exit_code=None），不重发。

        F3：environment/target 类命令走 run 会话（可中断＋增量）；
        其余一次性。调用方凭 last_operation_id + query_operation() 续查/
        取消；在途返回附 op 引用（模型用 describe/interrupt 工具跟进，
        不得把 exit None 当失败立即重跑）。
        """
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command 不能为空")
        self._ensure_sandbox()
        session = self._route_session(command)
        operation_id, payload, cached = self._prepare_submit(
            command, timeout, session=session)
        if cached is not None:
            self.last_operation_id = operation_id
            self.last_operation_running = False
            self.last_operation_session = session
            self.submitted_ops.append((operation_id, command))
            return cached
        self.last_operation_id = operation_id
        self.last_operation_running = True
        self.last_operation_session = session
        self.submitted_ops.append((operation_id, command))
        self._track_intent(self._run_id, operation_id, "submitted")
        data = self._post(
            f"/sandboxes/{quote(self._run_id, safe='')}/operations",
            payload,
        )
        operation = data.get("operation") if isinstance(data.get("operation"), dict) else data
        if str(operation.get("operation_id") or "") != operation_id:
            raise ExperimentSandboxError(
                "SANDBOX_ID_MISMATCH",
                "控制服务返回的 operation_id 与提交不一致；结果不可信，未重试。",
            )
        if str(operation.get("status") or "") in TERMINAL_OPERATION_STATUSES:
            response = _operation_to_response(operation)
            self.last_operation_running = False
            self._track_intent(
                self._run_id, operation_id, str(operation.get("status") or ""),
                exit_code=response.exit_code, output_tail=response.output)
            return response
        deadline = timeout if timeout and timeout > 0 else self._default_deadline_s
        end = time.monotonic() + max(deadline, self._poll_interval_s)
        started = time.monotonic()
        last: dict[str, Any] = operation
        text = str(operation.get("output_tail") or "")
        cursor = len(text)
        polls = 0
        while True:
            polls += 1
            probe = session and polls % 6 == 0
            _, current = self._get(
                f"/sandboxes/{quote(self._run_id, safe='')}/operations/{quote(operation_id, safe='')}"
                f"?cursor={cursor}&probe={1 if probe else 0}")
            if current:
                last = current
                increment = str(current.get("increment") or "")
                if current.get("reset"):
                    text = increment
                else:
                    text += increment
                try:
                    cursor = int(current.get("offset", cursor))
                except (TypeError, ValueError):
                    pass
            if str(last.get("status") or "") in TERMINAL_OPERATION_STATUSES:
                response = _operation_to_response(last)
                self.last_operation_running = False
                self._track_intent(
                    self._run_id, operation_id, str(last.get("status") or ""),
                    exit_code=response.exit_code, output_tail=response.output)
                return response
            if time.monotonic() >= end:
                # 超时≠停止：返回当前增量尾部＋op 引用，调用方续查/中断。
                self._track_intent(self._run_id, operation_id, "running")
                return ExecuteResponse(
                    output=text + _operation_ref_note(
                        operation_id, time.monotonic() - started, session),
                    exit_code=None, truncated=True)
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
        session = self._route_session(command)
        operation_id, payload, cached = self._prepare_submit(
            command, timeout, session=session)
        if cached is not None:
            self.last_operation_id = operation_id
            self.last_operation_running = False
            self.last_operation_session = session
            self.submitted_ops.append((operation_id, command))
            return cached
        self.last_operation_id = operation_id
        self.last_operation_running = True
        self.last_operation_session = session
        self.submitted_ops.append((operation_id, command))
        self._track_intent(self._run_id, operation_id, "submitted")
        data = await self._apost(
            f"/sandboxes/{quote(self._run_id, safe='')}/operations",
            payload,
        )
        operation = data.get("operation") if isinstance(data.get("operation"), dict) else data
        if str(operation.get("operation_id") or "") != operation_id:
            raise ExperimentSandboxError(
                "SANDBOX_ID_MISMATCH",
                "控制服务返回的 operation_id 与提交不一致；结果不可信，未重试。",
            )
        if str(operation.get("status") or "") in TERMINAL_OPERATION_STATUSES:
            response = _operation_to_response(operation)
            self.last_operation_running = False
            self._track_intent(
                self._run_id, operation_id, str(operation.get("status") or ""),
                exit_code=response.exit_code, output_tail=response.output)
            return response
        deadline = timeout if timeout and timeout > 0 else self._default_deadline_s
        end = time.monotonic() + max(deadline, self._poll_interval_s)
        started = time.monotonic()
        last: dict[str, Any] = operation
        text = str(operation.get("output_tail") or "")
        cursor = len(text)
        polls = 0
        while True:
            polls += 1
            probe = session and polls % 6 == 0
            _, current = await self._aget(
                f"/sandboxes/{quote(self._run_id, safe='')}/operations/{quote(operation_id, safe='')}"
                f"?cursor={cursor}&probe={1 if probe else 0}")
            if current:
                last = current
                increment = str(current.get("increment") or "")
                if current.get("reset"):
                    text = increment
                else:
                    text += increment
                try:
                    cursor = int(current.get("offset", cursor))
                except (TypeError, ValueError):
                    pass
            if str(last.get("status") or "") in TERMINAL_OPERATION_STATUSES:
                response = _operation_to_response(last)
                self.last_operation_running = False
                self._track_intent(
                    self._run_id, operation_id, str(last.get("status") or ""),
                    exit_code=response.exit_code, output_tail=response.output)
                return response
            if time.monotonic() >= end:
                self._track_intent(self._run_id, operation_id, "running")
                return ExecuteResponse(
                    output=text + _operation_ref_note(
                        operation_id, time.monotonic() - started, session),
                    exit_code=None, truncated=True)
            await asyncio.sleep(self._poll_interval_s)

    async def query_operation(
        self, operation_id: str, cursor: int = 0, probe: bool = False,
    ) -> dict[str, Any]:
        """按 id 查询操作（结果/日志游标＋可选探针采信）；供超时续查与对账。

        控制服务无此操作 → status=unknown（诚实未知，不重放执行）。
        """
        operation_id = (operation_id or "").strip()[:128]
        if not operation_id:
            raise ValueError("operation_id 不能为空")
        try:
            cursor = max(0, int(cursor or 0))
        except (TypeError, ValueError):
            cursor = 0
        status, data = await self._aget(
            f"/sandboxes/{quote(self._run_id, safe='')}/operations/{quote(operation_id, safe='')}"
            f"?cursor={cursor}&probe={1 if probe else 0}")
        if status == 404 or not data:
            return {"operation_id": operation_id, "status": "unknown",
                    "exit_code": None, "output_tail": "", "output_truncated": False,
                    "increment": "", "offset": cursor, "reset": True}
        data.setdefault("operation_id", operation_id)
        return data

    async def cancel_operation(self, operation_id: str) -> dict[str, Any]:
        """F3：操作级取消（只停该命令；整体取消仍走 cancel()）。

        one-shot 在途 → 控制面 409（无中断语义，不伪装）；fencing 过期
        → FENCING_REJECTED。调用方（中断工具）据此如实转述。
        """
        operation_id = (operation_id or "").strip()[:128]
        if not operation_id:
            raise ValueError("operation_id 不能为空")
        return await self._apost(
            f"/sandboxes/{quote(self._run_id, safe='')}/operations/{quote(operation_id, safe='')}/cancel",
            {"fencing": self._fencing or ""})

    async def cancel(self) -> dict[str, Any]:
        """取消运行操作并回收实例（run 级；重复返回同一终态由服务端保证）。"""
        return await self._apost(
            f"/sandboxes/{quote(self._run_id, safe='')}/cancel", {})

    async def start_build(self, repo_url: str, revision: str,
                          timeout_s: float | None = None) -> dict[str, Any]:
        """F4：提交 repo2docker 构建作业（固定源码输入；先登记后执行）。

        构建器未配置 → BUILDER_NOT_CONFIGURED（fail-closed）。调用方
        （执行核）轮询 query_build；fencing 随带（旧 token 拒绝）。
        """
        repo_url = (repo_url or "").strip()[:500]
        revision = (revision or "").strip()[:128]
        if not repo_url or not revision:
            raise ValueError("构建仓库地址/修订不能为空")
        return await self._apost(
            f"/sandboxes/{quote(self._run_id, safe='')}/builds",
            {"repo_url": repo_url, "revision": revision,
             "timeout_s": timeout_s, "fencing": self._fencing or ""})

    async def query_build(self, build_id: str) -> dict[str, Any]:
        """F4：查询构建作业（未知 id 即 unknown，不重建）。"""
        build_id = (build_id or "").strip()[:128]
        if not build_id:
            raise ValueError("build_id 不能为空")
        status, data = await self._aget(
            f"/sandboxes/{quote(self._run_id, safe='')}/builds/{quote(build_id, safe='')}")
        if status == 404 or not data:
            return {"build_id": build_id, "status": "unknown"}
        data.setdefault("build_id", build_id)
        return data

    async def migrate_image(self, image: str) -> dict[str, Any]:
        """F4：同 run 迁移到执行镜像（构建成功后；scope_hash 不变）。

        有在途操作即 409（调用方先取消/等待）；终态 run 拒绝。
        成功刷新本地 sandbox 绑定（旧实例已回收，后续提交进新容器）。
        """
        image = (image or "").strip()[:256]
        if not image:
            raise ValueError("执行镜像不能为空")
        data = await self._aput(
            f"/sandboxes/{quote(self._run_id, safe='')}",
            {"image": image})
        if str(data.get("sandbox_id") or ""):
            self._sandbox_id = str(data["sandbox_id"])
            self._ensured = True
        return data

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
            safe_path = _check_sandbox_path(path, self._workspace_root)
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
                safe_path = _check_sandbox_path(path, self._workspace_root)
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
            safe_path = _check_sandbox_path(path, self._workspace_root)
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
                safe_path = _check_sandbox_path(path, self._workspace_root)
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
