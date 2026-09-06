"""旧科研接口退役中间件（CodeNexus 转型 S2 切换期）。

S1 双轨期本中间件只在响应上追加标注头；**S2 起对旧前缀短路返回
``410 Gone`` + 迁移说明 JSON**，请求不再触达路由、service 与数据层。
Nexus（``/api/v1/nexus/*``）是唯一后继入口。

- 覆盖前缀：``/api/v1/research-agent``（Legacy ResearchAgent Harness v1）、
  ``/api/v1/web-research``（G7 WebResearchTool，能力由 Nexus web_search /
  search_arxiv_papers 承接）。
- 走中间件而不是路由依赖：所有方法、未知子路径、框架生成的响应统一 410；
  路由注册保留至 S3 删除，revert 本提交即恢复 S1 双轨行为。
- 响应头不再携带 ``Deprecation: true``——RFC 8594 的 Deprecation 语义是
  "仍可用但已废弃"，而 410 表示资源已不存在；改以 ``Link: successor-version``
  （RFC 5829）指向后继接口。

``Sunset``（RFC 8594）默认不发送：本次转型按里程碑推进而非日历日期，编造一个
到期日会误导调用方。日期一旦确定，配置 ``DEPRECATION_SUNSET_DATE`` 即可生效。
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from urllib.parse import quote

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# 退役路径前缀 -> 后继接口。
GONE_PATH_PREFIXES: dict[str, str] = {
    "/api/v1/research-agent": "/api/v1/nexus/chat",
    "/api/v1/web-research": "/api/v1/nexus/chat",
}

GONE_BODY = {"error": "RESEARCH_API_RETIRED", "migration": "Use /api/v1/nexus/* instead"}

# 转型计划文档，供调用方定位迁移说明。
# HTTP 头值必须 latin-1 可编码（starlette 会按 latin-1 编码），而计划文档的真实
# 文件名含中文，因此这里存 percent-encoded 形式：既保留可还原的真实路径，
# 又不会在写头时抛 UnicodeEncodeError。
DEPRECATION_PLAN_DOC_PATH = "docs/phase1/CodeNexus转型落地计划.md"
DEPRECATION_PLAN_DOC = quote(DEPRECATION_PLAN_DOC_PATH)
DEPRECATION_PHASE = "S2-research-retired"


class DeprecationHeaderMiddleware(BaseHTTPMiddleware):
    """旧科研接口 410 短路（类名保留 S1 命名，减少装配处 diff）。"""

    def __init__(
        self,
        app: ASGIApp,
        prefixes: dict[str, str] | None = None,
        sunset_date: str = "",
    ) -> None:
        super().__init__(app)
        self.prefixes = dict(prefixes if prefixes is not None else GONE_PATH_PREFIXES)
        self.sunset_date = sunset_date

    def _successor_for(self, path: str) -> str | None:
        for prefix, successor in self.prefixes.items():
            if path.startswith(prefix):
                return successor
        return None

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        successor = self._successor_for(request.url.path)
        if successor is None:
            return await call_next(request)

        headers = {
            "Link": f'<{successor}>; rel="successor-version"',
            "X-Deprecation-Phase": DEPRECATION_PHASE,
            "X-Deprecation-Plan": DEPRECATION_PLAN_DOC,
            "Cache-Control": "no-store",
        }
        if self.sunset_date:
            headers["Sunset"] = self.sunset_date
        return JSONResponse(status_code=410, content=GONE_BODY, headers=headers)
