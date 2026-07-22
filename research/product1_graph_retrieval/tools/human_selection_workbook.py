from __future__ import annotations

import argparse
import copy
import json
import posixpath
import re
import sys
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from src.canonical import write_json
from src.fixture_io import load_json
from tools.human_selection_review import (
    HumanSelectionReviewError,
    validate_selection_review,
)


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CELL_REF = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")
SELECTION_ATTESTATION = "human_selected_without_gold_labels_or_model_rankings"

GOVERNANCE_ROWS = (
    ("authorization.status", "必须为 approved"),
    ("authorization.authorized_by", "受控身份引用或 member_id"),
    ("authorization.evidence_ref", "授权审签证据"),
    ("authorization.valid_from", "ISO 8601"),
    ("authorization.expires_at", "与 no_expiry 二选一"),
    ("authorization.no_expiry", "TRUE/FALSE；与 expires_at 二选一"),
    ("privacy.status", "必须为 approved"),
    ("privacy.reviewed_by", "隐私复核人"),
    ("privacy.evidence_ref", "隐私审签证据"),
    ("privacy.known_direct_identifiers_present", "TRUE/FALSE；原始课件已发现邮箱模式"),
    ("privacy.sanitization_plan_ref", "清洗计划引用"),
    ("repository_storage_authorized", "TRUE/FALSE；内部仓库存储许可"),
    ("human_finalization.status", "全部复核完成后填写 approved"),
    ("human_finalization.finalized_by", "最终确认人的受控 member_id"),
    ("human_finalization.finalized_at", "ISO 8601"),
    ("human_finalization.attestation", f"必须为 {SELECTION_ATTESTATION}"),
)

HEADERS = {
    "治理复核": ["JSON路径", "当前值", "真人填写值", "说明"],
    "课程复核": ["course_id", "课程名", "workbook历史文件名", "实际PPTX", "实际PDF", "页数",
        "PPTX SHA256", "PDF SHA256", "文件映射状态", "文件映射复核人", "文件映射证据",
        "脱敏词(竖线分隔)", "脱敏状态", "脱敏复核人", "脱敏证据", "OCR provenance JSON"],
    "查询复核": ["candidate_query_id", "seed_id", "course_id", "知识点seed_id", "知识点",
        "作者复核页码(不进盲标包)", "query_text", "source_variant", "建议query_type(非Gold)",
        "建议stratum(非Gold)", "建议split(非Gold)", "真人选择", "final_query_type",
        "final_query_stratum", "final_split", "tags(竖线分隔)", "review_status", "reviewed_by",
        "review_note"],
    "知识点复核": ["candidate_kp_id", "seed_kp_id", "course_id", "canonical_label", "来源章节(作者复核)",
        "来源页码(作者复核)", "建议split(非Gold)", "真人选择", "aliases(竖线分隔)",
        "final_chapter_id", "final_chapter_path JSON", "final_split", "review_status", "reviewed_by",
        "review_note"],
    "章节复核": ["candidate_chapter_id", "course_id", "来源章节标签", "建议起始页(非Gold)",
        "建议结束页(非Gold)", "真人选择", "final_start_slide", "final_end_slide", "final_chapter_id",
        "final_chapter_path JSON", "review_status", "reviewed_by", "review_note"],
    "OCR复核": ["task_id", "course_id", "slide_number", "原生文本字符", "图片数", "受控原页引用",
        "真人选择", "decision", "blocks JSON(order/text/bbox/confidence)", "review_status", "reviewed_by",
        "review_note"],
    "范围外查询": ["candidate_scope_query_id", "真人选择", "unavailable_course_id", "query_text",
        "final_query_type", "final_split", "tags", "review_status", "reviewed_by", "review_note"],
}

PROTECTED_COLUMN_COUNT = {
    "治理复核": 2,
    "课程复核": 8,
    "查询复核": 11,
    "知识点复核": 7,
    "章节复核": 5,
    "OCR复核": 6,
    "范围外查询": 1,
}


