"""Immutable, course-isolated LanceDB indexes for knowledge bundles."""
from __future__ import annotations

import gc
import hashlib
import json
import math
import shutil
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.platform.knowledge.embedding import EmbeddingProvider

TABLE_TEXT_UNITS = "text_unit_embeddings"
TABLE_ENTITIES = "entity_embeddings"
TABLE_EVIDENCE = "evidence_embeddings"
REQUIRED_TABLES = (TABLE_TEXT_UNITS, TABLE_ENTITIES, TABLE_EVIDENCE)


class VectorIndexError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = message.split(":", 1)[0]


@dataclass(frozen=True)
class VectorBuildResult:
    storage_uri: str
    manifest_uri: str
    manifest_hash: str
    vector_dimension: int
    text_unit_row_count: int
    entity_row_count: int
    evidence_row_count: int


def _load_lancedb():
    try:
        import lancedb
    except ImportError as exc:  # pragma: no cover - deployment configuration
        raise VectorIndexError("VECTOR_STORE_UNAVAILABLE") from exc
    return lancedb


class LanceDbCourseVectorProvider:
    """Build and query one immutable database directory per Bundle."""

    schema_version = "course-lancedb/1.0"

    def __init__(
        self,
        *,
        root: str | Path | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.root = Path(root or settings.VECTOR_STORE_ROOT).resolve()
        self.embedding_provider = embedding_provider

    def bundle_dir(self, *, course_id: int, bundle_id: str) -> Path:
        if course_id <= 0 or not bundle_id.startswith("ckb_"):
            raise VectorIndexError("INVALID_BUNDLE_SCOPE")
        target = (self.root / "courses" / str(course_id) / "bundles" / bundle_id).resolve()
        if self.root != target and self.root not in target.parents:
            raise VectorIndexError("INVALID_VECTOR_STORAGE_PATH")
        return target

    def build(
        self,
        *,
        course_id: int,
        bundle_id: str,
        graph_snapshot_id: str,
        text_units: Sequence[dict],
        entities: Sequence[dict],
        evidence: Sequence[dict],
    ) -> VectorBuildResult:
        final_dir = self.bundle_dir(course_id=course_id, bundle_id=bundle_id)
        complete_path = final_dir / "COMPLETE"
        manifest_path = final_dir / "manifest.json"
        if complete_path.is_file() and manifest_path.is_file():
            return self.validate(course_id=course_id, bundle_id=bundle_id)
        if not text_units or not entities or not evidence:
            raise VectorIndexError("VECTOR_INPUT_EMPTY")
        if self.embedding_provider is None:
            raise VectorIndexError("GRAPHRAG_NOT_CONFIGURED")

        staging_dir = final_dir / "staging"
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        staging_dir.mkdir(parents=True, exist_ok=False)
        database_dir = staging_dir / "lancedb"

        text_rows = self._embed_rows(
            text_units,
            required=("id", "text", "retrieval_chunk_id", "document_id"),
            course_id=course_id,
            bundle_id=bundle_id,
            graph_snapshot_id=graph_snapshot_id,
        )
        entity_rows = self._embed_rows(
            entities,
            required=("id", "text", "node_key", "knowledge_node_id"),
            course_id=course_id,
            bundle_id=bundle_id,
            graph_snapshot_id=graph_snapshot_id,
        )
        evidence_rows = self._embed_rows(
            evidence,
            required=("id", "text", "citation_id", "document_id"),
            course_id=course_id,
            bundle_id=bundle_id,
            graph_snapshot_id=graph_snapshot_id,
        )
        all_rows = text_rows + entity_rows + evidence_rows
        if not all_rows:
            raise VectorIndexError("VECTOR_INPUT_EMPTY")
        dimensions = {len(row["vector"]) for row in all_rows}
        if len(dimensions) != 1 or 0 in dimensions:
            raise VectorIndexError("VECTOR_DIMENSION_MISMATCH")
        dimension = next(iter(dimensions))

        lancedb = _load_lancedb()
        database = lancedb.connect(str(database_dir))
        database.create_table(TABLE_TEXT_UNITS, data=text_rows, mode="overwrite")
        database.create_table(TABLE_ENTITIES, data=entity_rows, mode="overwrite")
        database.create_table(TABLE_EVIDENCE, data=evidence_rows, mode="overwrite")

        manifest = {
            "schema_version": self.schema_version,
            "course_id": course_id,
            "bundle_id": bundle_id,
            "graph_snapshot_id": graph_snapshot_id,
            "embedding_provider": self.embedding_provider.provider_name,
            "embedding_model": self.embedding_provider.model_name,
            "vector_dimension": dimension,
            "tables": {
                TABLE_TEXT_UNITS: len(text_rows),
                TABLE_ENTITIES: len(entity_rows),
                TABLE_EVIDENCE: len(evidence_rows),
            },
            "content_hash": _rows_hash(all_rows),
        }
        manifest_bytes = json.dumps(
            manifest, ensure_ascii=False, sort_keys=True, indent=2
        ).encode("utf-8")
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        manifest["manifest_hash"] = manifest_hash
        (staging_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )

        # Publish immutable files first; activation remains a separate SQL CAS.
        final_database_dir = final_dir / "lancedb"
        if final_database_dir.exists():
            shutil.rmtree(final_database_dir)
        # Windows: LanceDB 连接持有底层文件句柄，目录 rename 前必须显式释放
        # （lancedb 0.34 无 close()，依赖引用计数 + gc 关闭 pyarrow/rust 句柄）。
        del database
        gc.collect()
        staging_dir.replace(final_dir / "_ready")
        ready_dir = final_dir / "_ready"
        (ready_dir / "lancedb").replace(final_database_dir)
        (ready_dir / "manifest.json").replace(manifest_path)
        ready_dir.rmdir()
        complete_path.write_text(manifest_hash, encoding="ascii")
        return self.validate(course_id=course_id, bundle_id=bundle_id)

    def validate(self, *, course_id: int, bundle_id: str) -> VectorBuildResult:
        bundle_dir = self.bundle_dir(course_id=course_id, bundle_id=bundle_id)
        manifest_path = bundle_dir / "manifest.json"
        complete_path = bundle_dir / "COMPLETE"
        database_path = bundle_dir / "lancedb"
        if not manifest_path.is_file() or not complete_path.is_file() or not database_path.is_dir():
            raise VectorIndexError("INDEX_MANIFEST_MISMATCH")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_hash = str(manifest.pop("manifest_hash", ""))
        calculated = hashlib.sha256(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        ).hexdigest()
        if manifest_hash != calculated or complete_path.read_text(encoding="ascii").strip() != calculated:
            raise VectorIndexError("INDEX_MANIFEST_MISMATCH")
        if manifest.get("course_id") != course_id or manifest.get("bundle_id") != bundle_id:
            raise VectorIndexError("INDEX_COURSE_SCOPE_MISMATCH")

        database = _load_lancedb().connect(str(database_path))
        table_names = set(database.list_tables().tables)
        if not set(REQUIRED_TABLES).issubset(table_names):
            raise VectorIndexError("INDEX_MANIFEST_MISMATCH")
        expected = manifest.get("tables") or {}
        actual = {
            name: database.open_table(name).count_rows()
            for name in REQUIRED_TABLES
        }
        if any(actual[name] != int(expected.get(name, -1)) for name in REQUIRED_TABLES):
            raise VectorIndexError("INDEX_MANIFEST_MISMATCH")
        dimension = int(manifest.get("vector_dimension") or 0)
        if dimension <= 0:
            raise VectorIndexError("VECTOR_DIMENSION_MISMATCH")
        return VectorBuildResult(
            storage_uri=str(database_path),
            manifest_uri=str(manifest_path),
            manifest_hash=calculated,
            vector_dimension=dimension,
            text_unit_row_count=actual[TABLE_TEXT_UNITS],
            entity_row_count=actual[TABLE_ENTITIES],
            evidence_row_count=actual[TABLE_EVIDENCE],
        )

    def search(
        self,
        *,
        course_id: int,
        bundle_id: str,
        query: str,
        top_k: int,
        node_keys: Iterable[str] = (),
    ) -> list[dict]:
        if not query.strip():
            return []
        if self.embedding_provider is None:
            raise VectorIndexError("GRAPHRAG_NOT_CONFIGURED")
        validated = self.validate(course_id=course_id, bundle_id=bundle_id)
        query_vector = self.embedding_provider.embed([query])[0]
        if len(query_vector) != validated.vector_dimension:
            raise VectorIndexError("VECTOR_DIMENSION_MISMATCH")
        database = _load_lancedb().connect(validated.storage_uri)
        permitted_nodes = set(node_keys)
        rankings: list[list[dict]] = []
        for table_name, source in (
            (TABLE_TEXT_UNITS, "dense_text"),
            (TABLE_ENTITIES, "dense_entity"),
            (TABLE_EVIDENCE, "dense_evidence"),
        ):
            table = database.open_table(table_name)
            rows = (
                table.search(query_vector)
                .where(
                    f"course_id = {int(course_id)} AND bundle_id = '{_sql_literal(bundle_id)}'",
                    prefilter=True,
                )
                .limit(max(top_k * 3, 10))
                .to_list()
            )
            normalized: list[dict] = []
            for row in rows:
                row_node_key = row.get("node_key") or None
                if permitted_nodes and row_node_key not in permitted_nodes:
                    continue
                citation_ids = _string_list(row.get("citation_ids"))
                if row.get("citation_id"):
                    citation_ids.append(str(row["citation_id"]))
                # Citation closure is a hard learner-facing invariant.
                citation_ids = list(dict.fromkeys(item for item in citation_ids if item))
                if not citation_ids:
                    continue
                normalized.append({
                    **row,
                    "citation_ids": citation_ids,
                    "retrieval_source": source,
                })
            rankings.append(normalized)
        return _rrf(rankings, top_k=top_k)

    def _embed_rows(
        self,
        rows: Sequence[dict],
        *,
        required: tuple[str, ...],
        course_id: int,
        bundle_id: str,
        graph_snapshot_id: str,
    ) -> list[dict]:
        if not rows:
            return []
        if self.embedding_provider is None:
            raise VectorIndexError("GRAPHRAG_NOT_CONFIGURED")
        normalized: list[dict] = []
        for source in rows:
            missing = [field for field in required if source.get(field) in (None, "")]
            if missing:
                raise VectorIndexError(f"VECTOR_ROW_INVALID:{','.join(missing)}")
            row = dict(source)
            row.update({
                "course_id": course_id,
                "bundle_id": bundle_id,
                "graph_snapshot_id": graph_snapshot_id,
            })
            row.setdefault("node_key", "")
            row.setdefault("knowledge_node_id", 0)
            row.setdefault("evidence_ids", [])
            row.setdefault("citation_ids", [])
            row.setdefault("citation_id", "")
            row.setdefault("retrieval_chunk_id", "")
            row.setdefault("text_unit_id", "")
            row.setdefault("document_id", "")
            row.setdefault("page_number", 0)
            row.setdefault("content_hash", "")
            row.setdefault("student_visible", True)
            normalized.append(row)
        vectors = self.embedding_provider.embed([str(row["text"]) for row in normalized])
        for row, vector in zip(normalized, vectors):
            if not vector or any(not math.isfinite(float(value)) for value in vector):
                raise VectorIndexError("VECTOR_DIMENSION_MISMATCH")
            row["vector"] = [float(value) for value in vector]
        return normalized


def _rows_hash(rows: Sequence[dict]) -> str:
    stable = [
        {
            key: value
            for key, value in row.items()
            if key != "vector"
        }
        for row in sorted(rows, key=lambda item: (str(item.get("id")), str(item.get("text"))))
    ]
    return hashlib.sha256(
        json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _rrf(rankings: Sequence[Sequence[dict]], *, top_k: int) -> list[dict]:
    scores: dict[str, float] = {}
    merged: dict[str, dict] = {}
    sources: dict[str, set[str]] = {}
    for ranking in rankings:
        for rank, row in enumerate(ranking, start=1):
            key = str(row.get("id") or f"{row.get('document_id')}:{row.get('text')}")
            scores[key] = scores.get(key, 0.0) + 1.0 / (60 + rank)
            merged.setdefault(key, row)
            sources.setdefault(key, set()).add(str(row["retrieval_source"]))
    ordered = sorted(scores, key=lambda key: (-scores[key], key))
    result = []
    for key in ordered[:top_k]:
        row = dict(merged[key])
        row["score"] = scores[key]
        row["retrieval_sources"] = sorted(sources[key])
        result.append(row)
    return result


def _sql_literal(value: str) -> str:
    return value.replace("'", "''")


def _string_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            return [value]
    return [str(item) for item in value]
