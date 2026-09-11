"""F6 文档作业（DocumentJob）：一份冻结内容，多格式独立状态。

- 作业＝一次冻结快照＋模板＋格式集合；三种格式只读同一快照，模型不
  分别重写三遍；转换不改写事实。
- 状态：queued/rendering/validating/succeeded/partial/failed/cancelled；
  每格式独立 {status/engine/artifact_id/detail/checks}；一个失败返回
  partial 并保留成功格式；重试只处理失败格式。
- 幂等：(owner, idempotency_key) 唯一；同键同内容 hash → 返回原作业
  deduped；同键不同内容 → DOCUMENT_CONFLICT（不覆盖、不重渲）。
- 渲染中断可凭作业身份重试（retry 只跑失败格式）；取消仅对非终态有效。
- 存储：PG ``nexus_checkpoints.nexus_document_jobs``＋内存降级（与
  experiment_runs 同失败语义）。产物字节走 Artifact 链，不进本表。
- 撤销材料：artifact 来源在创建时经读链核对（404 即拒绝）；run 来源经
  归属校验；旧产物按现有保留/删除规则处理，本模块不删历史。
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

logger = logging.getLogger("nexus.document_jobs")

JOB_TERMINAL = ("succeeded", "partial", "failed", "cancelled")

_memory_jobs: dict[str, dict[str, Any]] = {}


class DocumentError(Exception):
    """文档作业域失败：携带机器可读 code（fail-closed 语义）。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def _now() -> float:
    return time.time()


def _pg_settings() -> tuple[str, str] | None:
    from nexus.experiment_runs import _pg_settings as runs_pg_settings

    try:
        return runs_pg_settings()
    except Exception:  # noqa: BLE001 - 配置不可读即内存降级
        return None


_JOB_KEYS = (
    "job_id", "owner", "session_id", "idempotency_key", "content_hash",
    "title", "template", "template_version", "source", "formats", "status",
    "created_at", "updated_at",
)
_JOB_SELECT = ", ".join(_JOB_KEYS)


def _row_to_job(row: dict[str, Any]) -> dict[str, Any]:
    formats = row.get("formats", {})
    if isinstance(formats, str):
        try:
            formats = json.loads(formats)
        except ValueError:
            formats = {}
    source = row.get("source", {})
    if isinstance(source, str):
        try:
            source = json.loads(source)
        except ValueError:
            source = {}
    return {
        "job_id": str(row.get("job_id") or ""),
        "owner": str(row.get("owner") or ""),
        "session_id": str(row.get("session_id") or ""),
        "idempotency_key": str(row.get("idempotency_key") or ""),
        "content_hash": str(row.get("content_hash") or ""),
        "title": str(row.get("title") or ""),
        "template": str(row.get("template") or ""),
        "template_version": str(row.get("template_version") or ""),
        "source": source if isinstance(source, dict) else {},
        "formats": formats if isinstance(formats, dict) else {},
        "status": str(row.get("status") or "queued"),
        "created_at": float(row.get("created_at") or 0),
        "updated_at": float(row.get("updated_at") or 0),
    }


def _row_from_pg(found: Any) -> dict[str, Any]:
    return _row_to_job(dict(zip(_JOB_KEYS, found)))


def _insert_row(row: dict[str, Any]) -> None:
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        try:
            import psycopg

            with psycopg.connect(dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"INSERT INTO {schema}.nexus_document_jobs "
                        f"({_JOB_SELECT}) "
                        f"VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        f"ON CONFLICT (job_id) DO NOTHING",
                        (
                            row["job_id"], row["owner"], row["session_id"],
                            row.get("idempotency_key", ""),
                            row.get("content_hash", ""),
                            row.get("title", ""),
                            row.get("template", ""),
                            row.get("template_version", ""),
                            json.dumps(row.get("source") or {},
                                       ensure_ascii=False),
                            json.dumps(row.get("formats") or {},
                                       ensure_ascii=False),
                            row.get("status", "queued"),
                            row.get("created_at", 0), row.get("updated_at", 0),
                        ),
                    )
            return
        except Exception as error:  # noqa: BLE001
            logger.warning("document job pg insert failed, memory: %s", error)
    _memory_jobs[row["job_id"]] = dict(row)