class HumanSelectionWorkbookError(ValueError):
    pass


def _resolved_json_path(packet: dict[str, Any], path: str) -> list[str]:
    parts = path.split(".")
    if parts[0] not in packet and parts[0] in packet.get("source_governance", {}):
        return ["source_governance", *parts]
    return parts


def _json_path_get(packet: dict[str, Any], path: str) -> Any:
    value: Any = packet
    for part in _resolved_json_path(packet, path):
        value = value[part]
    return value


def _json_path_set(packet: dict[str, Any], path: str, value: Any) -> None:
    target: Any = packet
    parts = _resolved_json_path(packet, path)
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value


def _review_cells(review: dict[str, Any]) -> list[Any]:
    selected = review.get("selected")
    return ["是" if selected is True else "否" if selected is False else "",
        "" if review.get("status") == "pending" else review.get("status", ""),
        review.get("reviewed_by") or "", review.get("review_note") or ""]


def _human_governance_value(packet: dict[str, Any], path: str) -> Any:
    value = _json_path_get(packet, path)
    return "" if value is None else value


def review_workbook_tables(source_packet: dict[str, Any],
    human_packet: dict[str, Any] | None = None) -> dict[str, list[list[Any]]]:
    """Return the canonical review-sheet cells used by the importer and tests.

    Protected cells always come from source_packet. Human cells are blank for a
    new workbook, or come from human_packet when rendering a completed example.
    """
    validate_selection_review(source_packet)
    human = human_packet
    rendered_human = human_packet or source_packet
    tables: dict[str, list[list[Any]]] = {}
    governance_rows = []
    for path, description in GOVERNANCE_ROWS:
        current = _json_path_get(source_packet, path)
        entered = _human_governance_value(human, path) if human is not None else ""
        governance_rows.append([path, "" if current is None else current, entered, description])
    tables["治理复核"] = [HEADERS["治理复核"], *governance_rows]

    human_courses = {row["course_id"]: row for row in rendered_human.get("courses", [])}
    rows = []
    for course in source_packet["courses"]:
        reviewed = human_courses.get(course["course_id"])
        if reviewed:
            mapping = reviewed["file_mapping_review"]
            redaction = reviewed["redaction_review"]
            human_cells = ["" if mapping["status"] == "pending_record_completion" else mapping["status"],
                mapping.get("reviewed_by") or "", mapping.get("evidence_ref") or "",
                " | ".join(reviewed.get("redaction_terms", [])),
                "" if redaction["status"] == "pending_record_completion" else redaction["status"],
                redaction.get("reviewed_by") or "", redaction.get("evidence_ref") or "",
                json.dumps(reviewed["ocr_provenance"], ensure_ascii=False, separators=(",", ":"))
                if reviewed.get("ocr_provenance") else ""]
        else:
            human_cells = [""] * 8
        rows.append([course["course_id"], course["course_name"], course["workbook_source_file"],
            course["actual_pptx"], course["actual_pdf"], course["page_count"], course["pptx_sha256"],
            course["pdf_sha256"], *human_cells])
    tables["课程复核"] = [HEADERS["课程复核"], *rows]

    def human_by(key: str, collection: str) -> dict[str, dict[str, Any]]:
        return {row[key]: row for row in rendered_human.get(collection, [])}

    human_queries = human_by("candidate_query_id", "query_candidates")
    rows = []
    for item in source_packet["query_candidates"]:
        reviewed = human_queries.get(item["candidate_query_id"])
        human_cells = ([*_review_cells(reviewed["human_review"])[:1], reviewed.get("final_query_type") or "",
            reviewed.get("final_query_stratum") or "", reviewed.get("final_split") or "",
            " | ".join(reviewed.get("tags", [])), *_review_cells(reviewed["human_review"])[1:]]
            if reviewed else [""] * 8)
        rows.append([item["candidate_query_id"], item["seed_id"], item["course_id"],
            item["knowledge_point_seed_id"], item["knowledge_point_label"],
            item["source_page_range_for_author_review_only"], item["text"], item["source_variant"],
            item["suggested_query_type_not_gold"], item["suggested_query_stratum_not_gold"],
            item["suggested_split_not_gold"], *human_cells])
    tables["查询复核"] = [HEADERS["查询复核"], *rows]

    human_kps = human_by("candidate_knowledge_point_id", "knowledge_point_candidates")
    rows = []
    for item in source_packet["knowledge_point_candidates"]:
        reviewed = human_kps.get(item["candidate_knowledge_point_id"])
        if reviewed:
            review_cells = _review_cells(reviewed["human_review"])
            human_cells = [review_cells[0], " | ".join(reviewed.get("aliases", [])),
                reviewed.get("final_chapter_id") or "",
                json.dumps(reviewed["final_chapter_path"], ensure_ascii=False, separators=(",", ":"))
                if reviewed.get("final_chapter_path") else "", reviewed.get("final_split") or "",
                *review_cells[1:]]
        else:
            human_cells = [""] * 8
        rows.append([item["candidate_knowledge_point_id"], item["seed_knowledge_point_id"],
            item["course_id"], item["canonical_label"], item["source_chapter_for_author_review_only"],
            item["source_page_range_for_author_review_only"], item["suggested_split_not_gold"], *human_cells])
    tables["知识点复核"] = [HEADERS["知识点复核"], *rows]

    human_chapters = human_by("candidate_chapter_id", "chapter_candidates")
    rows = []
    for item in source_packet["chapter_candidates"]:
        reviewed = human_chapters.get(item["candidate_chapter_id"])
        if reviewed:
            review_cells = _review_cells(reviewed["human_review"])
            human_cells = [review_cells[0], reviewed.get("final_start_slide") or "",
                reviewed.get("final_end_slide") or "", reviewed.get("final_chapter_id") or "",
                json.dumps(reviewed["final_chapter_path"], ensure_ascii=False, separators=(",", ":"))
                if reviewed.get("final_chapter_path") else "", *review_cells[1:]]
        else:
            human_cells = [""] * 8
        rows.append([item["candidate_chapter_id"], item["course_id"], item["source_chapter_label"],
            item["suggested_start_slide_not_gold"], item["suggested_end_slide_not_gold"], *human_cells])
    tables["章节复核"] = [HEADERS["章节复核"], *rows]

    human_ocr = human_by("task_id", "ocr_review_tasks")
    rows = []
    for item in source_packet["ocr_review_tasks"]:
        reviewed = human_ocr.get(item["task_id"])
        if reviewed:
            review_cells = _review_cells(reviewed["human_review"])
            human_cells = [review_cells[0], reviewed.get("decision") or "",
                json.dumps(reviewed.get("blocks", []), ensure_ascii=False, separators=(",", ":"))
                if reviewed.get("blocks") else "", *review_cells[1:]]
        else:
            human_cells = [""] * 6
        rows.append([item["task_id"], item["course_id"], item["slide_number"], item["native_text_chars"],
            item["picture_count"], item["controlled_source_ref"], *human_cells])
    tables["OCR复核"] = [HEADERS["OCR复核"], *rows]

    human_scopes = human_by("candidate_scope_query_id", "scope_query_candidates")
    rows = []
    for item in source_packet["scope_query_candidates"]:
        reviewed = human_scopes.get(item["candidate_scope_query_id"])
        if reviewed:
            review_cells = _review_cells(reviewed["human_review"])
            human_cells = [review_cells[0], reviewed.get("unavailable_course_id") or "",
                reviewed.get("text") or "", reviewed.get("final_query_type") or "",
                reviewed.get("final_split") or "", " | ".join(reviewed.get("tags", [])),
                *review_cells[1:]]
        else:
            human_cells = [""] * 9
        rows.append([item["candidate_scope_query_id"], *human_cells])
    tables["范围外查询"] = [HEADERS["范围外查询"], *rows]
    return tables


