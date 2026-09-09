"""F7 补读：按问题补读后续页、长块后半段、表格和图（块偏移分页）。

- 解析（parsed）、读过（read）、理解（understood）分别表达：
  parsed＝附件解析总字符/总块数（服务端事实）；read＝已组织成证据的块；
  understood＝模型综合结论（本模块不代劳，只给核对口径）。
- 不可得如实 abstract_only/partial：覆盖范围沿 build_evidence 的机械判定；
  附件总量低于阈值即 abstract_only，不直接伪称全文综述。
- 引用 ID 合法不等于支持结论：补读只返回新证据（去重），综合阶段仍须
  核对主张与原文（见 research_loop 交付核对）。
"""

from __future__ import annotations

import logging
from typing import Any

from nexus.paper_evidence import (
    ABSTRACT_ONLY_THRESHOLD_CHARS,
    COVERAGE_ABSTRACT,
    COVERAGE_FULLTEXT,
    build_evidence,
)

logger = logging.getLogger("nexus.research_reading")

READ_MORE_MAX_LIMIT = 12


def describe_reading_state(*, attachment_total_chars: int, blocks_total: int,
                           blocks_read: int) -> dict[str, Any]:
    """阅读状态三分（纯函数，可单测）：解析量 vs 已读块 vs 理解（模型侧）。"""
    try:
        total = max(0, int(attachment_total_chars or 0))
        total_blocks = max(0, int(blocks_total or 0))
        read = max(0, min(int(blocks_read or 0), total_blocks))
    except (TypeError, ValueError):
        total, total_blocks, read = 0, 0, 0
    coverage = (COVERAGE_ABSTRACT if total < ABSTRACT_ONLY_THRESHOLD_CHARS
                else COVERAGE_FULLTEXT)
    return {
        "parsed_chars": total,
        "parsed_blocks": total_blocks,
        "read_blocks": read,
        "unread_blocks": max(0, total_blocks - read),
        "coverage": coverage,
        "note": ("解析完成≠已读（仅摘要级内容，须上传全文补验）"
                 if coverage == COVERAGE_ABSTRACT
                 else "已读块数≠已理解：综合结论须逐条核对主张与原文摘录。"),
    }


async def read_more_blocks(
    *, attachment_id: str, filename: str = "", offset: int = 0,
    limit: int = 6, question: str = "",
    known_evidence_ids: list[str] | None = None,
    attachment_total_chars: int | None = None,
    fetch_blocks: Any = None,
) -> dict[str, Any]:
    """补读后续块（纯编排；fetch_blocks 可注入替身，默认走附件后端）。

    - offset/limit 按块索引（不是字符偏移）；limit 上限 12；
    - 只返回本次新证据（known 去重）；coverage 按附件总量机械判定；
    - 返回 {evidences, next_offset, has_more, reading_state}。
    """
    aid = (attachment_id or "").strip()[:16]
    if not aid:
        raise ValueError("attachment_id 不能为空")
    try:
        offset = max(0, int(offset or 0))
        limit = max(1, min(int(limit or 6), READ_MORE_MAX_LIMIT))
    except (TypeError, ValueError):
        raise ValueError("非法分段参数")
    if fetch_blocks is None:
        from nexus.tools.paper_research import _fetch_blocks as _default_fetch

        async def fetch_blocks(inner_aid: str) -> tuple[list[dict[str, Any]], int, bool]:
            from nexus.config import get_settings

            settings = get_settings()
            url = (settings.backend_internal_url or "").rstrip("/")
            token = settings.backend_internal_token or ""
            if not url or not token:
                return [], 0, False
            data, _ = await _default_fetch(url, token, inner_aid)
            if data is None:
                return [], 0, False
            blocks = [block for block in (data.get("blocks") or [])
                      if isinstance(block, dict)]
            total = sum(len(str(block.get("text") or "")) for block in blocks)
            return blocks, total, bool(data.get("truncated"))
    blocks, total, _ = await fetch_blocks(aid)
    if attachment_total_chars is not None:
        try:
            total = max(0, int(attachment_total_chars))
        except (TypeError, ValueError):
            pass
    known = {str(eid) for eid in (known_evidence_ids or [])}
    evidences: list[dict[str, Any]] = []
    for block in blocks[offset:offset + limit]:
        evidence = build_evidence(
            attachment_id=aid, filename=filename or "用户上传文件",
            block=block, attachment_total_chars=total)
        if evidence is None:
            continue
        if str(evidence.get("evidence_id") or "") in known:
            continue
        evidences.append(evidence)
    next_offset = offset + limit
    return {
        "evidences": evidences,
        "next_offset": next_offset,
        "has_more": next_offset < len(blocks),
        "reading_state": describe_reading_state(
            attachment_total_chars=total, blocks_total=len(blocks),
            blocks_read=min(next_offset, len(blocks))),
    }
