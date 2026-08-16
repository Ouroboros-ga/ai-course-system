"""Educational relationship ontology and validation."""
from __future__ import annotations

from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import time
from enum import Enum

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_CALL_RETRIES = 2
_RETRY_BASE_DELAY_SECONDS = 2.0


class EducationalRelationType(str, Enum):
    PREREQUISITE_OF = "PREREQUISITE_OF"
    PART_OF = "PART_OF"
    EXPLAINS = "EXPLAINS"
    CAUSES = "CAUSES"
    CONTRASTS_WITH = "CONTRASTS_WITH"
    APPLIES_TO = "APPLIES_TO"
    EXAMPLE_OF = "EXAMPLE_OF"
    RELATED_TO = "RELATED_TO"


class RelationshipClassificationError(RuntimeError):
    pass


class _BalanceExhaustedError(RelationshipClassificationError):
    pass


class EducationalRelationshipClassifier:
    """Classify GraphRAG relation descriptions using a versioned policy."""

    policy_version = "edu-graph-graphrag/1.0"
    batch_size = 20
    max_workers = 4

    def classify(
        self,
        entities: list[dict],
        relations: list[dict],
        *,
        relation_profile: list[str] | None = None,
    ) -> list[dict]:
        if not relations:
            return []
        if not settings.GRAPHRAG_COMPLETION_API_BASE:
            raise RelationshipClassificationError("GRAPHRAG_NOT_CONFIGURED")
        if not settings.GRAPHRAG_COMPLETION_API_KEY:
            raise RelationshipClassificationError("GRAPHRAG_NOT_CONFIGURED")
        if not settings.GRAPHRAG_COMPLETION_MODEL:
            raise RelationshipClassificationError("GRAPHRAG_NOT_CONFIGURED")
        entity_by_id = {
            str(entity.get("id")): {
                "id": str(entity.get("id")),
                "title": entity.get("title"),
                "type": entity.get("type"),
                "description": entity.get("description"),
            }
            for entity in entities
        }
        allowed_types = _allowed_relation_types(relation_profile)
        batches = [
            (offset, relations[offset:offset + self.batch_size])
            for offset in range(0, len(relations), self.batch_size)
        ]
        classified_batches: dict[int, list[dict]] = {}
        failed_batches: list[int] = []
        with ThreadPoolExecutor(
            max_workers=min(self.max_workers, len(batches)),
            thread_name_prefix="graph-relation-classifier",
        ) as executor:
            future_offsets = {
                executor.submit(
                    self._classify_batch,
                    offset,
                    batch,
                    entity_by_id,
                    allowed_types,
                ): offset
                for offset, batch in batches
            }
            for future in as_completed(future_offsets):
                offset = future_offsets[future]
                try:
                    classified_batches[offset] = future.result()
                except _BalanceExhaustedError:
                    for f in future_offsets:
                        f.cancel()
                    raise
                except Exception:
                    log.exception("Relation classification batch %d failed", offset)
                    failed_batches.append(offset)
        if failed_batches and not classified_batches:
            raise RelationshipClassificationError("RELATION_CLASSIFICATION_FAILED")
        output: list[dict] = []
        for offset, batch in batches:
            if offset in classified_batches:
                output.extend(classified_batches[offset])
            else:
                for relation in batch:
                    output.append(normalize_typed_relation({
                        **relation,
                        "type": EducationalRelationType.RELATED_TO.value,
                        "confidence": 0.0,
                        "reason": "分类批次失败，降级为 RELATED_TO",
                    }))
        validate_prerequisite_dag(output)
        return output

    def _classify_batch(
        self,
        offset: int,
        batch: list[dict],
        entity_by_id: dict[str, dict],
        allowed_types: set[str],
    ) -> list[dict]:
        payload = []
        for relation in batch:
            source = str(relation.get("source") or "")
            target = str(relation.get("target") or "")
            payload.append({
                "id": str(relation.get("id") or f"rel_{offset + len(payload)}"),
                "source": entity_by_id.get(source, {"id": source}),
                "target": entity_by_id.get(target, {"id": target}),
                "description": relation.get("description") or "",
                "text_unit_ids": list(relation.get("text_unit_ids") or []),
            })
        classified = self._call(payload, allowed_types=allowed_types)
        by_id = {str(item.get("id")): item for item in classified}
        output: list[dict] = []
        for original, request_row in zip(batch, payload):
            decision = by_id.get(request_row["id"])
            if decision is None:
                normalized = normalize_typed_relation({
                    **original,
                    "type": EducationalRelationType.RELATED_TO.value,
                    "confidence": 0.0,
                    "reason": "LLM 未返回该关系的分类结果，降级为 RELATED_TO",
                    "source": original.get("source"),
                    "target": original.get("target"),
                    "text_unit_ids": original.get("text_unit_ids") or [],
                })
                output.append(normalized)
                continue
            normalized = normalize_typed_relation({
                **original,
                **decision,
                "source": original.get("source"),
                "target": original.get("target"),
                "text_unit_ids": original.get("text_unit_ids") or [],
            })
            if normalized["type"] not in allowed_types:
                normalized["type"] = EducationalRelationType.RELATED_TO.value
                normalized["reason"] = (
                    "原分类不在本次关系策略内；降级为 RELATED_TO。"
                    f"{normalized['reason']}"
                )
            output.append(normalized)
        return output

    def _call(self, rows: list[dict], *, allowed_types: set[str]) -> list[dict]:
        endpoint = settings.GRAPHRAG_COMPLETION_API_BASE.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint += "/chat/completions"
        allowed_text = "、".join(sorted(allowed_types))
        system = (
            "你是教育知识图谱关系分类器。只根据提供的实体描述、关系描述和来源标识分类，"
            "不得按章节顺序猜测先修关系。允许类型仅为 PREREQUISITE_OF、PART_OF、"
            "EXPLAINS、CAUSES、CONTRASTS_WITH、APPLIES_TO、EXAMPLE_OF、RELATED_TO。"
            "无法判断方向时必须用 RELATED_TO。返回 JSON 对象 {\"relations\":[...]};"
            f"本次允许的关系类型仅为：{allowed_text}。"
            "每项保留 id，并给出 type、confidence(0..1)、reason。"
        )
        for attempt in range(1 + _MAX_CALL_RETRIES):
            try:
                response = httpx.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {settings.GRAPHRAG_COMPLETION_API_KEY}",
                    },
                    json={
                        "model": settings.GRAPHRAG_COMPLETION_MODEL,
                        "temperature": 0,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": json.dumps(rows, ensure_ascii=False)},
                        ],
                    },
                    timeout=min(float(settings.GRAPHRAG_RUN_TIMEOUT_SECONDS), 300.0),
                )
            except httpx.HTTPError as exc:
                if attempt < _MAX_CALL_RETRIES:
                    time.sleep(_RETRY_BASE_DELAY_SECONDS * (2 ** attempt))
                    continue
                raise RelationshipClassificationError(
                    f"GRAPHRAG_PROVIDER_UNAVAILABLE:{type(exc).__name__}"
                ) from exc
            if response.status_code == 402 or _is_balance_error_response(response):
                raise _BalanceExhaustedError(
                    "LLM_BUDGET_EXCEEDED:insufficient_balance"
                )
            if response.status_code in _RETRYABLE_STATUS_CODES and attempt < _MAX_CALL_RETRIES:
                time.sleep(_RETRY_BASE_DELAY_SECONDS * (2 ** attempt))
                continue
            if response.status_code >= 400:
                raise RelationshipClassificationError(
                    f"GRAPHRAG_PROVIDER_UNAVAILABLE:{response.status_code}"
                )
            try:
                content = response.json()["choices"][0]["message"]["content"]
                result = json.loads(content)
                rows = result.get("relations")
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                raise RelationshipClassificationError(
                    "RELATION_CLASSIFICATION_FAILED"
                ) from exc
            if not isinstance(rows, list):
                raise RelationshipClassificationError("RELATION_CLASSIFICATION_FAILED")
            return rows
        raise RelationshipClassificationError(
            f"GRAPHRAG_PROVIDER_UNAVAILABLE:retries_exhausted"
        )