def _update_row(row: dict[str, Any]) -> None:
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        try:
            import psycopg

            with psycopg.connect(dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE {schema}.nexus_document_jobs SET formats=%s, "
                        f"status=%s, updated_at=%s WHERE job_id=%s",
                        (
                            json.dumps(row.get("formats") or {},
                                       ensure_ascii=False),
                            row.get("status", "queued"),
                            row.get("updated_at", _now()),
                            row["job_id"],
                        ),
                    )
            return
        except Exception as error:  # noqa: BLE001
            logger.warning("document job pg update failed: %s", error)
    _memory_jobs[row["job_id"]] = dict(row)


def get_job(job_id: str) -> dict[str, Any] | None:
    """读作业（归属由调用方校验；PG 优先，失败记日志后读内存）。"""
    job_id = (job_id or "").strip()[:64]
    if not job_id:
        return None
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        try:
            import psycopg

            with psycopg.connect(dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT {_JOB_SELECT} "
                        f"FROM {schema}.nexus_document_jobs WHERE job_id=%s",
                        (job_id,),
                    )
                    found = cur.fetchone()
            if found is not None:
                return _row_from_pg(found)
        except Exception as error:  # noqa: BLE001
            logger.warning("document job pg read failed: %s", error)
    stored = _memory_jobs.get(job_id)
    return _row_to_job(dict(stored)) if stored is not None else None


def find_by_idempotency(owner: str, idempotency_key: str) -> dict[str, Any] | None:
    """按 (owner, 幂等键) 找作业（PG 优先，内存回退全表扫描）。"""
    owner = (owner or "").strip()
    key = (idempotency_key or "").strip()[:128]
    if not owner or not key:
        return None
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        try:
            import psycopg

            with psycopg.connect(dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT {_JOB_SELECT} "
                        f"FROM {schema}.nexus_document_jobs "
                        f"WHERE owner=%s AND idempotency_key=%s "
                        f"ORDER BY created_at DESC LIMIT 1",
                        (owner, key),
                    )
                    found = cur.fetchone()
            if found is not None:
                return _row_from_pg(found)
        except Exception as error:  # noqa: BLE001
            logger.warning("document job pg idempotency read failed: %s", error)
    candidates = [dict(v) for v in _memory_jobs.values()
                  if str(v.get("owner") or "") == owner
                  and str(v.get("idempotency_key") or "") == key]
    if not candidates:
        return None
    candidates.sort(key=lambda item: float(item.get("created_at") or 0),
                    reverse=True)
    return _row_to_job(candidates[0])


def _overall_status(formats: dict[str, Any]) -> str:
    states = [str((info or {}).get("status") or "failed")
              for info in formats.values()]
    if not states:
        return "failed"
    if all(state == "succeeded" for state in states):
        return "succeeded"
    if any(state == "succeeded" for state in states):
        return "partial"
    return "failed"


