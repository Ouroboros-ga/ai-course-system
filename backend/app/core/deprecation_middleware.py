"""废弃接口标注中间件（CodeNexus 转型 S1 双轨期）。

只在响应上追加标注头，**不改变**状态码、响应体与任何业务行为——S1 双轨期的
硬要求是旧 ``/research-agent`` 链路行为零变更，随时可回退到旧链路做演示
（docs/phase1/CodeNexus转型落地计划.md §二）。真正的下线在 S2（410 Gone）
与 S3（删除路由）完成。

用中间件而不是路由依赖，是为了让 ``HTTPException``、校验失败（422）等由框架
直接生成的响应也带上标注头；路由依赖里改 ``Response.headers`` 只对正常返回生效。

``Sunset``（RFC 8594）默认不发送：本次转型按里程碑推进而非日历日期，编造一个
到期日会误导调用方。日期一旦确定，配置 ``DEPRECATION_SUNSET_DATE`` 即可生效。
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from urllib.parse import quote

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# 被标注为废弃的路径前缀 -> 后继接口。
# ``/api/v1/research-agent``：Legacy ResearchAgent Harness v1（大脑由 Nexus 替代）
# ``/api/v1/web-research``：G7 WebResearchTool（能力并入 Nexus web_search 工具）
DEPRECATED_PATH_PREFIXES: dict[str, str] = {
    "/api/v1/research-agent": "/api/v1/nexus/chat",
    "/api/v1/web-research": "/api/v1/nexus/chat",
}

# 转型计划文档，供调用方定位迁移说明。
# HTTP 头值必须 latin-1 可编码（starlette 会按 latin-1 编码），而计划文档的真实
# 文件名含中文，因此这里存 percent-encoded 形式：既保留可还原的真实路径，
# 又不会在写头时抛 UnicodeEncodeError。
DEPRECATION_PLAN_DOC_PATH = "docs/phase1/CodeNexus转型落地计划.md"
DEPRECATION_PLAN_DOC = quote(DEPRECATION_PLAN_DOC_PATH)
DEPRECATION_PHASE = "S1-dual-track"


class DeprecationHeaderMiddleware(BaseHTTPMiddleware):
    """给废弃接口的响应追加 ``Deprecation`` / ``Link`` 等标注头。"""

    def __init__(
        self,
        app: ASGIApp,
        prefixes: dict[str, str] | None = None,
        sunset_date: str = "",
    ) -> None:
        super().__init__(app)
        self.prefixes = dict(prefixes if prefixes is not None else DEPRECATED_PATH_PREFIXES)
        self.sunset_date = sunset_date

    def _successor_for(self, path: str) -> str | None:
        for prefix, successor in self.prefixes.items():
            if path.startswith(prefix):
                return successor
        return None

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        successor = self._successor_for(request.url.path)
        if successor is None:
            return response

        # RFC 8594 §2：布尔形式的 Deprecation 头表示"已废弃但仍可用"。
        response.headers["Deprecation"] = "true"
        # RFC 5829：指向后继接口，便于客户端自动发现迁移目标。
        response.headers["Link"] = f'<{successor}>; rel="successor-version"'
        response.headers["X-Deprecation-Phase"] = DEPRECATION_PHASE
        response.headers["X-Deprecation-Plan"] = DEPRECATION_PLAN_DOC
        if self.sunset_date:
            response.headers["Sunset"] = self.sunset_date
        return response
