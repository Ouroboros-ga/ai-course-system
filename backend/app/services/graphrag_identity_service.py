"""Reconcile ephemeral GraphRAG entities with stable course ``kn_*`` nodes."""
from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass

from sqlmodel import Session, select

from app.models.graph_production_model import (
    CourseKnowledgeNode,
    CourseKnowledgeNodeStatus,
)
from app.models.knowledge_bundle_model import GraphRagEntityMapping
from app.platform.knowledge.document_ir_exporter import GraphRagInputManifest
from app.platform.knowledge.graphrag_runner import GraphRagArtifacts


class IdentityAmbiguousError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReconciledGraph:
    nodes: tuple[dict, ...]
    relations: tuple[dict, ...]
    quality_report: dict


class GraphRagIdentityService:
    def reconcile(
        self,
        session: Session,
        *,
        course_id: int,
        graphrag_run_id: str,
        manifest: GraphRagInputManifest,
        artifacts: GraphRagArtifacts,
    ) -> ReconciledGraph:
        existing_mappings = {
            mapping.graphrag_entity_id: mapping
            for mapping in session.exec(select(GraphRagEntityMapping).where(
                GraphRagEntityMapping.course_id == course_id,
                GraphRagEntityMapping.graphrag_run_id == graphrag_run_id,
            )).all()
        }
        nodes = list(session.exec(select(CourseKnowledgeNode).where(
            CourseKnowledgeNode.course_id == course_id,
        )).all())
        source_lookup = _source_lookup(manifest, artifacts)
        entity_to_node: dict[str, CourseKnowledgeNode] = {}
        rejected_entity_ids: set[str] = set()
        rejected_entity_titles: list[str] = []
        mapping_method_counts: dict[str, int] = {}
        snapshot_nodes_by_key: dict[str, dict] = {}

        for entity in artifacts.entities:
            entity_id = str(entity.get("id") or "")
            if not entity_id:
                raise ValueError("GRAPH_OUTPUT_INVALID")
            if _is_placeholder_entity(entity):
                rejected_entity_ids.add(entity_id)
                rejected_entity_titles.append(str(entity.get("title") or ""))
                continue
            canonical_title, entity_aliases = _entity_names(entity)
            anchor_ids = sorted({
                anchor_id
                for text_unit_id in entity.get("text_unit_ids") or []
                for anchor_id in source_lookup.get(str(text_unit_id), ())
            })
            mapping = existing_mappings.get(entity_id)
            node = None
            method = "existing_run"
            score = 1.0
            warnings: list[str] = []
            if mapping is not None:
                node = session.get(CourseKnowledgeNode, mapping.knowledge_node_id)
                if node is None or node.course_id != course_id:
                    raise ValueError("IDENTITY_MAPPING_INVALID")
            else:
                node, method, score = self._match(
                    nodes,
                    title=canonical_title,
                    aliases=entity_aliases,
                    entity_type=str(entity.get("type") or "concept"),
                    anchor_ids=set(anchor_ids),
                )
                if node is None:
                    node = CourseKnowledgeNode(
                        course_id=course_id,
                        node_key=f"kn_{uuid.uuid4().hex}",
                        title=canonical_title,
                        kind=str(entity.get("type") or "concept").lower(),
                        status=CourseKnowledgeNodeStatus.CANDIDATE,
                        source_anchor_ids=anchor_ids,
                        extra_data={
                            "description": str(entity.get("description") or ""),
                            "aliases": entity_aliases,
                            "identity_origin": "graphrag",
                        },
                    )
                    session.add(node)
                    session.flush()
                    nodes.append(node)
                    method = "new_identity"
                    score = 1.0
                fingerprint = _fingerprint(
                    canonical_title,
                    str(entity.get("type") or "concept"),
                    anchor_ids,
                )
                mapping = GraphRagEntityMapping(
                    course_id=course_id,
                    graphrag_run_id=graphrag_run_id,
                    graphrag_entity_id=entity_id,
                    entity_title=str(entity.get("title") or ""),
                    entity_type=str(entity.get("type") or "concept"),
                    entity_fingerprint=fingerprint,
                    knowledge_node_id=int(node.id),
                    node_key=node.node_key,
                    mapping_method=method,
                    mapping_score=score,
                    source_text_unit_ids=list(entity.get("text_unit_ids") or []),
                    source_anchor_ids=anchor_ids,
                    warnings=warnings,
                )
                session.add(mapping)
            mapping_method_counts[mapping.mapping_method] = (
                mapping_method_counts.get(mapping.mapping_method, 0) + 1
            )
            entity_to_node[entity_id] = node
            snapshot_node = snapshot_nodes_by_key.get(node.node_key)
            if snapshot_node is None:
                snapshot_node = {
                    "id": node.node_key,
                    "identity_id": node.id,
                    "title": canonical_title or node.title,
                    "label": canonical_title or node.title,
                    "aliases": entity_aliases,
                    "type": str(entity.get("type") or node.kind).lower(),
                    "description": str(entity.get("description") or ""),
                    "source_anchor_ids": [],
                    "source_text_unit_ids": [],
                    "graphrag_entity_fingerprints": [],
                }
                snapshot_nodes_by_key[node.node_key] = snapshot_node
            snapshot_node["source_anchor_ids"] = sorted({
                *snapshot_node["source_anchor_ids"],
                *anchor_ids,
            })
            snapshot_node["source_text_unit_ids"] = sorted({
                *snapshot_node["source_text_unit_ids"],
                *[str(item) for item in entity.get("text_unit_ids") or []],
            })
            snapshot_node["graphrag_entity_fingerprints"] = sorted({
                *snapshot_node["graphrag_entity_fingerprints"],
                mapping.entity_fingerprint,
            })
            description = str(entity.get("description") or "").strip()
            if len(description) > len(snapshot_node["description"]):
                snapshot_node["description"] = description

        snapshot_relations_by_key: dict[tuple[str, str, str], dict] = {}
        placeholder_relation_count = 0
        self_loop_count = 0
        duplicate_relation_count = 0
        for relation in artifacts.relationships:
            source_id = str(relation.get("source") or "")
            target_id = str(relation.get("target") or "")
            if source_id in rejected_entity_ids or target_id in rejected_entity_ids:
                placeholder_relation_count += 1
                continue
            source = entity_to_node.get(source_id)
            target = entity_to_node.get(target_id)
            if source is None or target is None:
                raise ValueError("GRAPH_OUTPUT_INVALID")
            text_unit_ids = [str(item) for item in relation.get("text_unit_ids") or []]
            anchor_ids = sorted({
                anchor_id
                for text_unit_id in text_unit_ids
                for anchor_id in source_lookup.get(text_unit_id, ())
            })
            relation_type = str(relation.get("type") or "RELATED_TO")
            if source.node_key == target.node_key:
                self_loop_count += 1
                continue
            relation_key = (source.node_key, target.node_key, relation_type)
            snapshot_relation = snapshot_relations_by_key.get(relation_key)
            if snapshot_relation is None:
                snapshot_relation = {
                "id": f"kr_{hashlib.sha256((source.node_key + '|' + target.node_key + '|' + str(relation.get('type')) + '|' + '|'.join(anchor_ids)).encode('utf-8')).hexdigest()[:24]}",
                "source": source.node_key,
                "target": target.node_key,
                "type": relation_type,
                "description": str(relation.get("description") or relation.get("reason") or ""),
                "reason": str(relation.get("reason") or ""),
                "confidence": float(relation.get("confidence") or 0.0),
                "weight": float(relation.get("weight") or 0.0),
                "source_anchor_ids": [],
                "source_text_unit_ids": [],
                }
                snapshot_relations_by_key[relation_key] = snapshot_relation
            else:
                duplicate_relation_count += 1
            snapshot_relation["source_anchor_ids"] = sorted({
                *snapshot_relation["source_anchor_ids"],
                *anchor_ids,
            })
            snapshot_relation["source_text_unit_ids"] = sorted({
                *snapshot_relation["source_text_unit_ids"],
                *text_unit_ids,
            })
            snapshot_relation["confidence"] = max(
                snapshot_relation["confidence"],
                float(relation.get("confidence") or 0.0),
            )
            snapshot_relation["weight"] += float(relation.get("weight") or 0.0)
        return ReconciledGraph(
            tuple(snapshot_nodes_by_key.values()),
            tuple(snapshot_relations_by_key.values()),
            {
                "identity_policy": "strict-title-anchor/1.0",
                "source_entity_count": len(artifacts.entities),
                "accepted_entity_count": len(entity_to_node),
                "snapshot_node_count": len(snapshot_nodes_by_key),
                "mapping_method_counts": mapping_method_counts,
                "rejected_placeholder_count": len(rejected_entity_ids),
                "rejected_placeholder_titles": sorted(set(rejected_entity_titles)),
                "source_relationship_count": len(artifacts.relationships),
                "snapshot_relationship_count": len(snapshot_relations_by_key),
                "removed_placeholder_relationship_count": placeholder_relation_count,
                "removed_self_loop_count": self_loop_count,
                "deduplicated_relationship_count": duplicate_relation_count,
            },
        )

    @staticmethod
    def _match(
        nodes: list[CourseKnowledgeNode],
        *,
        title: str,
        aliases: list[str] | None = None,
        entity_type: str,
        anchor_ids: set[str],
    ) -> tuple[CourseKnowledgeNode | None, str, float]:
        aliases = aliases or []
        incoming_names = {
            normalized
            for value in (title, *aliases)
            if (normalized := _normalize_title(value))
        }
        candidates: list[tuple[float, str, CourseKnowledgeNode]] = []
        for node in nodes:
            node_anchors = set(node.source_anchor_ids or [])
            overlap = (
                len(anchor_ids & node_anchors) / max(1, len(anchor_ids | node_anchors))
                if anchor_ids and node_anchors else 0.0
            )
            node_title = _normalize_title(node.title)
            node_aliases = {
                _normalize_title(str(alias))
                for alias in (node.extra_data or {}).get("aliases", [])
            }
            same_type = str(node.kind).lower() == entity_type.lower()
            if node_title in incoming_names and overlap > 0:
                candidates.append((0.98 + min(overlap, 0.02), "exact_title_anchor", node))
            elif incoming_names & node_aliases and same_type and overlap > 0:
                candidates.append((0.92 + min(overlap, 0.05), "alias_anchor", node))
        candidates.sort(key=lambda item: (-item[0], item[2].node_key))
        if not candidates:
            return None, "new_identity", 0.0
        if len(candidates) > 1 and candidates[0][0] - candidates[1][0] < 0.05:
            raise IdentityAmbiguousError("IDENTITY_AMBIGUOUS")
        score, method, node = candidates[0]
        return node, method, score