def _column_index(reference: str) -> int:
    match = CELL_REF.fullmatch(reference)
    if not match:
        raise HumanSelectionWorkbookError(f"xlsx_cell_reference_invalid:{reference}")
    result = 0
    for character in match.group(1):
        result = result * 26 + ord(character) - 64
    return result - 1


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(node.text or "" for node in item.iter(f"{{{MAIN_NS}}}t"))
        for item in root.findall(f"{{{MAIN_NS}}}si")]


def _cell_value(cell: ElementTree.Element, shared: list[str]) -> Any:
    cell_type = cell.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(f"{{{MAIN_NS}}}t"))
    value_node = cell.find(f"{{{MAIN_NS}}}v")
    if value_node is None or value_node.text is None:
        return None
    value = value_node.text
    if cell_type == "s":
        try:
            return shared[int(value)]
        except (IndexError, ValueError) as exc:
            raise HumanSelectionWorkbookError("xlsx_shared_string_index_invalid") from exc
    if cell_type == "b":
        return value == "1"
    if cell_type in {"str", "e"}:
        return value
    try:
        number = float(value)
    except ValueError:
        return value
    return int(number) if number.is_integer() else number


def _worksheet_targets(archive: zipfile.ZipFile) -> dict[str, str]:
    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    relationships = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    target_by_id = {node.get("Id"): node.get("Target") for node in relationships.findall(
        f"{{{PACKAGE_REL_NS}}}Relationship")}
    targets = {}
    for sheet in workbook.findall(f".//{{{MAIN_NS}}}sheet"):
        name = sheet.get("name")
        relation = sheet.get(f"{{{REL_NS}}}id")
        target = target_by_id.get(relation)
        if not name or not target:
            raise HumanSelectionWorkbookError("xlsx_sheet_relationship_invalid")
        normalized = target.lstrip("/") if target.startswith("/xl/") else posixpath.normpath(
            posixpath.join("xl", target))
        targets[name] = normalized
    return targets


