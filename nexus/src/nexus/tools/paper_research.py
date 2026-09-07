"""NX-R1a Research-only 证据薄链：上传论文全文 → 证据 → 带引用报告。

安全与诚实边界（任务书 T3）：
- 只消费 1–3 篇已上传、ready、属于当前用户且绑定当前会话的 PDF——owner/
  会话绑定由 Backend 内部附件端点双重校验，身份只来自请求作用域
  （ContextVar），模型传参不能越权，也不直读磁盘。
- 证据内容来自实际返回块；source_title 是用户上传文件标签；locator 缺失
  如实标注，不编造页码。
- 模型只能引用服务端登记的 evidence_id；write_research_report 服务端解析
  id 并渲染引用，不接受模型编造的页码/引文。引用校验失败返回可修复错误
  （模型最多修正一次），仍失败则如实输出证据缺口，不写带伪引用的成功报告。
- 综合分析使用现有 Agent 模型循环；本批不新增检索框架/URL 下载器/隐藏
  收费服务；搜索候选（search_arxiv_papers/web_search 元数据）与已读全文
  证据严格区分，候选无全文时提示用户上传。
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from langchain_core.tools import tool

from nexus.config import get_settings
from nexus.paper_evidence import (
    EVIDENCE_EXCERPT_MAX,
    EVIDENCE_TOTAL_CHARS_MAX,
    MAX_ATTACHMENTS_PER_CALL,
    MAX_EVIDENCES_PER_CALL,
    build_evidence,
    citation_line,
    get_registry,
)
from nexus.request_scope import current_attachments, current_session_id, current_user_id

logger = logging.getLogger(__name__)

_TIME_OUT_S = 30.0
_TITLE_MAX = 120
_BODY_MAX_CHARS = 400_000


def _backend_ready() -> tuple[str, str] | None:
    settings = get_settings()
    url = (settings.backend_internal_url or "").rstrip("/")
    token = settings.backend_internal_token or ""
    if not url or not token:
        return None
    return url, token


async def _fetch_blocks(url: str, token: str, aid: str) -> tuple[dict[str, Any] | None, str | None]:
    """拉取附件解析块；返回 (data, error_code)。语义错误码与 read_attachment 对齐。"""
    user_id = current_user_id()
    session_id = current_session_id()
    headers: dict[str, str] = {
        "Authorization": f"Bearer {token}",
        **({"X-Nexus-User-Id": user_id} if user_id else {}),
        **({"X-Nexus-Session-Id": session_id} if session_id else {}),
    }
    try:
        async with httpx.AsyncClient(timeout=_TIME_OUT_S) as client:
            response = await client.get(
                f"{url}/api/v1/nexus-internal/attachments/{aid}/content", headers=headers
            )
    except Exception as error:  # noqa: BLE001
        logger.warning("paper evidence fetch unreachable: %s", type(error).__name__)
        return None, "ATTACHMENT_UNAVAILABLE"
    code_by_status = {403: "ATTACHMENT_SESSION_MISMATCH", 404: "ATTACHMENT_NOT_FOUND"}
    if response.status_code in code_by_status:
        return None, code_by_status[response.status_code]
    if response.status_code != 200:
        return None, "ATTACHMENT_UNAVAILABLE"
    try:
        data = response.json().get("data") or {}
    except ValueError:
        return None, "ATTACHMENT_UNAVAILABLE"
    return data, None


@tool
async def collect_paper_evidence(question: str, attachment_ids: list[str]) -> dict[str, Any]:
    """读取用户上传的论文 PDF（≤3 篇）全文块，建立带可核对定位的证据清单。

    参数：
    - question：当前研究问题（用于组织证据，不改变读取范围）；
    - attachment_ids：要读取的附件 id（仅本次对话已绑定的上传 PDF 可用）。

    返回 evidences（每条含 evidence_id/locator/excerpt/coverage），后续
    write_research_report 只能引用这些 evidence_id；引用时必须使用原文
    locator。只有摘要级内容会标记 abstract_only，不会冒充读过全文。
    """
    from nexus.request_scope import current_attachments as scope_ids

    q = (question or "").strip()[:300]
    if not q:
        return {"status": "rejected", "code": "QUESTION_REQUIRED",
                "detail": "缺少研究问题，无法组织证据。", "evidences": []}
    allowed = set(scope_ids())
    requested: list[str] = []
    for raw in attachment_ids or []:
        aid = (raw or "").strip()[:16]
        if aid and aid not in requested:
            requested.append(aid)
    if not requested:
        return {"status": "rejected", "code": "ATTACHMENT_ID_INVALID",
                "detail": "未提供附件 id。", "evidences": []}
    if len(requested) > MAX_ATTACHMENTS_PER_CALL:
        requested = requested[:MAX_ATTACHMENTS_PER_CALL]
    out_of_scope = [aid for aid in requested if allowed and aid not in allowed]
    if out_of_scope:
        return {"status": "rejected", "code": "ATTACHMENT_NOT_IN_SCOPE",
                "detail": f"附件未绑定到本次对话：{','.join(out_of_scope)}。",
                "evidences": []}
    ready = _backend_ready()
    if ready is None:
        return {"status": "unavailable", "code": "EVIDENCE_UNAVAILABLE",
                "detail": "附件服务未配置；不得编造论文内容。", "evidences": []}
    url, token = ready

    evidences: list[dict[str, Any]] = []
    attachment_errors: list[dict[str, str]] = []
    coverage_by_attachment: dict[str, str] = {}
    total_chars = 0
    budget_hit = False
    truncated_any = False

    for aid in requested:
        if budget_hit:
            attachment_errors.append({"attachment_id": aid, "code": "EVIDENCE_BUDGET_REACHED",
                                      "detail": "证据条数/总字符预算已用满，本篇未读取。"})
            continue
        data, error_code = await _fetch_blocks(url, token, aid)
        if data is None:
            attachment_errors.append({"attachment_id": aid, "code": error_code or "ATTACHMENT_UNAVAILABLE",
                                      "detail": "附件读取失败或不可用。"})
            continue
        kind = str(data.get("kind") or "").lower()
        if kind and kind not in ("pdf",):
            # 本批研究薄链先验收 PDF；其他格式走通用 read_attachment 能力。
            attachment_errors.append({"attachment_id": aid, "code": "KIND_NOT_PDF",
                                      "detail": f"本研究证据链当前只支持 PDF，收到 {kind or 'unknown'}。"})
            continue
        blocks = data.get("blocks") or []
        att_total = sum(len(str(b.get("text") or "")) for b in blocks if isinstance(b, dict))
        coverage = "fulltext_excerpt"
        if att_total < 500:
            coverage = "abstract_only"
        coverage_by_attachment[aid] = coverage
        if data.get("truncated"):
            truncated_any = True
        added_for_this_attachment = 0
        for block in blocks:
            if len(evidences) >= MAX_EVIDENCES_PER_CALL or total_chars >= EVIDENCE_TOTAL_CHARS_MAX:
                budget_hit = True
                break
            evidence = build_evidence(
                attachment_id=aid, filename=str(data.get("filename") or ""),
                block=block, attachment_total_chars=att_total,
            )
            if evidence is None:
                continue
            if total_chars + len(evidence["excerpt"]) > EVIDENCE_TOTAL_CHARS_MAX:
                budget_hit = True
                truncated_any = True
                break
            evidences.append(evidence)
            total_chars += len(evidence["excerpt"])
            added_for_this_attachment += 1
        if added_for_this_attachment == 0 and not budget_hit:
            attachment_errors.append({"attachment_id": aid, "code": "NO_TEXT_BLOCKS",
                                      "detail": "解析产物无文本块（扫描件/空文档？）。"})

    if evidences:
        get_registry().register(current_user_id() or "", current_session_id() or "", evidences)
        return {
            "status": "success",
            "question": q,
            "evidences": evidences,
            "coverage_by_attachment": coverage_by_attachment,
            "attachment_errors": attachment_errors,
            "truncated": truncated_any or budget_hit,
            "detail": (
                f"已建立 {len(evidences)} 条证据（excerpt≤{EVIDENCE_EXCERPT_MAX} 字符，"
                f"总预算 {EVIDENCE_TOTAL_CHARS_MAX}）。只有摘要级内容标记 abstract_only；"
                "搜索候选元数据不属于本清单。"
            ),
            "is_supplementary": True,
        }
    first_error = attachment_errors[0] if attachment_errors else None
    return {
        "status": "failed",
        "code": (first_error or {}).get("code", "EVIDENCE_UNAVAILABLE"),
        "detail": (first_error or {}).get("detail", "未能建立任何证据；不得编造论文内容。"),
        "evidences": [],
        "attachment_errors": attachment_errors,
    }


@tool
async def write_research_report(
    title: str,
    question: str,
    body_markdown: str,
    cited_evidence_ids: list[str],
) -> dict[str, Any]:
    """把研究综合写成带可核对引用的 Markdown 报告 Artifact（真实落盘）。

    参数：
    - title：报告标题（≤120 字符，用作下载文件名）；
    - question：研究问题（写进报告头部）；
    - body_markdown：正文全文（研究问题/资料覆盖/证据/方法比较/综合结论/
      限制与待补证据各节；引用处使用 [n] 编号，引用列表由服务端按
      cited_evidence_ids 渲染）；
    - cited_evidence_ids：正文实际引用的 evidence_id（只能来自
      collect_paper_evidence 返回；服务端渲染来源与 locator，不接受编造）。

    引用校验失败时返回可修复错误（invalid_ids）——最多修正一次，仍失败
    应如实输出证据缺口，不得输出带伪引用的报告。
    """
    clean_title = (title or "").strip()[:_TITLE_MAX]
    body = (body_markdown or "").strip()
    if not clean_title or not body:
        return {"status": "rejected", "code": "REPORT_CONTENT_REQUIRED",
                "detail": "标题与正文不能为空。"}
    if len(body) > _BODY_MAX_CHARS:
        return {"status": "rejected", "code": "REPORT_TOO_LARGE",
                "detail": f"正文超长（>{_BODY_MAX_CHARS} 字符）。"}
    user_id = current_user_id() or ""
    session_id = current_session_id() or ""

    registry = get_registry()
    resolved: list[tuple[str, dict[str, Any]]] = []
    invalid: list[str] = []
    for raw in cited_evidence_ids or []:
        eid = (raw or "").strip()
        if not eid or any(eid == e for e, _ in resolved):
            continue
        evidence = registry.resolve(eid, user_id=user_id, session_id=session_id)
        if evidence is None:
            invalid.append(eid[:32])
        else:
            resolved.append((eid, evidence))
    if invalid:
        return {
            "status": "rejected",
            "code": "EVIDENCE_ID_INVALID",
            "invalid_ids": invalid,
            "detail": (
                "以下引用无法解析（不存在/非本会话/他人证据）："
                f"{', '.join(invalid[:10])}。只能引用 collect_paper_evidence "
                "返回的 evidence_id；请修正后重试（最多一次），仍失败则如实"
                "输出证据缺口，不得编造页码或引文。"
            ),
        }
    if not resolved:
        return {
            "status": "rejected",
            "code": "CITATIONS_REQUIRED",
            "detail": "研究报告必须至少引用一条已建立证据；无证据时不得写报告，"
                      "应提示用户上传论文全文。",
        }

    lines = [f"# {clean_title}", "", f"**研究问题**：{question.strip()[:300]}", "", body, ""]
    lines.append("## 引用")
    lines.append("")
    for index, (_eid, evidence) in enumerate(resolved, start=1):
        lines.append(citation_line(index, evidence))
    abstract_only = [e for _, e in resolved if e.get("coverage") == "abstract_only"]
    if abstract_only:
        lines.append("")
        lines.append(
            f"> 覆盖范围说明：{len(abstract_only)} 条证据仅含摘要级内容"
            "（abstract_only），对应结论需用户上传全文补验。"
        )
    lines.append("")
    lines.append("> 本报告证据来自用户上传文件（补充参考），不写入课程知识域；"
                 "引用定位存在不代表论点正确，推断与限制以正文为准。")

    from nexus.artifact_client import write_artifact_via_backend

    written = await write_artifact_via_backend(
        artifact_type="markdown",
        title=clean_title,
        content="\n".join(lines),
        user_id=user_id,
    )
    if written.get("status") != "success":
        return {
            "status": "unavailable",
            "code": "ARTIFACT_UNAVAILABLE",
            "detail": str(written.get("detail") or "报告写入失败；未生成任何文件。")[:200],
        }
    return {
        "status": "success",
        "detail": "报告已真实写入存储，引用由服务端按证据登记渲染，可在产物面板下载。",
        "artifact": written.get("artifact"),
        "citations": [
            {
                "evidence_id": eid,
                "source_title": evidence.get("source_title"),
                "locator": evidence.get("locator"),
                "coverage": evidence.get("coverage"),
            }
            for eid, evidence in resolved
        ],
        "is_supplementary": True,
    }
