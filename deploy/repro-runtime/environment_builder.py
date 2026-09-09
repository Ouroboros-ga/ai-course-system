"""F4 repo2docker 窄适配（deploy/repro-runtime/environment_builder.py）。

定位：构建作业契约＋外部构建器 HTTP 客户端薄封装，不实现构建内核——
不支持声明解析、不求解依赖、不管理 Docker daemon。repo2docker 的配置
解析与构建流程由构建器承担；本项目只做固定源码输入、隔离构建委托、
构建作业与镜像结果回传（见计划 §9/F4-6/7）。

隔离要求（F4-6）：构建在受限构建设施执行，daemon/凭据只属于可信控制面，
不把宿主 Docker socket 暴露给项目代码。本模块只经 HTTPS 与已配置的构建
器地址通信（token 经环境变量，不进日志/业务记录）。

运行时接入（F4-7）：repo2docker 产物不假定自带 SWE-ReX 运行时；构建请求
携带 appendix（固定版本 swerex 服务端安装），记录项目构建镜像与实际执行
镜像两种身份及对应关系（见 BuildResult）。
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger("repro_runtime.environment_builder")

# 固定版本运行时 appendix（构建出的执行镜像必须能跑控制面协议）。
# 版本与控制面 venv 的 swe-rex 对齐（当前 1.4.0），升级需同步改此处并记录。
SWEREX_APPENDIX_LINES = (
    "RUN pip install --no-cache-dir swerex==1.4.0",
)
BUILD_JOB_TIMEOUT_S = 1800.0


class BuilderError(Exception):
    """构建域失败：携带机器可读 code（fail-closed 语义）。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def builder_configured() -> bool:
    """构建器是否配置（地址＋token 双配才算；缺任一即未交付）。"""
    return bool((os.environ.get("REPO2DOCKER_BUILDER_URL") or "").strip()
                and (os.environ.get("REPO2DOCKER_BUILDER_TOKEN") or "").strip())


def build_appendix() -> str:
    """执行运行时 appendix（Dockerfile 片段；随构建请求下发）。"""
    extra = (os.environ.get("REPO2DOCKER_APPENDIX_EXTRA") or "").strip()
    lines = list(SWEREX_APPENDIX_LINES)
    if extra:
        lines.extend(line for line in extra.splitlines() if line.strip())
    return "\n".join(lines) + "\n"


class Repo2DockerBuilder:
    """外部构建器 HTTP 客户端（无状态；作业状态由调用方持久化）。

    构建器契约（未来 daemon 实现时遵守，版本 v1）：
    - POST /builds {repo_url, revision, appendix} → 200 {build_id}
    - GET /builds/{id} → 200 {build_id, status, build_image, exec_image,
      log_tail, detail}；status ∈ queued/running/succeeded/failed/cancelled
    - 未配置/不可达 → BuilderError（调用方映射 501/502，不伪装成功）。
    """

    def __init__(self, base_url: str = "", token: str = "",
                 timeout_s: float = 30.0, transport: Any = None) -> None:
        self._base_url = (base_url or os.environ.get(
            "REPO2DOCKER_BUILDER_URL") or "").rstrip("/")
        self._token = token or os.environ.get("REPO2DOCKER_BUILDER_TOKEN") or ""
        self._timeout_s = max(1.0, float(timeout_s or 30.0))
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _require_configured(self) -> str:
        if not self._base_url or not self._token:
            raise BuilderError(
                "BUILDER_NOT_CONFIGURED",
                "repo2docker 构建器未配置（REPO2DOCKER_BUILDER_URL/TOKEN 为空）；"
                "构建路线 fail-closed，不等同基础镜像安装。",
            )
        return self._base_url

    async def submit(self, *, repo_url: str, revision: str) -> str:
        """提交构建 → build_id（网络/认证失败即抛，不重试伪装）。"""
        import httpx

        base = self._require_configured()
        payload = {"repo_url": (repo_url or "").strip(),
                   "revision": (revision or "").strip(),
                   "appendix": build_appendix()}
        if not payload["repo_url"] or not payload["revision"]:
            raise BuilderError("BUILD_REQUEST_INVALID", "仓库地址/修订不能为空。")
        try:
            async with httpx.AsyncClient(transport=self._transport,
                                         timeout=self._timeout_s) as client:
                response = await client.post(f"{base}/builds", json=payload,
                                             headers=self._headers())
        except Exception as error:  # noqa: BLE001
            raise BuilderError(
                "BUILDER_UNAVAILABLE",
                f"构建器不可达（{type(error).__name__}）。") from error
        if response.status_code >= 400:
            raise BuilderError(
                "BUILDER_REJECTED",
                f"构建器拒绝请求（HTTP {response.status_code}）。")
        try:
            build_id = str(response.json().get("build_id") or "")
        except ValueError as error:
            raise BuilderError("BUILDER_BAD_RESPONSE", "构建器返回非 JSON。") from error
        if not build_id:
            raise BuilderError("BUILDER_BAD_RESPONSE", "构建器未返回 build_id。")
        return build_id[:128]

    async def query(self, build_id: str) -> dict[str, Any]:
        """查询构建（未知 id 即 unknown，不抛）。"""
        import httpx

        base = self._require_configured()
        build_id = (build_id or "").strip()[:128]
        if not build_id:
            raise BuilderError("BUILD_REQUEST_INVALID", "build_id 不能为空。")
        try:
            async with httpx.AsyncClient(transport=self._transport,
                                         timeout=self._timeout_s) as client:
                response = await client.get(f"{base}/builds/{build_id}",
                                            headers=self._headers())
        except Exception as error:  # noqa: BLE001
            raise BuilderError(
                "BUILDER_UNAVAILABLE",
                f"构建器不可达（{type(error).__name__}）。") from error
        if response.status_code == 404:
            return {"build_id": build_id, "status": "unknown"}
        if response.status_code >= 400:
            raise BuilderError(
                "BUILDER_REJECTED",
                f"构建器拒绝查询（HTTP {response.status_code}）。")
        try:
            data = response.json()
        except ValueError as error:
            raise BuilderError("BUILDER_BAD_RESPONSE", "构建器返回非 JSON。") from error
        if not isinstance(data, dict):
            raise BuilderError("BUILDER_BAD_RESPONSE", "构建器返回非对象。")
        data.setdefault("build_id", build_id)
        return data


def new_build_id() -> str:
    """本地构建作业 id（控制面登记用；与远端 daemon id 解耦存放）。"""
    import uuid

    return f"bld-{uuid.uuid4().hex[:12]}"


def now() -> float:
    return time.time()
