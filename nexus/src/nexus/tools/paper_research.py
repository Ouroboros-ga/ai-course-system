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


def _question_terms(question: str) -> list[str]:
    """研究问题分词（确定性词频排序用）：英文数字下划线 ≥2 字符、CJK ≥2 字。

    无分词器依赖；排序只影响块选择顺序，不改变读取预算与范围。
    """
    import re as _re

    return sorted({_t for _t in _re.findall(
        r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", (question or "").lower())})


def _rank_blocks(
    blocks: list[dict[str, Any]], terms: list[str]
) -> list[dict[str, Any]]:
    """NX-N0/R3：问题相关块优先（稳定排序：分数降序＋原序号升序）。

    无命中时退化为原文顺序（行为不变）；预算/截断语义不受影响。
    """
    scored = []
    for index, block in enumerate(blocks):
        text = ""
        if isinstance(block, dict):
            raw = block.get("text")
            text = str(raw).lower() if isinstance(raw, str) else ""
        score = sum(text.count(term) for term in terms) if terms else 0
        scored.append((index, block, score))
    scored.sort(key=lambda item: (-item[2], item[0]))
    return [block for _, block, _ in scored]


@tool
async def collect_paper_evidence(question: str, attachment_ids: list[str],
                                 task_id: str = "") -> dict[str, Any]:
    """读取用户上传的论文 PDF（≤3 篇）全文块，建立带可核对定位的证据清单。

    参数：
    - question：当前研究问题（参与证据排序：问题相关块优先；不改变读取
      预算与范围，无命中时保持原文顺序）；
    - attachment_ids：要读取的附件 id（仅本次对话已绑定的上传 PDF 可用）。
    - task_id：所属研究任务（可选；在任务预算内计数，证据同步持久化，
      重启可恢复；缺省用请求上下文的当前任务）。

    返回 evidences（每条含 evidence_id/locator/excerpt/coverage，超长块带
    truncated 标记），后续 write_research_report 只能引用这些 evidence_id；
    引用时必须使用原文 locator。只有摘要级内容会标记 abstract_only，
    不会冒充读过全文。
    """
    from nexus.request_scope import current_attachments as scope_ids
    from nexus.request_scope import current_research_task_id

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
    # F7：任务预算预检（失败不收费；成功后扣 evidence_calls）。
    resolved_task = (task_id or "").strip()[:64]
    if not resolved_task:
        try:
            from nexus.request_scope import current_research_task_id as _current_task

            resolved_task = _current_task() or ""
        except Exception:  # noqa: BLE001
            resolved_task = ""
    if resolved_task:
        try:
            from nexus import research_state as research_state_module

            _task = research_state_module.get_task(resolved_task)
            if _task is None or (_task.get("owner") or "") != (current_user_id() or ""):
                return {"status": "rejected", "code": "TASK_NOT_FOUND",
                        "detail": "研究任务不存在或无权使用。", "evidences": []}
            _exhausted = research_state_module.check_budget(_task)
            if _exhausted:
                return {"status": "rejected", "code": "RESEARCH_BUDGET_EXHAUSTED",
                        "detail": f"研究预算已用尽（{_exhausted}）；不再派生新工作。",
                        "evidences": []}
        except Exception as error:  # noqa: BLE001 - 预检失败 fail-closed
            code = getattr(error, "code", "")
            if code in ("TASK_NOT_FOUND",):
                return {"status": "rejected", "code": code, "detail": str(error),
                        "evidences": []}

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
        # NX-N0/R3：问题相关块优先进入预算（确定性排序，无命中保持原文顺序）。
        ranked = _rank_blocks(
            [b for b in blocks if isinstance(b, dict)], _question_terms(q))
        for block in ranked:
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
        # F7：任务预算记账＋证据持久化（重启可恢复；持久化失败不阻断本次返回）。
        if resolved_task:
            try:
                from nexus import research_state as research_state_module

                research_state_module.consume_budget(
                    resolved_task, current_user_id() or "", "evidence_calls")
            except Exception as error:  # noqa: BLE001 - 记账失败只记日志
                logger.warning("research budget consume failed: %s",
                               type(error).__name__)
            try:
                from nexus import paper_evidence as evidence_module

                by_attachment: dict[str, list[dict[str, Any]]] = {}
                for evidence in evidences:
                    by_attachment.setdefault(
                        str(evidence.get("attachment_id") or ""), []).append(evidence)
                for aid, items in by_attachment.items():
                    evidence_module.persist_evidences(
                        user_id=current_user_id() or "",
                        session_id=current_session_id() or "",
                        task_id=resolved_task, attachment_id=aid,
                        source_title=str(items[0].get("source_title") or ""),
                        evidences=items)
            except Exception as error:  # noqa: BLE001 - 持久化失败只记日志
                logger.warning("evidence persist failed: %s", type(error).__name__)
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
    task_id: str = "",
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
    - task_id：所属研究任务（可选；引用解析含持久化回读，成功后登记
      报告产物，交付核对可见）。

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
    # 最小篇幅门禁（NX-Report）：在**写入点**拒绝过短正文，而不是等到交付核对。
    # 理由：delivery_checklist 的 task 记录里只有 report_artifact_id，没有正文长度；
    # 为它加列需要 DB 迁移，而这里能直接拿到 body。语义与既有 rejected 一致
    # （可修复错误 + 明确指引，模型按指引补足后重试）。
    # 阈值 0 表示不校验（可用 NEXUS_REPORT_MIN_CHARS 调整或关闭）。
    _min_chars = max(0, int(getattr(get_settings(), "report_min_chars", 0) or 0))
    if _min_chars and len(body) < _min_chars:
        return {
            "status": "rejected",
            "code": "REPORT_TOO_SHORT",
            "detail": (
                f"报告正文过短（{len(body)} 字符，下限 {_min_chars}）。请按系统提示的"
                " NX-Report 结构补足各节实质论述后重试：研究问题 / 资料覆盖与来源 /"
                " 关键证据 / 方法比较 / 综合结论 / 限制与待补证据。"
                "证据不足以支撑某节时，先考虑用 read_paper_more 补读；"
                "不得用「暂无相关内容」或重复语句凑数。"
            ),
        }
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
            # F7：持久化回读（重启后内存登记丢失时的恢复路径；归属一致才认）。
            from nexus import paper_evidence as evidence_module

            evidence = evidence_module.resolve_persisted(
                eid, user_id=user_id, session_id=session_id)
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
    # NX-N0/R1：正文 [n] 编号必须映射到已解析证据（按 cited 顺序 1..N）。
    # 只验 id 合法不代表引用合法——[999]、错位编号、无正文引用都拒绝。
    import re as _re

    used_numbers = sorted({int(n) for n in _re.findall(r"\[(\d+)\]", body)})
    out_of_range = [n for n in used_numbers if n < 1 or n > len(resolved)]
    if out_of_range:
        return {
            "status": "rejected",
            "code": "CITATION_NUMBER_INVALID",
            "detail": (
                f"正文引用编号越界：{out_of_range}（本次有效范围 1–{len(resolved)}，"
                "按 cited_evidence_ids 顺序编号）。请修正后重试（最多一次），"
                "仍失败则如实输出证据缺口。"
            ),
        }
    if not used_numbers:
        return {
            "status": "rejected",
            "code": "CITATION_BODY_MISSING",
            "detail": "正文没有任何 [n] 引用标记，不能只交引用附录；请在论述处"
                      "标注引用编号后重试。",
        }
    # NX-N0/R2：写入前重验来源附件当前可用性。登记时校验过 owner/session，
    # 但附件可能随后被删除/过期/改绑——旧 evidence_id 不得继续产生新报告
    # （已生成报告按 Artifact 生命周期保留，本条不静默删除）。
    # 后端未配置时无法重验（此时 collect 本就不可用，登记只可能来自测试）。
    backend = _backend_ready()
    if backend is not None:
        url, token = backend
        revoked: list[str] = []
        checked: set[str] = set()
        for _, evidence in resolved:
            aid = str(evidence.get("attachment_id") or "")
            if not aid or aid in checked:
                continue
            checked.add(aid)
            _, fetch_error = await _fetch_blocks(url, token, aid)
            if fetch_error is not None:
                revoked.append(f"{aid}({fetch_error})")
        if revoked:
            return {
                "status": "rejected",
                "code": "EVIDENCE_SOURCE_REVOKED",
                "detail": (
                    "以下证据来源当前不可用（删除/过期/改绑/越权）："
                    f"{', '.join(revoked)}。请重新读取可用来源后再写报告；"
                    "不得用旧摘录生成新报告。"
                ),
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
    # F7：报告产物回链到研究任务（交付核对可见；失败只记日志）。
    resolved_task = (task_id or "").strip()[:64]
    if not resolved_task:
        try:
            from nexus.request_scope import current_research_task_id as _current_task

            resolved_task = _current_task() or ""
        except Exception:  # noqa: BLE001
            resolved_task = ""
    if resolved_task:
        try:
            from nexus import research_state as research_state_module

            research_state_module.set_report(
                resolved_task, user_id,
                str((written.get("artifact") or {}).get("artifact_id") or ""))
        except Exception as error:  # noqa: BLE001
            logger.warning("research report link failed: %s", type(error).__name__)
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


@tool
async def read_paper_more(question: str, attachment_id: str, offset: int = 0,
                          limit: int = 6, task_id: str = "") -> dict[str, Any]:
    """按问题补读论文后续块（表格/图/长块后半段；块偏移分页）。

    参数：
    - question：当前研究问题（仅参与排序说明，不改变预算与范围）；
    - attachment_id：已绑定本次对话的附件 id；
    - offset/limit：块索引分页（limit≤12；未见≠不存在，has_more 为真时
      继续用 next_offset 续读）；
    - task_id：所属研究任务（可选；在任务预算内计数，新证据同步持久化）。

    只返回本次新证据（已知 id 去重）；覆盖范围沿机械判定，
    abstract_only 不得冒充全文综述。
    """
    from nexus.request_scope import current_attachments as scope_ids

    aid = (attachment_id or "").strip()[:16]
    if not aid:
        return {"status": "rejected", "code": "ATTACHMENT_ID_INVALID",
                "detail": "未提供附件 id。", "evidences": []}
    allowed = set(scope_ids())
    if allowed and aid not in allowed:
        return {"status": "rejected", "code": "ATTACHMENT_NOT_IN_SCOPE",
                "detail": f"附件未绑定到本次对话：{aid}。",
                "evidences": []}
    try:
        offset = max(0, int(offset or 0))
        limit = max(1, min(int(limit or 6), 12))
    except (TypeError, ValueError):
        return {"status": "rejected", "code": "READ_RANGE_INVALID",
                "detail": "非法分段参数。", "evidences": []}
    resolved_task = (task_id or "").strip()[:64]
    if not resolved_task:
        try:
            from nexus.request_scope import current_research_task_id as _current_task

            resolved_task = _current_task() or ""
        except Exception:  # noqa: BLE001
            resolved_task = ""
    if resolved_task:
        try:
            from nexus import research_state as research_state_module

            _task = research_state_module.get_task(resolved_task)
            if _task is None or (_task.get("owner") or "") != (current_user_id() or ""):
                return {"status": "rejected", "code": "TASK_NOT_FOUND",
                        "detail": "研究任务不存在或无权使用。", "evidences": []}
            _exhausted = research_state_module.check_budget(_task)
            if _exhausted:
                return {"status": "rejected", "code": "RESEARCH_BUDGET_EXHAUSTED",
                        "detail": f"研究预算已用尽（{_exhausted}）。",
                        "evidences": []}
        except Exception as error:  # noqa: BLE001
            code = getattr(error, "code", "")
            if code in ("TASK_NOT_FOUND",):
                return {"status": "rejected", "code": code, "detail": str(error),
                        "evidences": []}
    ready = _backend_ready()
    if ready is None:
        return {"status": "unavailable", "code": "EVIDENCE_UNAVAILABLE",
                "detail": "附件服务未配置；不得编造论文内容。", "evidences": []}
    url, token = ready

    async def _fetch(inner_aid: str) -> tuple[list[dict[str, Any]], int, bool]:
        data, error_code = await _fetch_blocks(url, token, inner_aid)
        if data is None:
            raise LookupError(error_code or "ATTACHMENT_UNAVAILABLE")
        blocks = [block for block in (data.get("blocks") or [])
                  if isinstance(block, dict)]
        total = sum(len(str(block.get("text") or "")) for block in blocks)
        return blocks, total, bool(data.get("truncated"))

    try:
        from nexus import research_reading as reading_module

        try:
            known: list[str] = []
            if resolved_task:
                try:
                    from nexus import research_state as research_state_module

                    _task = research_state_module.get_task(resolved_task)
                    known = list((_task or {}).get("evidence_ids") or [])
                except Exception:  # noqa: BLE001
                    known = []
            result = await reading_module.read_more_blocks(
                attachment_id=aid, filename="", offset=offset, limit=limit,
                question=question or "", known_evidence_ids=known,
                fetch_blocks=_fetch)
        except LookupError as error:
            return {"status": "failed", "code": "ATTACHMENT_UNAVAILABLE",
                    "detail": f"附件读取失败（{error}）。", "evidences": []}
        except ValueError as error:
            return {"status": "rejected", "code": "READ_RANGE_INVALID",
                    "detail": str(error), "evidences": []}
    except Exception as error:  # noqa: BLE001
        logger.warning("read more failed: %s", type(error).__name__)
        return {"status": "failed", "code": "EVIDENCE_UNAVAILABLE",
                "detail": "补读失败；不得编造论文内容。", "evidences": []}
    evidences = result.get("evidences") or []
    if evidences:
        get_registry().register(current_user_id() or "", current_session_id() or "",
                                evidences)
        if resolved_task:
            try:
                from nexus import research_state as research_state_module

                research_state_module.consume_budget(
                    resolved_task, current_user_id() or "", "evidence_calls")
            except Exception as error:  # noqa: BLE001
                logger.warning("research budget consume failed: %s",
                               type(error).__name__)
            try:
                from nexus import paper_evidence as evidence_module

                evidence_module.persist_evidences(
                    user_id=current_user_id() or "",
                    session_id=current_session_id() or "",
                    task_id=resolved_task, attachment_id=aid,
                    source_title=str(evidences[0].get("source_title") or ""),
                    evidences=evidences)
            except Exception as error:  # noqa: BLE001
                logger.warning("evidence persist failed: %s", type(error).__name__)
    return {"status": "success", "question": (question or "").strip()[:300],
            "attachment_id": aid, "evidences": evidences,
            "next_offset": result.get("next_offset", offset + limit),
            "has_more": bool(result.get("has_more", False)),
            "reading_state": result.get("reading_state") or {},
            "is_supplementary": True}