def _is_balance_error_response(response: httpx.Response) -> bool:
    text = response.text[:500].lower()
    return any(kw in text for kw in ("insufficient", "balance", "quota", "credit"))


def normalize_typed_relation(relation: dict) -> dict:
    """Validate a classifier result without inventing educational semantics."""
    normalized = dict(relation)
    raw_type = str(normalized.get("type") or normalized.get("relation_type") or "")
    try:
        relation_type = EducationalRelationType(raw_type.upper())
    except ValueError:
        relation_type = EducationalRelationType.RELATED_TO
    normalized["type"] = relation_type.value
    normalized["source"] = str(normalized.get("source") or "")
    normalized["target"] = str(normalized.get("target") or "")
    normalized["confidence"] = max(0.0, min(1.0, float(normalized.get("confidence") or 0.0)))
    normalized["reason"] = str(
        normalized.get("reason") or normalized.get("description") or ""
    )
    normalized["text_unit_ids"] = list(normalized.get("text_unit_ids") or [])
    return normalized


def _allowed_relation_types(relation_profile: list[str] | None) -> set[str]:
    if not relation_profile:
        return {item.value for item in EducationalRelationType}
    allowed = {
        item.value
        for raw in relation_profile
        for item in EducationalRelationType
        if item.value == str(raw).upper()
    }
    allowed.add(EducationalRelationType.RELATED_TO.value)
    return allowed


def validate_prerequisite_dag(relations: list[dict]) -> None:
    adjacency: dict[str, set[str]] = defaultdict(set)
    indegree: dict[str, int] = defaultdict(int)
    nodes: set[str] = set()
    for relation in relations:
        if relation.get("type") != EducationalRelationType.PREREQUISITE_OF.value:
            continue
        source, target = relation.get("source"), relation.get("target")
        if not source or not target or source == target:
            raise ValueError("PREREQUISITE_GRAPH_INVALID")
        nodes.update((source, target))
        if target not in adjacency[source]:
            adjacency[source].add(target)
            indegree[target] += 1
            indegree.setdefault(source, 0)
    queue = deque(node for node in nodes if indegree[node] == 0)
    visited = 0
    while queue:
        source = queue.popleft()
        visited += 1
        for target in adjacency[source]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if visited != len(nodes):
        raise ValueError("PREREQUISITE_GRAPH_CYCLE")