async def create_and_render(
    *, owner: str, session_id: str, frozen: dict[str, Any],
    formats: list[str], template: str = "",
    idempotency_key: str = "", source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """创建作业并同步渲染（幂等＋落盘＋产物写入）。

    - 同键同内容 → 返回原作业 deduped（不重渲不重写）；
    - 同键不同内容 → DocumentError(DOCUMENT_CONFLICT)；
    - 渲染中断（异常）→ 已有成功格式保留，作业 failed/partial 落盘后抛错，
      调用方可凭 job_id 重试（只跑失败格式）。
    返回 {"job", "deduped"}。
    """
    from nexus import artifact_client
    from nexus import document_output as output_module

    owner = (owner or "").strip()
    session_id = (session_id or "").strip()
    if not owner:
        raise DocumentError("DOCUMENT_OWNER_EMPTY", "owner 不能为空。")
    template = (template or str(frozen.get("template") or "tech_doc")).strip()
    if template not in output_module.DOCUMENT_TEMPLATES:
        raise DocumentError("TEMPLATE_UNKNOWN", f"未知模板：{template}")
    wanted: list[str] = []
    for fmt in formats or []:
        cleaned = str(fmt or "").strip().lower()
        if cleaned and cleaned not in wanted:
            wanted.append(cleaned)
    for cleaned in wanted:
        if cleaned not in output_module.SUPPORTED_FORMATS:
            raise DocumentError("FORMAT_UNKNOWN", f"不支持的格式：{cleaned}")
    if not wanted:
        raise DocumentError("FORMAT_EMPTY", "未指定任何格式。")
    content_hash = str(frozen.get("content_hash") or "")
    if not content_hash:
        raise DocumentError("DOCUMENT_HASH_EMPTY", "冻结内容缺 hash。")
    key = (idempotency_key or "").strip()[:128]
    if key:
        existing = find_by_idempotency(owner, key)
        if existing is not None:
            if str(existing.get("content_hash") or "") == content_hash:
                return {"job": existing, "deduped": True}
            raise DocumentError(
                "DOCUMENT_CONFLICT",
                "同幂等键已有不同内容的作业；换键或确认后重试，不覆盖。",
            )
    now = _now()
    formats_state: dict[str, Any] = {
        fmt: {"status": "queued", "engine": "", "engine_fallback": "",
              "artifact_id": "", "detail": "待渲染", "checks": {}}
        for fmt in wanted
    }
    # 冻结快照随行持久化（重试/恢复只跑失败格式时复用同一快照；产物字节
    # 不进本表，走 Artifact 链）。
    source_stored = dict(source or {})
    source_stored["_frozen"] = {"markdown": str(frozen.get("markdown") or ""),
                                "title": str(frozen.get("title") or ""),
                                "template": template}
    row = {
        "job_id": f"docjob-{uuid.uuid4().hex[:12]}",
        "owner": owner, "session_id": session_id,
        "idempotency_key": key, "content_hash": content_hash,
        "title": str(frozen.get("title") or "")[:120],
        "template": template,
        "template_version": output_module.DOCUMENT_TEMPLATES[template]["version"],
        "source": source_stored,
        "formats": formats_state, "status": "rendering",
        "created_at": now, "updated_at": now,
    }
    _insert_row(row)
    try:
        built = output_module.build_document_formats(frozen=frozen, formats=wanted)
    except output_module.DocumentRenderError as error:
        row["status"] = "failed"
        for fmt in wanted:
            row["formats"][fmt] = {
                "status": "failed", "engine": "", "engine_fallback": "",
                "artifact_id": "", "detail": f"{error.code}：{error}",
                "checks": {"ok": False}}
        row["updated_at"] = _now()
        _update_row(row)
        raise DocumentError(error.code, str(error)) from error
    per_format = built.get("formats") or {}
    for fmt in wanted:
        rendered = per_format.get(fmt) or {}
        if str(rendered.get("status") or "") != "succeeded":
            row["formats"][fmt] = {
                "status": "failed",
                "engine": str(rendered.get("engine") or ""),
                "engine_fallback": str(rendered.get("engine_fallback") or ""),
                "artifact_id": "",
                "detail": str(rendered.get("detail") or "渲染失败")[:500],
                "checks": rendered.get("checks") or {"ok": False},
            }
            continue
        if fmt == "markdown":
            text = str(rendered.get("text") or "")
            written = await artifact_client.write_artifact_via_backend(
                artifact_type="markdown",
                title=str(frozen.get("title") or "文档"),
                content=text, user_id=owner,
                run_id=str((source or {}).get("run_id") or ""))
        elif fmt == "word":
            from nexus import artifact_client as binary_client

            written = await binary_client.write_binary_artifact_via_backend(
                artifact_type="word",
                title=str(frozen.get("title") or "文档"),
                raw=bytes(rendered.get("bytes") or b""), user_id=owner,
                run_id=str((source or {}).get("run_id") or ""))
        elif fmt == "latex":
            written = await artifact_client.write_artifact_via_backend(
                artifact_type="latex",
                title=f"{str(frozen.get('title') or '文档')}（LaTeX）",
                content=str(rendered.get("text") or ""), user_id=owner,
                run_id=str((source or {}).get("run_id") or ""))
            if written.get("status") == "success":
                try:
                    from nexus import document_output as output_module

                    compile_result = output_module.try_compile_latex(
                        str(rendered.get("text") or ""))
                except Exception:  # noqa: BLE001 - 编译自检失败不推翻交付
                    compile_result = {"compiled": False, "code": "COMPILE_UNAVAILABLE"}
                checks = dict(rendered.get("checks") or {"ok": True})
                checks["compile"] = {"compiled": bool(compile_result.get("compiled")),
                                     "code": str(compile_result.get("code") or ""),
                                     "detail": str(compile_result.get("detail") or "")}
                rendered = dict(rendered)
                rendered["checks"] = checks
        else:  # pdf
            from nexus import artifact_client as binary_client

            written = await binary_client.write_binary_artifact_via_backend(
                artifact_type="pdf",
                title=f"{str(frozen.get('title') or '文档')}（PDF）",
                raw=bytes(rendered.get("bytes") or b""), user_id=owner,
                run_id=str((source or {}).get("run_id") or ""))
        if written.get("status") != "success":
            row["formats"][fmt] = {
                "status": "failed",
                "engine": str(rendered.get("engine") or ""),
                "engine_fallback": str(rendered.get("engine_fallback") or ""),
                "artifact_id": "",
                "detail": f"产物写入失败（{written.get('code', '')}）："
                          f"{written.get('detail', '')}"[:500],
                "checks": rendered.get("checks") or {"ok": True},
            }
            continue
        row["formats"][fmt] = {
            "status": "succeeded",
            "engine": str(rendered.get("engine") or ""),
            "engine_fallback": str(rendered.get("engine_fallback") or ""),
            "artifact_id": str(written["artifact"].get("artifact_id") or ""),
            "detail": str(rendered.get("detail") or "")[:500],
            "checks": rendered.get("checks") or {"ok": True},
        }
    row["status"] = _overall_status(row["formats"])
    row["updated_at"] = _now()
    _update_row(row)
    return {"job": _row_to_job(row), "deduped": False}


async def retry_failed(*, job_id: str, owner: str) -> dict[str, Any]:
    """重试作业的失败格式（只跑失败格式；成功格式保留不重写）。

    幂等：无失败格式即原样返回 deduped。取消/终态 succeeded 无需重试
    （succeeded 全成；cancelled 需新建作业）。
    """
    from nexus import artifact_client
    from nexus import document_output as output_module

    job = get_job(job_id)
    if job is None:
        raise DocumentError("JOB_NOT_FOUND", "文档作业不存在。")
    if (owner or "") != job["owner"]:
        raise DocumentError("JOB_FORBIDDEN", "无权操作他人的文档作业。")
    if job["status"] == "cancelled":
        raise DocumentError("JOB_CANCELLED", "作业已取消，请新建作业。")
    failed = [fmt for fmt, info in (job.get("formats") or {}).items()
              if str((info or {}).get("status") or "") != "succeeded"]
    if not failed:
        return {"job": job, "deduped": True, "retried": []}
    frozen_holder = (job.get("source") or {}).get("_frozen")
    if not isinstance(frozen_holder, dict) or not frozen_holder.get("markdown"):
        raise DocumentError(
            "JOB_FROZEN_MISSING",
            "作业未携带冻结快照（旧作业），请用原内容新建作业。",
        )
    # 重试与创建读同一快照（模板沿用作业模板，不重新解释）。
    frozen_retry = {"markdown": str(frozen_holder.get("markdown") or ""),
                    "title": str(frozen_holder.get("title") or job.get("title") or ""),
                    "template": str(job.get("template") or "tech_doc")}
    try:
        built = output_module.build_document_formats(
            frozen={**frozen_retry,
                    "document_id": "", "content_hash": job.get("content_hash") or ""},
            formats=failed)
    except output_module.DocumentRenderError as error:
        raise DocumentError(error.code, str(error)) from error
    per_format = built.get("formats") or {}
    formats_state = dict(job.get("formats") or {})
    for fmt in failed:
        rendered = per_format.get(fmt) or {}
        if str(rendered.get("status") or "") != "succeeded":
            formats_state[fmt] = {
                "status": "failed",
                "engine": str(rendered.get("engine") or ""),
                "engine_fallback": str(rendered.get("engine_fallback") or ""),
                "artifact_id": "",
                "detail": str(rendered.get("detail") or "渲染失败")[:500],
                "checks": rendered.get("checks") or {"ok": False},
            }
            continue
        if fmt == "markdown":
            written = await artifact_client.write_artifact_via_backend(
                artifact_type="markdown",
                title=str(job.get("title") or "文档"),
                content=str(rendered.get("text") or ""), user_id=owner,
                run_id=str((job.get("source") or {}).get("run_id") or ""))
        elif fmt == "word":
            from nexus import artifact_client as binary_client

            written = await binary_client.write_binary_artifact_via_backend(
                artifact_type="word",
                title=str(job.get("title") or "文档"),
                raw=bytes(rendered.get("bytes") or b""), user_id=owner,
                run_id=str((job.get("source") or {}).get("run_id") or ""))
        elif fmt == "latex":
            written = await artifact_client.write_artifact_via_backend(
                artifact_type="latex",
                title=f"{str(job.get('title') or '文档')}（LaTeX）",
                content=str(rendered.get("text") or ""), user_id=owner,
                run_id=str((job.get("source") or {}).get("run_id") or ""))
            if written.get("status") == "success":
                try:
                    from nexus import document_output as output_module

                    compile_result = output_module.try_compile_latex(
                        str(rendered.get("text") or ""))
                except Exception:  # noqa: BLE001
                    compile_result = {"compiled": False, "code": "COMPILE_UNAVAILABLE"}
                checks = dict(rendered.get("checks") or {"ok": True})
                checks["compile"] = {"compiled": bool(compile_result.get("compiled")),
                                     "code": str(compile_result.get("code") or ""),
                                     "detail": str(compile_result.get("detail") or "")}
                rendered = dict(rendered)
                rendered["checks"] = checks
        else:
            from nexus import artifact_client as binary_client

            written = await binary_client.write_binary_artifact_via_backend(
                artifact_type="pdf",
                title=f"{str(job.get('title') or '文档')}（PDF）",
                raw=bytes(rendered.get("bytes") or b""), user_id=owner,
                run_id=str((job.get("source") or {}).get("run_id") or ""))
        if written.get("status") != "success":
            formats_state[fmt] = {
                "status": "failed",
                "engine": str(rendered.get("engine") or ""),
                "engine_fallback": str(rendered.get("engine_fallback") or ""),
                "artifact_id": "",
                "detail": f"产物写入失败（{written.get('code', '')}）"[:500],
                "checks": rendered.get("checks") or {"ok": True},
            }
            continue
        formats_state[fmt] = {
            "status": "succeeded",
            "engine": str(rendered.get("engine") or ""),
            "engine_fallback": str(rendered.get("engine_fallback") or ""),
            "artifact_id": str(written["artifact"].get("artifact_id") or ""),
            "detail": str(rendered.get("detail") or "")[:500],
            "checks": rendered.get("checks") or {"ok": True},
        }
    updated = dict(job)
    updated["formats"] = formats_state
    updated["status"] = _overall_status(formats_state)
    updated["updated_at"] = _now()
    _update_row(updated)
    return {"job": _row_to_job(updated), "deduped": False, "retried": failed}


def cancel_job(*, job_id: str, owner: str) -> dict[str, Any]:
    """取消作业（仅非终态有效；终态返回 already_terminal）。"""
    job = get_job(job_id)
    if job is None:
        raise DocumentError("JOB_NOT_FOUND", "文档作业不存在。")
    if (owner or "") != job["owner"]:
        raise DocumentError("JOB_FORBIDDEN", "无权操作他人的文档作业。")
    if str(job.get("status") or "") in JOB_TERMINAL:
        return {**job, "already_terminal": True}
    updated = dict(job)
    updated["status"] = "cancelled"
    updated["updated_at"] = _now()
    _update_row(updated)
    return {**_row_to_job(updated), "already_terminal": False}


def public_job_view(job: dict[str, Any]) -> dict[str, Any]:
    """对外视图（结构文件有效/公式可编辑/编译成功/排版可用分开记录）。"""
    formats_view: dict[str, Any] = {}
    for fmt, info in (job.get("formats") or {}).items():
        info = info or {}
        checks = info.get("checks") or {}
        # 自检字典可能是 validate/verify 的 {ok, checks{…}, detail} 形：
        # 数学/编译明细在内层，顶层缺席即 False/空。
        inner = checks.get("checks") if isinstance(checks.get("checks"), dict) else {}
        compile_info = (checks.get("compile") or {}
                        if isinstance(checks.get("compile"), dict) else {})
        formats_view[fmt] = {
            "status": str(info.get("status") or "failed"),
            "engine": str(info.get("engine") or ""),
            "engine_fallback": str(info.get("engine_fallback") or ""),
            "artifact_id": str(info.get("artifact_id") or ""),
            "detail": str(info.get("detail") or ""),
            "structural_valid": bool(checks.get("ok", False)),
            "math_editable": bool(checks.get("math_editable", False)
                                  or inner.get("math_editable", False)),
            "math_native": bool(checks.get("math_native", False)
                                or inner.get("math_native", False)),
            "compile_code": str(compile_info.get("code", "")
                                or checks.get("code", "")
                                or inner.get("code", "") or ""),
        }
    return {
        "job_id": job.get("job_id", ""),
        "status": job.get("status", ""),
        "title": job.get("title", ""),
        "template": job.get("template", ""),
        "template_version": job.get("template_version", ""),
        "content_hash": job.get("content_hash", ""),
        "formats": formats_view,
        "created_at": job.get("created_at", 0),
        "updated_at": job.get("updated_at", 0),
    }


def clear_memory_store() -> None:
    """测试隔离：清空内存作业（PG 行不受影响）。"""
    _memory_jobs.clear()
