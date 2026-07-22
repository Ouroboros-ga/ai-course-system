"""Evidence-grounded, immutable research graph snapshots (not GraphRAG)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from .canonical import canonical_json_bytes, sha256_bytes


GRAPH_SCHEMA_VERSION = "product1-deterministic-course-graph/1.0"
ALLOWED_PREDICATES = {"CONTAINS", "GROUNDED_BY", "MAPPED_TO", "NEXT"}


def _id(prefix: str, *parts: object) -> str:
    return prefix + sha256_bytes("\0".join("" if value is None else str(value) for value in parts).encode("utf-8"))[:24]


def _node(node_type: str, source_id: str, course_id: str, **properties: Any) -> dict[str, Any]:
    return {"node_id": _id("rgn_", node_type, source_id), "node_type": node_type, "source_id": source_id, "course_id": course_id, "properties": properties}


def _edge(subject: str, predicate: str, object_: str, course_id: str, evidence_ids: Iterable[str], *, source: str) -> dict[str, Any]:
    refs = tuple(sorted(set(evidence_ids)))
    return {
        "edge_id": _id("rge_", subject, predicate, object_, ",".join(refs)),
        "subject_node_id": subject,
        "predicate": predicate,
        "object_node_id": object_,
        "course_id": course_id,
        "research_evidence_ids": list(refs),
        "status": "accepted",
        "source": source,
    }


def build_snapshot(
    *,
    source_blocks: Iterable[dict[str, Any]],
    evidence: Iterable[dict[str, Any]],
    knowledge_points: Iterable[dict[str, Any]],
    slides: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build only structural and shared-active-evidence relationships."""

    blocks = {row["block_id"]: row for row in source_blocks}
    active_evidence = {row["research_evidence_id"]: row for row in evidence if row.get("status") == "active"}
    slides_by_id = {row["research_slide_id"]: row for row in slides}
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    course_nodes: dict[str, str] = {}
    chapter_nodes: dict[tuple[str, str], str] = {}
    chapter_first_slide: dict[tuple[str, str], int] = {}

    def add_node(row: dict[str, Any]) -> str:
        nodes[row["node_id"]] = row
        return row["node_id"]

    def course_node(course_id: str) -> str:
        if course_id not in course_nodes:
            course_nodes[course_id] = add_node(_node("Course", course_id, course_id))
        return course_nodes[course_id]

    def chapter_node(course_id: str, chapter_id: str, chapter_path: list[str] | None, first_slide: int | None = None) -> str:
        key = (course_id, chapter_id)
        if first_slide is not None:
            chapter_first_slide[key] = min(first_slide, chapter_first_slide.get(key, first_slide))
        if key not in chapter_nodes:
            chapter_nodes[key] = add_node(_node("Chapter", chapter_id, course_id, chapter_path=chapter_path or []))
            edge = _edge(course_node(course_id), "CONTAINS", chapter_nodes[key], course_id, [], source="courseware_structure")
            edges[edge["edge_id"]] = edge
        return chapter_nodes[key]

    evidence_nodes: dict[str, str] = {}
    for item in sorted(active_evidence.values(), key=lambda row: row["research_evidence_id"]):
        evidence_nodes[item["research_evidence_id"]] = add_node(
            _node("Evidence", item["research_evidence_id"], item["course_id"], citation_key=item["citation_key"], page_or_slide=item["page_or_slide"], block_id=item["block_id"])
        )

    slide_nodes: dict[str, str] = {}
    evidence_to_slides: dict[str, list[str]] = defaultdict(list)
    for slide in sorted(slides_by_id.values(), key=lambda row: row["research_slide_id"]):
        course_id, chapter_id = slide["course_id"], slide["chapter_id"]
        chapter = chapter_node(course_id, chapter_id, slide.get("chapter_path"), slide.get("slide_number"))
        slide_nodes[slide["research_slide_id"]] = add_node(_node("PPTSlide", slide["research_slide_id"], course_id, slide_number=slide["slide_number"], title=slide.get("title", "")))
        contains = _edge(chapter, "CONTAINS", slide_nodes[slide["research_slide_id"]], course_id, slide.get("research_evidence_ids", []), source="courseware_structure")
        edges[contains["edge_id"]] = contains
        for evidence_id in slide.get("research_evidence_ids", []):
            if evidence_id in active_evidence:
                evidence_to_slides[evidence_id].append(slide["research_slide_id"])
        for block_id in slide.get("block_ids", []):
            block = blocks.get(block_id)
            if not block or block.get("course_id") != course_id:
                continue
            script = add_node(_node("ScriptNode", block_id, course_id, block_type=block.get("block_type"), page_or_slide=block.get("page_or_slide")))
            refs = [item for item in slide.get("research_evidence_ids", []) if active_evidence.get(item, {}).get("block_id") == block_id]
            edge = _edge(slide_nodes[slide["research_slide_id"]], "MAPPED_TO", script, course_id, refs, source="slide_block_structure")
            edges[edge["edge_id"]] = edge

    for kp in sorted(knowledge_points, key=lambda row: row["research_knowledge_point_id"]):
        course_id, kp_id = kp["course_id"], kp["research_knowledge_point_id"]
        chapter = chapter_node(course_id, kp["chapter_id"], kp.get("chapter_path"), kp.get("source_page_start"))
        kp_node = add_node(_node("KnowledgePoint", kp_id, course_id, canonical_label=kp["canonical_label"]))
        contains = _edge(chapter, "CONTAINS", kp_node, course_id, kp.get("research_evidence_ids", []), source="knowledge_point_structure")
        edges[contains["edge_id"]] = contains
        for evidence_id in sorted(set(kp.get("research_evidence_ids", []))):
            record = active_evidence.get(evidence_id)
            if not record or record["course_id"] != course_id:
                continue
            grounded = _edge(kp_node, "GROUNDED_BY", evidence_nodes[evidence_id], course_id, [evidence_id], source="knowledge_point_active_evidence")
            edges[grounded["edge_id"]] = grounded
            for slide_id in sorted(evidence_to_slides.get(evidence_id, [])):
                mapped = _edge(kp_node, "MAPPED_TO", slide_nodes[slide_id], course_id, [evidence_id], source="shared_active_evidence")
                edges[mapped["edge_id"]] = mapped

    for course_id in sorted(course_nodes):
        ordered = sorted((key for key in chapter_nodes if key[0] == course_id), key=lambda key: (chapter_first_slide.get(key, 10**9), key[1]))
        for left, right in zip(ordered, ordered[1:]):
            edge = _edge(chapter_nodes[left], "NEXT", chapter_nodes[right], course_id, [], source="first_slide_order")
            edges[edge["edge_id"]] = edge
    return sorted(nodes.values(), key=lambda row: row["node_id"]), sorted(edges.values(), key=lambda row: row["edge_id"])


def validate_snapshot(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], active_evidence_ids: set[str]) -> dict[str, Any]:
    index = {row["node_id"]: row for row in nodes}
    if len(index) != len(nodes):
        raise ValueError("duplicate graph node")
    if len({row["edge_id"] for row in edges}) != len(edges):
        raise ValueError("duplicate graph edge")
    for edge in edges:
        if edge["predicate"] not in ALLOWED_PREDICATES or edge["status"] != "accepted":
            raise ValueError("unsupported graph edge")
        left, right = index.get(edge["subject_node_id"]), index.get(edge["object_node_id"])
        if not left or not right or left["course_id"] != edge["course_id"] or right["course_id"] != edge["course_id"]:
            raise ValueError("cross-course or dangling graph edge")
        if not set(edge.get("research_evidence_ids", [])) <= active_evidence_ids:
            raise ValueError("graph edge references inactive evidence")
    return {"valid": True, "node_count": len(nodes), "edge_count": len(edges)}
