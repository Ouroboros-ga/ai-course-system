from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


FINAL_QUERY_STRATA = {
    "exact_term",
    "definition",
    "formula_or_code",
    "paraphrase",
    "cross_language_alias",
    "multi_hop_relation",
    "no_answer",
}
QUERY_HEADERS = {
    "seed_id",
    "course_id",
    "knowledge_point_id",
    "knowledge_point",
    "ppt_page_range",
    "query_text",
    "query_variant",
    "review_status",
}
KP_HEADERS = {
    "knowledge_point_id",
    "course_id",
    "knowledge_point",
    "ppt_page_start",
    "ppt_page_end",
}
PAGE_HEADERS = {"course_id", "ppt_page", "source_file"}


def _read_csv(path: Path) -> tuple[str, list[dict[str, str]]]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        rows = list(csv.DictReader(text.splitlines()))
        if rows or text.strip():
            return encoding, rows
    raise ValueError(f"unsupported_csv_encoding:{path.name}")


def audit_seed_exports(source_dir: Path) -> dict[str, Any]:
    source_dir = Path(source_dir)
    exports: list[dict[str, Any]] = []
    query_rows: list[dict[str, str]] | None = None
    kp_rows: list[dict[str, str]] | None = None
    page_rows: list[dict[str, str]] | None = None

    for path in sorted(source_dir.glob("*.csv"), key=lambda value: value.name):
        encoding, rows = _read_csv(path)
        headers = set(rows[0]) if rows else set()
        role = "unmatched"
        if QUERY_HEADERS <= headers:
            role, query_rows = "query_seed_export", rows
        elif KP_HEADERS <= headers:
            role, kp_rows = "knowledge_point_export", rows
        elif PAGE_HEADERS <= headers:
            role, page_rows = "page_index_export", rows
        exports.append({"file": path.name, "encoding": encoding, "rows": len(rows), "role": role})

    reasons: list[str] = []
    warnings: list[str] = []
    if query_rows is None:
        reasons.append("query_seed_export_missing")
        query_rows = []
    if kp_rows is None:
        reasons.append("knowledge_point_export_missing")
        kp_rows = []
    if page_rows is None:
        reasons.append("page_index_export_missing")
        page_rows = []

    query_review = Counter(row.get("review_status", "") for row in query_rows)
    if query_review != Counter({"已复核": len(query_rows)}):
        reasons.append("queries_not_all_human_reviewed")
    if not 60 <= len(query_rows) <= 100:
        reasons.append("final_query_count_must_be_60_to_100")
    if any("expected_answerability" in row or "gold_answer_hint" in row for row in query_rows):
        warnings.append("seed_only_gold_like_columns_must_be_removed_before_selection")
    final_strata = {row.get("query_stratum") for row in query_rows if row.get("query_stratum")}
    if final_strata != FINAL_QUERY_STRATA:
        reasons.append("all_seven_human_reviewed_query_strata_required")

    kp_ids = [row.get("knowledge_point_id", "") for row in kp_rows]
    if not 40 <= len(kp_ids) <= 80:
        reasons.append("knowledge_point_count_must_be_40_to_80")
    if len(kp_ids) != len(set(kp_ids)) or any(not value for value in kp_ids):
        reasons.append("knowledge_point_ids_must_be_nonempty_unique")

    page_max: dict[str, int] = {}
    for row in page_rows:
        course_id = row.get("course_id", "")
        try:
            page = int(row.get("ppt_page", ""))
        except ValueError:
            reasons.append(f"invalid_page_index:{course_id}:{row.get('ppt_page', '')}")
            continue
        page_max[course_id] = max(page_max.get(course_id, 0), page)
    for row in kp_rows:
        course_id = row.get("course_id", "")
        try:
            start, end = int(row.get("ppt_page_start", "")), int(row.get("ppt_page_end", ""))
        except ValueError:
            reasons.append(f"invalid_kp_page_range:{row.get('knowledge_point_id', '')}")
            continue
        if start < 1 or end < start or end > page_max.get(course_id, 0):
            reasons.append(f"kp_page_range_out_of_course:{row.get('knowledge_point_id', '')}")

    return {
        "status": "ready_for_selection_import" if not reasons else "blocked_pending_human_selection",
        "ready_for_selection_import": not reasons,
        "exports": exports,
        "counts": {
            "queries": len(query_rows),
            "knowledge_points": len(kp_rows),
            "pages": len(page_rows),
            "courses": len(page_max),
        },
        "query_review_status": dict(sorted(query_review.items())),
        "query_variants": dict(sorted(Counter(row.get("query_variant", "") for row in query_rows).items())),
        "page_count_by_course": dict(sorted(page_max.items())),
        "reasons": sorted(set(reasons)),
        "warnings": sorted(set(warnings)),
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Audit human-selection seed CSV exports")
    parser.add_argument("source_dir", type=Path)
    args = parser.parse_args()
    result = audit_seed_exports(args.source_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["ready_for_selection_import"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