def _read_sheet(archive: zipfile.ZipFile, target: str, shared: list[str], name: str) -> tuple[list[list[Any]], list[str]]:
    root = ElementTree.fromstring(archive.read(target))
    row_values: dict[int, dict[int, Any]] = {}
    formulas = []
    for row in root.findall(f".//{{{MAIN_NS}}}sheetData/{{{MAIN_NS}}}row"):
        row_number = int(row.get("r", "0"))
        cells = row_values.setdefault(row_number, {})
        for cell in row.findall(f"{{{MAIN_NS}}}c"):
            reference = cell.get("r", "")
            column = _column_index(reference)
            if cell.find(f"{{{MAIN_NS}}}f") is not None:
                formulas.append(f"{name}!{reference}")
            value = _cell_value(cell, shared)
            if value is not None:
                cells[column] = value
    if not row_values:
        return [], formulas
    max_column = max((max(cells, default=-1) for cells in row_values.values()), default=-1)
    matrix = []
    for row_number in range(1, max(row_values) + 1):
        cells = row_values.get(row_number, {})
        matrix.append([cells.get(column) for column in range(max_column + 1)])
    return matrix, formulas


def read_review_workbook(path: Path) -> dict[str, list[list[Any]]]:
    path = Path(path)
    if path.suffix.casefold() != ".xlsx":
        raise HumanSelectionWorkbookError("review_workbook_must_be_xlsx")
    try:
        with zipfile.ZipFile(path) as archive:
            shared = _shared_strings(archive)
            targets = _worksheet_targets(archive)
            missing = set(HEADERS) - set(targets)
            if missing:
                raise HumanSelectionWorkbookError(f"review_sheets_missing:{sorted(missing)}")
            result = {}
            formulas = []
            for name in HEADERS:
                matrix, sheet_formulas = _read_sheet(archive, targets[name], shared, name)
                result[name] = matrix
                formulas.extend(sheet_formulas)
            if formulas:
                raise HumanSelectionWorkbookError(f"review_cells_must_not_contain_formulas:{formulas}")
            return result
    except (KeyError, zipfile.BadZipFile, ElementTree.ParseError, OSError) as exc:
        raise HumanSelectionWorkbookError(f"review_workbook_unreadable:{exc}") from exc


