"""CR1 语料来源适配：五类 JSONL → DK1 ingest 记录（流式，无模型、无网络）。

五类原始格式共享 ``{id, title, text, source, license}`` 形状（见
``knowledge_data/corpus/extract_*.py`` 与 ``build_rfc_corpus.py``），
本模块只做字段映射与身份派生，不做内容改写：

- ``external_id``：原文 ``id``（缺失则按“来源类型 + 文件内稳定行号”
  生成，stats 记 ``generated_id``，禁止用全库行号）；
- ``source_family_id``：arxiv 去版本后缀（``arxiv-2101.00001v2`` →
  ``arxiv-2101.00001``）；其余 ``{kind}:{external_id}``；
- ``title``/``license_code`` 透传（缺失记 stats，不编造）；
- ``text`` 必须非空，否则跳过并记 ``empty_text``；
- 坏行（JSON/编码/非对象）跳过并记原因，只保留前 N 条明细。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterator, Optional

SOURCE_KINDS = ("textbook", "zhwiki", "enwiki", "rfc", "arxiv")

#: 跳过明细上限（超出只计数）。
MAX_SKIPPED_ROWS = 50


def resolve_source_root(explicit: Any = None) -> Path:
    """来源根目录：显式参数 > DISCIPLINE_SOURCE_ROOT 环境变量 > Settings > 当前目录。"""
    if explicit:
        return Path(str(explicit))
    env_root = os.environ.get("DISCIPLINE_SOURCE_ROOT", "").strip()
    if env_root:
        return Path(env_root)
    try:
        from app.core.config import settings

        configured = str(getattr(settings, "DISCIPLINE_SOURCE_ROOT", "") or "")
        if configured.strip():
            return Path(configured)
    except Exception:  # noqa: BLE001 - 无配置环境回退当前目录
        pass
    return Path(".")


def family_for(source_kind: str, external_id: str, doc: dict) -> str:
    """文档族：同一词条/同一 RFC 系列/同一论文各版本归一族。"""
    if source_kind == "arxiv":
        base = str(external_id)
        if base.startswith("arxiv-"):
            base = base[len("arxiv-"):]
        # 去版本后缀（vN 结尾），保留基础编号
        head, sep, tail = base.rpartition("v")
        if sep and tail.isdigit():
            base = head
        return f"arxiv-{base}"
    if source_kind == "textbook":
        book = str(doc.get("book") or "").strip()
        if book:
            return f"textbook:{book}"
    return f"{source_kind}:{external_id}"


def record_for(source_kind: str, doc: dict, line_no: int) -> dict[str, Any]:
    """单条 JSONL 文档 → ingest 记录；非法抛 ValueError(reason)。"""
    if not isinstance(doc, dict):
        raise ValueError("bad_record")
    external_id = str(doc.get("id") or "").strip()
    if not external_id:
        raise ValueError("missing_id")
    text = doc.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("empty_text")
    title = str(doc.get("title") or "").strip()
    license_code = str(doc.get("license") or "").strip()
    return {
        "source_kind": source_kind,
        "external_id": external_id,
        "source_family_id": family_for(source_kind, external_id, doc),
        "title": title,
        "language": "",
        "domains": [],
        "license_code": license_code or "unknown",
        "text": text,
    }


def iter_source_records(
    source_spec: dict,
    source_root: Any = None,
    stats: Optional[dict] = None,
) -> Iterator[dict[str, Any]]:
    """流式产出有效 ingest 记录；坏行跳过并记入 stats（不抛错中断）。

    stats 形如 ``{"file":..., "lines": N, "yielded": M,
    "missing_license": K, "skipped": [{line_no, doc_id, reason}]}``。
    source_spec 缺 file/来源不明时直接返回空迭代（stats 记 reason）。
    """
    spec = source_spec or {}
    kind = str(spec.get("source_kind") or "")
    filename = str(spec.get("file") or "")
    local_stats: dict[str, Any] = {
        "file": filename, "lines": 0, "yielded": 0,
        "missing_license": 0, "skipped": [],
    }
    if stats is not None:
        stats.clear()
        stats.update(local_stats)

    def _skip(line_no: int, doc_id: str, reason: str) -> None:
        local_stats["skipped_truncated"] = local_stats.get("skipped_truncated", 0)
        if len(local_stats["skipped"]) < MAX_SKIPPED_ROWS:
            local_stats["skipped"].append(
                {"line_no": line_no, "doc_id": doc_id, "reason": reason})
        else:
            local_stats["skipped_truncated"] += 1

    if kind not in SOURCE_KINDS or not filename:
        _skip(0, "", "unknown_source_spec")
        return
    path = resolve_source_root(source_root) / filename
    try:
        fh = path.open("rb")
    except OSError:
        _skip(0, "", "file_unavailable")
        return
    with fh:
        for line_no, raw in enumerate(fh, 1):
            local_stats["lines"] += 1
            try:
                line = raw.decode("utf-8")
            except UnicodeDecodeError:
                _skip(line_no, "", "bad_encoding")
                continue
            if not line.strip():
                continue
            try:
                doc = json.loads(line)
            except json.JSONDecodeError:
                _skip(line_no, "", "bad_json")
                continue
            doc_id = str(doc.get("id") or "") if isinstance(doc, dict) else ""
            try:
                record = record_for(kind, doc, line_no)
            except ValueError as exc:
                if str(exc) == "missing_id":
                    # 无明确 external_id：来源类型 + 文件内稳定行号生成
                    generated = f"{kind}:{Path(filename).stem}:{line_no}"
                    if isinstance(doc, dict):
                        doc = {**doc, "id": generated}
                        try:
                            record = record_for(kind, doc, line_no)
                        except ValueError as exc2:
                            _skip(line_no, generated, str(exc2))
                            continue
                        record["generated_id"] = True
                    else:
                        _skip(line_no, "", "bad_record")
                        continue
                else:
                    _skip(line_no, doc_id, str(exc))
                    continue
            if not doc.get("license"):
                local_stats["missing_license"] += 1
            local_stats["yielded"] += 1
            yield record