def _source_lookup(
    manifest: GraphRagInputManifest,
    artifacts: GraphRagArtifacts,
) -> dict[str, tuple[str, ...]]:
    anchors_by_source = {
        document.source_key: document.anchor_ids
        for document in manifest.documents
    }
    source_by_document_id: dict[str, str] = {}
    for document in artifacts.documents:
        title = str(document.get("title") or "")
        source_key = title[3:] if title.startswith("rc:") else title
        if source_key not in anchors_by_source and f"rc_{source_key}" in anchors_by_source:
            source_key = f"rc_{source_key}"
        source_by_document_id[str(document.get("id"))] = source_key
    lookup: dict[str, tuple[str, ...]] = {}
    for text_unit in artifacts.text_units:
        document_ids = list(text_unit.get("document_ids") or [])
        if text_unit.get("document_id"):
            document_ids.append(text_unit.get("document_id"))
        anchor_ids = {
            anchor_id
            for document_id in document_ids
            for anchor_id in anchors_by_source.get(
                source_by_document_id.get(str(document_id), ""), ()
            )
        }
        lookup[str(text_unit.get("id"))] = tuple(sorted(anchor_ids))
    return lookup


def _normalize_title(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold(), flags=re.UNICODE)


def _entity_names(entity: dict) -> tuple[str, list[str]]:
    """Split a Chinese canonical title from trailing English terminology aliases."""
    raw_title = str(entity.get("title") or "").strip()
    aliases = [str(item).strip() for item in entity.get("aliases") or [] if str(item).strip()]
    match = re.fullmatch(r"(.+?)[（(]([^()（）]+)[）)]", raw_title)
    if match and re.search(r"[\u4e00-\u9fff]", match.group(1)) and re.search(r"[A-Za-z]", match.group(2)):
        canonical_title = match.group(1).strip()
        aliases.extend(part.strip() for part in re.split(r"[/,，;；]", match.group(2)) if part.strip())
    else:
        canonical_title = raw_title
    return canonical_title, list(dict.fromkeys(aliases))


def _is_placeholder_entity(entity: dict) -> bool:
    normalized = _normalize_title(str(entity.get("title") or ""))
    if normalized in {
        "none",
        "noentities",
        "noentitiesfound",
        "noentityfound",
        "imagecontentunavailable",
        "unknownentity",
    }:
        return True
    return bool(re.fullmatch(r"image\d+(?:jpe?g|png|gif|bmp|webp|svg)?", normalized))


def _fingerprint(title: str, entity_type: str, anchor_ids: list[str]) -> str:
    payload = "|".join((_normalize_title(title), entity_type.lower(), *sorted(anchor_ids)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