def _blank(value: Any) -> bool:
    return value is None or isinstance(value, str) and not value.strip()


def _text(value: Any) -> str | None:
    return None if _blank(value) else str(value).strip()


def _boolean(value: Any, *, optional: bool = True) -> bool | None:
    if _blank(value):
        if optional:
            return None
        raise HumanSelectionWorkbookError("boolean_value_missing")
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().casefold()
    if normalized in {"true", "1", "yes", "是"}:
        return True
    if normalized in {"false", "0", "no", "否"}:
        return False
    raise HumanSelectionWorkbookError(f"boolean_value_invalid:{value}")


def _integer(value: Any) -> int | None:
    if _blank(value):
        return None
    if isinstance(value, bool):
        raise HumanSelectionWorkbookError(f"integer_value_invalid:{value}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise HumanSelectionWorkbookError(f"integer_value_invalid:{value}") from exc
    if not number.is_integer():
        raise HumanSelectionWorkbookError(f"integer_value_invalid:{value}")
    return int(number)


def _json_cell(value: Any, *, expected: type, default: Any) -> Any:
    if _blank(value):
        return copy.deepcopy(default)
    if not isinstance(value, str):
        raise HumanSelectionWorkbookError(f"json_cell_must_be_text:{value}")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HumanSelectionWorkbookError(f"json_cell_invalid:{exc}") from exc
    if not isinstance(parsed, expected):
        raise HumanSelectionWorkbookError(f"json_cell_type_invalid:{expected.__name__}")
    return parsed


def _pipe_list(value: Any) -> list[str]:
    if _blank(value):
        return []
    result = []
    for item in str(value).split("|"):
        cleaned = item.strip()
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result


def _same_protected(expected: Any, actual: Any) -> bool:
    if _blank(expected):
        return _blank(actual)
    if isinstance(expected, bool):
        try:
            return _boolean(actual, optional=False) is expected
        except HumanSelectionWorkbookError:
            return False
    if isinstance(expected, int) and not isinstance(expected, bool):
        try:
            return _integer(actual) == expected
        except HumanSelectionWorkbookError:
            return False
    return str(actual) == str(expected)


def _records(matrix: list[list[Any]], sheet: str, expected_rows: list[list[Any]]) -> list[dict[str, Any]]:
    headers = HEADERS[sheet]
    if not matrix:
        raise HumanSelectionWorkbookError(f"review_sheet_empty:{sheet}")
    actual_headers = ["" if value is None else str(value) for value in matrix[0][:len(headers)]]
    if actual_headers != headers or any(not _blank(value) for value in matrix[0][len(headers):]):
        raise HumanSelectionWorkbookError(f"review_headers_changed:{sheet}")
    data = matrix[1:]
    while data and all(_blank(value) for value in data[-1]):
        data.pop()
    if len(data) != len(expected_rows):
        raise HumanSelectionWorkbookError(f"review_row_count_changed:{sheet}:{len(data)}:{len(expected_rows)}")
    expected_by_key = {str(row[0]): row for row in expected_rows}
    actual_by_key: dict[str, list[Any]] = {}
    for row in data:
        padded = [*row, *([None] * max(0, len(headers) - len(row)))]
        if any(not _blank(value) for value in padded[len(headers):]):
            raise HumanSelectionWorkbookError(f"review_extra_column_data:{sheet}")
        key = _text(padded[0])
        if not key or key in actual_by_key:
            raise HumanSelectionWorkbookError(f"review_row_key_invalid:{sheet}:{key}")
        actual_by_key[key] = padded[:len(headers)]
    if set(actual_by_key) != set(expected_by_key):
        raise HumanSelectionWorkbookError(f"review_row_keys_changed:{sheet}")
    for key, expected in expected_by_key.items():
        actual = actual_by_key[key]
        protected = PROTECTED_COLUMN_COUNT[sheet]
        if sheet == "治理复核":
            protected_indexes = (0, 1, 3)
        else:
            protected_indexes = range(protected)
        for index in protected_indexes:
            if not _same_protected(expected[index], actual[index]):
                raise HumanSelectionWorkbookError(
                    f"protected_cell_changed:{sheet}:{key}:{headers[index]}")
    return [dict(zip(headers, actual_by_key[str(row[0])])) for row in expected_rows]


def _review(row: dict[str, Any], selected: str, status: str, reviewed_by: str, note: str) -> dict[str, Any]:
    return {"status": _text(row[status]) or "pending", "selected": _boolean(row[selected]),
        "reviewed_by": _text(row[reviewed_by]), "review_note": _text(row[note])}


def _all_reviewed(packet: dict[str, Any]) -> bool:
    finalization = packet["human_finalization"]
    if finalization.get("status") != "approved" or finalization.get("attestation") != SELECTION_ATTESTATION:
        return False
    if not finalization.get("finalized_by") or not finalization.get("finalized_at"):
        return False
    governance = packet["source_governance"]
    authorization, privacy = governance["authorization"], governance["privacy"]
    if authorization.get("status") != "approved" or not all(authorization.get(key)
        for key in ("authorized_by", "evidence_ref", "valid_from")):
        return False
    if not authorization.get("expires_at") and authorization.get("no_expiry") is not True:
        return False
    if privacy.get("status") != "approved" or not all(privacy.get(key)
        for key in ("reviewed_by", "evidence_ref", "sanitization_plan_ref")):
        return False
    if not isinstance(privacy.get("known_direct_identifiers_present"), bool):
        return False
    if governance.get("repository_storage_authorized") is not True:
        return False
    for course in packet["courses"]:
        for name in ("file_mapping_review", "redaction_review"):
            record = course[name]
            if record.get("status") != "approved" or not record.get("reviewed_by") or not record.get("evidence_ref"):
                return False
    for collection in ("query_candidates", "knowledge_point_candidates", "chapter_candidates",
        "ocr_review_tasks", "scope_query_candidates"):
        for item in packet[collection]:
            review = item["human_review"]
            if review.get("status") not in {"approved", "rejected"} or not isinstance(review.get("selected"), bool) or not review.get("reviewed_by"):
                return False
    return True


def import_selection_review_workbook(source_packet: dict[str, Any], workbook_path: Path) -> dict[str, Any]:
    validate_selection_review(source_packet)
    if source_packet.get("status") != "pending_human_review":
        raise HumanSelectionWorkbookError("source_review_packet_must_be_pending")
    packet = copy.deepcopy(source_packet)
    expected = review_workbook_tables(source_packet)
    matrices = read_review_workbook(workbook_path)
    rows = {name: _records(matrices[name], name, expected[name][1:]) for name in HEADERS}

    boolean_paths = {"authorization.no_expiry", "privacy.known_direct_identifiers_present",
        "repository_storage_authorized"}
    allowed_paths = {path for path, _ in GOVERNANCE_ROWS}
    for row in rows["治理复核"]:
        path = str(row["JSON路径"])
        if path not in allowed_paths:
            raise HumanSelectionWorkbookError(f"governance_path_invalid:{path}")
        entered = row["真人填写值"]
        if _blank(entered):
            continue
        value = _boolean(entered, optional=False) if path in boolean_paths else _text(entered)
        _json_path_set(packet, path, value)

    by_course = {item["course_id"]: item for item in packet["courses"]}
    for row in rows["课程复核"]:
        course = by_course[str(row["course_id"])]
        course["file_mapping_review"] = {"status": _text(row["文件映射状态"]) or "pending_record_completion",
            "reviewed_by": _text(row["文件映射复核人"]), "evidence_ref": _text(row["文件映射证据"])}
        course["redaction_terms"] = _pipe_list(row["脱敏词(竖线分隔)"])
        course["redaction_review"] = {"status": _text(row["脱敏状态"]) or "pending_record_completion",
            "reviewed_by": _text(row["脱敏复核人"]), "evidence_ref": _text(row["脱敏证据"])}
        course["ocr_provenance"] = _json_cell(row["OCR provenance JSON"], expected=dict, default=None)

    by_query = {item["candidate_query_id"]: item for item in packet["query_candidates"]}
    for row in rows["查询复核"]:
        item = by_query[str(row["candidate_query_id"])]
        item.update({"final_query_type": _text(row["final_query_type"]),
            "final_query_stratum": _text(row["final_query_stratum"]),
            "final_split": _text(row["final_split"]), "tags": _pipe_list(row["tags(竖线分隔)"]),
            "human_review": _review(row, "真人选择", "review_status", "reviewed_by", "review_note")})

    by_kp = {item["candidate_knowledge_point_id"]: item for item in packet["knowledge_point_candidates"]}
    for row in rows["知识点复核"]:
        item = by_kp[str(row["candidate_kp_id"])]
        item.update({"aliases": _pipe_list(row["aliases(竖线分隔)"]),
            "final_chapter_id": _text(row["final_chapter_id"]),
            "final_chapter_path": _json_cell(row["final_chapter_path JSON"], expected=list, default=None),
            "final_split": _text(row["final_split"]),
            "human_review": _review(row, "真人选择", "review_status", "reviewed_by", "review_note")})

    by_chapter = {item["candidate_chapter_id"]: item for item in packet["chapter_candidates"]}
    for row in rows["章节复核"]:
        item = by_chapter[str(row["candidate_chapter_id"])]
        item.update({"final_start_slide": _integer(row["final_start_slide"]),
            "final_end_slide": _integer(row["final_end_slide"]),
            "final_chapter_id": _text(row["final_chapter_id"]),
            "final_chapter_path": _json_cell(row["final_chapter_path JSON"], expected=list, default=None),
            "human_review": _review(row, "真人选择", "review_status", "reviewed_by", "review_note")})

    by_ocr = {item["task_id"]: item for item in packet["ocr_review_tasks"]}
    for row in rows["OCR复核"]:
        item = by_ocr[str(row["task_id"])]
        item.update({"decision": _text(row["decision"]),
            "blocks": _json_cell(row["blocks JSON(order/text/bbox/confidence)"], expected=list, default=[]),
            "human_review": _review(row, "真人选择", "review_status", "reviewed_by", "review_note")})

    by_scope = {item["candidate_scope_query_id"]: item for item in packet["scope_query_candidates"]}
    for row in rows["范围外查询"]:
        item = by_scope[str(row["candidate_scope_query_id"])]
        item.update({"unavailable_course_id": _text(row["unavailable_course_id"]),
            "text": _text(row["query_text"]), "final_query_type": _text(row["final_query_type"]),
            "final_split": _text(row["final_split"]), "tags": _pipe_list(row["tags"]),
            "human_review": _review(row, "真人选择", "review_status", "reviewed_by", "review_note")})

    packet["status"] = "human_review_complete" if _all_reviewed(packet) else "pending_human_review"
    validate_selection_review(packet)
    return packet


def main() -> int:
    parser = argparse.ArgumentParser(description="Import only human-editable B-G0b workbook cells")
    parser.add_argument("pending_review", type=Path)
    parser.add_argument("workbook", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        packet = import_selection_review_workbook(load_json(args.pending_review), args.workbook)
        write_json(args.output, packet)
        result = validate_selection_review(packet) | {"output": str(args.output.resolve())}
    except (HumanSelectionWorkbookError, HumanSelectionReviewError, OSError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "reasons": str(exc).split(";")}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
