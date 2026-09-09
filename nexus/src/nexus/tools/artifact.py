"""M3 Artifact 工具：把真实文件写入对象存储（经 Backend 内部端点）。

设计文档 Phase 4 原则：不要模型输出"以下是 Word 文档内容"，要真实文件。
- 工具只接受 markdown / latex 文本对象（P0）；成功后返回 artifact_id 与
  下载路径（前端经 Backend JWT 路由下载）；
- 未配置内部端点 / 失败时 fail-closed 返回 ARTIFACT_UNAVAILABLE，
  绝不假造"文件已生成"（AGENTS.md §4.3 诚实性）。
- F6 create_document_output：同一冻结快照的多格式正式输出（Ask 可用，
  纯渲染不属于实验执行授权）；旧 write_artifact 保持兼容。
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from nexus.artifact_client import write_artifact_via_backend
from nexus.request_scope import current_session_id, current_user_id


@tool
async def write_artifact(artifact_type: str, title: str, content: str) -> dict[str, Any]:
    """把整理成果写成真实文件（Artifact），供用户下载。

    参数：
    - artifact_type：仅支持 "markdown"（研究报告、笔记、总结）或
      "latex"（论文/公式类内容）；
    - title：产物标题（将用作下载文件名，<=120 字符）；
    - content：完整正文（纯文本，<=512KB）。

    成功返回 artifact_id 与下载路径；失败如实返回错误（不得声称文件已生成）。
    输出长报告时优先调用本工具落成文件，再在对话中给出摘要。
    """
    result = await write_artifact_via_backend(
        artifact_type=artifact_type,
        title=title,
        content=content,
        user_id=current_user_id(),
    )
    if result.get("status") == "success":
        result["detail"] = "文件已真实写入存储，用户可在产物面板下载。"
    return result


@tool
async def create_document_output(
    source: str,
    title: str = "",
    template: str = "tech_doc",
    formats: str = "markdown,word,latex",
    idempotency_key: str = "",
) -> dict[str, Any]:
    """由一份冻结内容生成正式文档（Markdown/Word/LaTeX/PDF，可多选）。

    参数：
    - source：成果引用，`run:<run_id>`（实验报告，需本人终态 run）、
      `artifact:<artifact_id>`（已有文本产物，需本人可读）或直接 Markdown
      正文（无外部来源）；
    - title：文档标题（<=120 字符；run 来源缺省用报告标题）；
    - template：`tech_doc`（技术说明）/`research_review`（研究综述）/
      `experiment_report`（实验报告）；
    - formats：逗号分隔，如 `markdown,word,latex,pdf`（pdf 无工具链时如实
      缺席，其余格式保留，即 partial）；
    - idempotency_key：幂等键（同键同内容去重，同键不同内容报冲突）。

    纯渲染，不执行实验，Ask 下可用。成功返回作业视图（含每格式状态、
    引擎与产物 id）；失败如实返回错误（不得声称文件已生成）。
    """
    from nexus import document_jobs as jobs_module
    from nexus import document_output as output_module

    user_id = current_user_id() or ""
    session_id = current_session_id() or ""
    if not user_id:
        return {"status": "error", "code": "SCOPE_MISSING",
                "detail": "缺少用户上下文，无法创建文档作业。"}
    wanted = [part.strip().lower() for part in (formats or "").split(",")
              if part.strip()]
    if not wanted:
        return {"status": "error", "code": "FORMAT_EMPTY",
                "detail": "未指定任何格式。"}
    source_text = (source or "").strip()
    if not source_text:
        return {"status": "error", "code": "SOURCE_EMPTY",
                "detail": "成果引用为空。"}
    markdown = ""
    resolved_title = (title or "").strip()
    source_ref: dict[str, Any] = {}
    try:
        if source_text.startswith("run:"):
            from nexus import experiment_report as report_module
            from nexus import experiment_runs as runs_module

            run_id = source_text[4:].strip()[:64]
            run = runs_module.get_run(run_id)
            if run is None or (user_id or "") != run.get("owner", ""):
                return {"status": "error", "code": "SOURCE_NOT_FOUND",
                        "detail": "实验运行不存在或无权读取。"}
            if run.get("status") not in ("succeeded", "failed"):
                return {"status": "error", "code": "SOURCE_NOT_READY",
                        "detail": f"运行尚未终态（现态 {run.get('status')}），"
                                  "无可冻结的成果。"}
            backend = None
            try:
                from nexus.experiment_agent import _backend_from_settings

                backend = _backend_from_settings(run_id)
            except Exception:  # noqa: BLE001 - 只读 lifecycle，失败即空
                backend = None
            _report, report_md, recipe_md = await report_module.build_stored_report(
                run_id=run_id, user_id=user_id, backend=backend)
            markdown = (f"{report_md.rstrip()}\n\n---\n\n"
                        f"# 附录：实验配方\n\n{recipe_md.strip()}\n")
            resolved_title = resolved_title or f"自主实验报告 · {run_id[:12]}"
            source_ref = {"kind": "run_report", "run_id": run_id}
        elif source_text.startswith("artifact:"):
            from nexus import artifact_client

            artifact_id = source_text[9:].strip()[:64]
            read = await artifact_client.read_artifact_via_backend(
                artifact_id=artifact_id, user_id=user_id)
            if read.get("status") != "success":
                # 撤销/删除的材料读不到→拒绝生成新版本（旧产物保留）。
                return {"status": "error", "code": str(read.get("code") or "SOURCE_NOT_FOUND"),
                        "detail": str(read.get("detail") or "产物不可读。")}
            if read.get("truncated"):
                return {"status": "error", "code": "SOURCE_TRUNCATED",
                        "detail": "产物被截断，不得当完整来源。"}
            markdown = str(read.get("content") or "")
            resolved_title = resolved_title or str(
                (read.get("artifact") or {}).get("title") or "文档")
            source_ref = {"kind": "artifact", "artifact_id": artifact_id}
        else:
            if len(source_text.encode("utf-8")) > 512 * 1024:
                return {"status": "error", "code": "DOCUMENT_TOO_LARGE",
                        "detail": "正文超 512KB 上限。"}
            markdown = source_text
            resolved_title = resolved_title or "文档"
            source_ref = {"kind": "markdown"}
    except Exception as error:  # noqa: BLE001 - 来源解析失败 fail-closed
        code = getattr(error, "code", type(error).__name__)
        return {"status": "error", "code": code, "detail": str(error)[:300]}
    try:
        frozen = output_module.freeze_document(
            markdown=markdown, title=resolved_title, template=template,
            source=source_ref)
    except output_module.DocumentRenderError as error:
        return {"status": "error", "code": error.code, "detail": str(error)}
    try:
        created = await jobs_module.create_and_render(
            owner=user_id, session_id=session_id, frozen=frozen,
            formats=wanted, template=template,
            idempotency_key=(idempotency_key or "").strip(),
            source={**source_ref, "run_id": source_ref.get("run_id", "")})
    except jobs_module.DocumentError as error:
        return {"status": "error", "code": error.code, "detail": str(error)}
    job = created["job"]
    return {"status": "success", "deduped": bool(created.get("deduped", False)),
            "job": jobs_module.public_job_view(job)}
