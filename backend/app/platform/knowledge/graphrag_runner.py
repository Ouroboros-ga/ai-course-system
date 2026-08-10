"""GraphRAG 3.x adapter over canonical DocumentIR DataFrames."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.config import settings
from app.platform.knowledge.document_ir_exporter import GraphRagInputManifest
from app.platform.knowledge.relationship_classifier import (
    EducationalRelationshipClassifier,
)


class GraphRagRunError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = message.split(":", 1)[0]


@dataclass(frozen=True)
class GraphRagArtifacts:
    entities: tuple[dict, ...]
    relationships: tuple[dict, ...]
    text_units: tuple[dict, ...]
    documents: tuple[dict, ...]
    output_manifest_uri: str
    output_content_hash: str
    warnings: tuple[dict, ...]
    estimated_input_tokens: int
    estimated_max_cost: float


class GraphRagRunner:
    """Run GraphRAG in a task worker, never in a request handler."""

    required_outputs = ("documents", "text_units", "entities", "relationships")

    def __init__(self, classifier: EducationalRelationshipClassifier | None = None) -> None:
        self.classifier = classifier or EducationalRelationshipClassifier()

    def run(
        self,
        *,
        manifest: GraphRagInputManifest,
        artifact_root: Path,
        policy_context: dict[str, Any] | None = None,
        allow_isolated_worker: bool = True,
    ) -> GraphRagArtifacts:
        if not settings.GRAPHRAG_ENABLED:
            raise GraphRagRunError("GRAPHRAG_NOT_CONFIGURED")
        self._validate_model_configuration()
        if (
            settings.GRAPHRAG_WORKER_PYTHON
            and allow_isolated_worker
            and os.environ.get("AI_COURSE_GRAPHRAG_IN_WORKER") != "1"
        ):
            return self._run_isolated_worker(
                manifest=manifest,
                artifact_root=artifact_root,
                policy_context=policy_context,
            )
        artifact_root.mkdir(parents=True, exist_ok=True)
        output_dir = artifact_root / "output"
        reports_dir = artifact_root / "reports"
        cache_dir = artifact_root / "cache"
        vector_dir = artifact_root / "graphrag-vectors"
        for directory in (output_dir, reports_dir, cache_dir, vector_dir):
            directory.mkdir(parents=True, exist_ok=True)

        frame = pd.DataFrame([
            {
                "id": document.source_key,
                "title": document.title,
                "text": document.text,
            }
            for document in manifest.documents
        ])
        estimated_tokens = _estimate_tokens([document.text for document in manifest.documents])
        estimated_cost = (
            estimated_tokens / 1_000_000
        ) * settings.GRAPHRAG_ESTIMATED_INPUT_COST_USD_PER_MILLION_TOKENS
        max_estimated_cost_usd = (
            settings.GRAPHRAG_MAX_ESTIMATED_COST_USD
            if settings.GRAPHRAG_MAX_ESTIMATED_COST_USD > 0
            else settings.GRAPHRAG_MAX_ESTIMATED_COST
        )
        if (
            settings.GRAPHRAG_MAX_INPUT_TOKENS > 0
            and estimated_tokens > settings.GRAPHRAG_MAX_INPUT_TOKENS
        ):
            raise GraphRagRunError("LLM_BUDGET_EXCEEDED")
        if (
            max_estimated_cost_usd > 0
            and estimated_cost > max_estimated_cost_usd
        ):
            raise GraphRagRunError("LLM_BUDGET_EXCEEDED")
        outputs = self._load_complete_outputs(output_dir, manifest=manifest)
        if outputs is None:
            config = self._make_config(
                artifact_root=artifact_root,
                output_dir=output_dir,
                reports_dir=reports_dir,
                cache_dir=cache_dir,
                vector_dir=vector_dir,
                policy_context=policy_context,
            )
            try:
                from graphrag.api import build_index

                results = asyncio.run(asyncio.wait_for(
                    build_index(
                        config=config,
                        method="standard",
                        input_documents=frame,
                        verbose=False,
                        additional_context={
                            "course_id": manifest.course_id,
                            "input_content_hash": manifest.input_content_hash,
                        },
                    ),
                    timeout=float(settings.GRAPHRAG_RUN_TIMEOUT_SECONDS),
                ))
            except TimeoutError as exc:
                raise GraphRagRunError("GRAPHRAG_RUN_TIMEOUT") from exc
            except Exception as exc:
                raise GraphRagRunError(
                    f"GRAPHRAG_PROVIDER_UNAVAILABLE:{type(exc).__name__}"
                ) from exc
            errors = [
                {"workflow": item.workflow, "error": type(item.error).__name__}
                for item in results
                if item.error is not None
            ]
            if errors:
                raise GraphRagRunError(
                    "GRAPH_OUTPUT_INVALID:"
                    + ",".join(item["workflow"] for item in errors)
                )
            outputs = {
                name: self._read_output_table(output_dir, name)
                for name in self.required_outputs
            }
        if not outputs["entities"] or not outputs["relationships"]:
            raise GraphRagRunError("GRAPH_OUTPUT_INVALID")
        outputs["relationships"] = _normalize_relationship_endpoints(
            outputs["entities"],
            outputs["relationships"],
        )
        entity_ids = {str(item.get("id")) for item in outputs["entities"]}
        if any(
            str(item.get("source")) not in entity_ids
            or str(item.get("target")) not in entity_ids
            for item in outputs["relationships"]
        ):
            raise GraphRagRunError("GRAPH_OUTPUT_INVALID")
        if any(not item.get("text_unit_ids") for item in outputs["entities"]):
            raise GraphRagRunError("EVIDENCE_CLOSURE_FAILED")
        if any(not item.get("text_unit_ids") for item in outputs["relationships"]):
            raise GraphRagRunError("EVIDENCE_CLOSURE_FAILED")

        typed_relationships_path = output_dir / "typed_relationships.json"
        typed_relationships = self._load_typed_relationships(
            typed_relationships_path,
            source_relationships=outputs["relationships"],
        )
        if typed_relationships is None:
            typed_relationships = self.classifier.classify(
                outputs["entities"],
                outputs["relationships"],
                relation_profile=list(
                    (policy_context or {}).get("relation_profile") or []
                ),
            )
            typed_relationships_path.write_text(
                json.dumps(typed_relationships, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        output_manifest = {
            "schema_version": "course-graphrag-output/1.0",
            "course_id": manifest.course_id,
            "input_content_hash": manifest.input_content_hash,
            "counts": {name: len(rows) for name, rows in outputs.items()},
            "relation_policy": self.classifier.policy_version,
            "policy_context_hash": hashlib.sha256(
                json.dumps(
                    policy_context or {},
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest(),
            "completion_provider": settings.GRAPHRAG_COMPLETION_PROVIDER,
            "completion_model": settings.GRAPHRAG_COMPLETION_MODEL,
            "embedding_provider": settings.GRAPHRAG_EMBEDDING_PROVIDER,
            "embedding_model": settings.GRAPHRAG_EMBEDDING_MODEL,
        }
        output_bytes = json.dumps(
            output_manifest, ensure_ascii=False, sort_keys=True, indent=2
        ).encode("utf-8")
        output_hash = hashlib.sha256(output_bytes).hexdigest()
        output_manifest["output_content_hash"] = output_hash
        output_manifest_path = artifact_root / "output_manifest.json"
        output_manifest_path.write_text(
            json.dumps(output_manifest, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        return GraphRagArtifacts(
            entities=tuple(outputs["entities"]),
            relationships=tuple(typed_relationships),
            text_units=tuple(outputs["text_units"]),
            documents=tuple(outputs["documents"]),
            output_manifest_uri=str(output_manifest_path),
            output_content_hash=output_hash,
            warnings=tuple(),
            estimated_input_tokens=estimated_tokens,
            estimated_max_cost=estimated_cost,
        )

    def load_existing_artifacts(
        self,
        *,
        manifest: GraphRagInputManifest,
        artifact_root: Path,
    ) -> GraphRagArtifacts:
        """Load a completed GraphRAG run without invoking any model provider."""
        output_dir = artifact_root / "output"
        outputs = self._load_complete_outputs(output_dir, manifest=manifest)
        if outputs is None:
            raise GraphRagRunError("GRAPH_ARTIFACTS_NOT_FOUND")
        if not outputs["entities"] or not outputs["relationships"]:
            raise GraphRagRunError("GRAPH_OUTPUT_INVALID")

        outputs["relationships"] = _normalize_relationship_endpoints(
            outputs["entities"],
            outputs["relationships"],
        )
        entity_ids = {str(item.get("id")) for item in outputs["entities"]}
        if any(
            str(item.get("source")) not in entity_ids
            or str(item.get("target")) not in entity_ids
            for item in outputs["relationships"]
        ):
            raise GraphRagRunError("GRAPH_OUTPUT_INVALID")

        typed_relationships = self._load_typed_relationships(
            output_dir / "typed_relationships.json",
            source_relationships=outputs["relationships"],
        )
        if typed_relationships is None:
            raise GraphRagRunError("TYPED_RELATIONSHIPS_NOT_FOUND")

        output_manifest_path = artifact_root / "output_manifest.json"
        output_manifest_bytes = (
            output_manifest_path.read_bytes()
            if output_manifest_path.is_file()
            else json.dumps(
                {
                    "course_id": manifest.course_id,
                    "input_content_hash": manifest.input_content_hash,
                    "counts": {name: len(rows) for name, rows in outputs.items()},
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        )
        return GraphRagArtifacts(
            entities=tuple(outputs["entities"]),
            relationships=tuple(typed_relationships),
            text_units=tuple(outputs["text_units"]),
            documents=tuple(outputs["documents"]),
            output_manifest_uri=str(output_manifest_path),
            output_content_hash=hashlib.sha256(output_manifest_bytes).hexdigest(),
            warnings=tuple(),
            estimated_input_tokens=0,
            estimated_max_cost=0.0,
        )

    @staticmethod
    def _run_isolated_worker(
        *,
        manifest: GraphRagInputManifest,
        artifact_root: Path,
        policy_context: dict[str, Any] | None = None,
    ) -> GraphRagArtifacts:
        # Do not call Path.resolve() here. A venv's ``bin/python`` is normally
        # a symlink to the base interpreter; resolving the final symlink would
        # bypass the venv and lose GraphRAG/sqlmodel site-packages on Linux.
        python = Path(os.path.abspath(settings.GRAPHRAG_WORKER_PYTHON))
        if not python.is_file():
            raise GraphRagRunError("GRAPHRAG_WORKER_UNAVAILABLE")
        manifest_path = artifact_root / "input" / "input_manifest.json"
        result_path = artifact_root / "worker_result.json"
        policy_path = artifact_root / "input" / "policy_context.json"
        if not manifest_path.is_file():
            raise GraphRagRunError("GRAPH_INPUT_MANIFEST_MISMATCH")
        environment = os.environ.copy()
        environment["AI_COURSE_GRAPHRAG_IN_WORKER"] = "1"
        # Runtime/CLI overrides live on the already-instantiated Settings
        # object.  The isolated interpreter rebuilds Settings from its own
        # environment, so propagate the safety gates explicitly; otherwise a
        # bounded manual smoke could silently inherit broader server defaults.
        environment["GRAPHRAG_MAX_INPUT_TOKENS"] = str(
            settings.GRAPHRAG_MAX_INPUT_TOKENS
        )
        environment["GRAPHRAG_MAX_ESTIMATED_COST_USD"] = str(
            settings.GRAPHRAG_MAX_ESTIMATED_COST_USD
        )
        environment["GRAPHRAG_ESTIMATED_INPUT_COST_USD_PER_MILLION_TOKENS"] = str(
            settings.GRAPHRAG_ESTIMATED_INPUT_COST_USD_PER_MILLION_TOKENS
        )
        environment["GRAPHRAG_MAX_ESTIMATED_COST"] = str(
            settings.GRAPHRAG_MAX_ESTIMATED_COST
        )
        policy_path.write_text(
            json.dumps(policy_context or {}, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        try:
            completed = subprocess.run(
                [
                    str(python),
                    "-m",
                    "app.platform.knowledge.graphrag_worker",
                    "--manifest",
                    str(manifest_path),
                    "--artifact-root",
                    str(artifact_root),
                    "--result",
                    str(result_path),
                    "--policy-context",
                    str(policy_path),
                ],
                cwd=str(Path(__file__).resolve().parents[3]),
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=float(settings.GRAPHRAG_RUN_TIMEOUT_SECONDS) + 30,
            )
        except subprocess.TimeoutExpired as exc:
            raise GraphRagRunError("GRAPHRAG_RUN_TIMEOUT") from exc
        if not result_path.is_file():
            # A worker can finish writing all immutable GraphRAG tables and
            # still disappear before the small JSON handoff is flushed (for
            # example when the task process is restarted).  Do not discard a
            # complete, manifest-matching artifact set.  Re-enter the runner
            # in-process with isolation disabled; this path only validates the
            # tables and performs the remaining typed-relation step, so it does
            # not repeat GraphRAG extraction or embedding work.
            try:
                complete_outputs = GraphRagRunner()._load_complete_outputs(
                    artifact_root / "output",
                    manifest=manifest,
                )
                if complete_outputs is None:
                    raise GraphRagRunError("GRAPHRAG_WORKER_FAILED")
                return GraphRagRunner().run(
                    manifest=manifest,
                    artifact_root=artifact_root,
                    policy_context=policy_context,
                    allow_isolated_worker=False,
                )
            except GraphRagRunError:
                raise
            except Exception as exc:
                raise GraphRagRunError("GRAPHRAG_WORKER_FAILED") from exc
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GraphRagRunError("GRAPHRAG_WORKER_RESULT_INVALID") from exc
        if payload.get("error"):
            raise GraphRagRunError(str(payload["error"]))
        if completed.returncode != 0:
            raise GraphRagRunError("GRAPHRAG_WORKER_FAILED")
        if payload.get("input_content_hash") != manifest.input_content_hash:
            raise GraphRagRunError("GRAPH_INPUT_MANIFEST_MISMATCH")
        return GraphRagArtifacts(
            entities=tuple(payload.get("entities") or []),
            relationships=tuple(payload.get("relationships") or []),
            text_units=tuple(payload.get("text_units") or []),
            documents=tuple(payload.get("documents") or []),
            output_manifest_uri=str(payload.get("output_manifest_uri") or ""),
            output_content_hash=str(payload.get("output_content_hash") or ""),
            warnings=tuple(payload.get("warnings") or []),
            estimated_input_tokens=int(payload.get("estimated_input_tokens") or 0),
            estimated_max_cost=float(payload.get("estimated_max_cost") or 0.0),
        )

    @staticmethod
    def _validate_model_configuration() -> None:
        required = (
            settings.GRAPHRAG_COMPLETION_MODEL,
            settings.GRAPHRAG_COMPLETION_API_BASE,
            settings.GRAPHRAG_COMPLETION_API_KEY,
            settings.GRAPHRAG_EMBEDDING_MODEL,
        )
        if not all(required):
            raise GraphRagRunError("GRAPHRAG_NOT_CONFIGURED")
        embedding_provider = settings.GRAPHRAG_EMBEDDING_PROVIDER.strip().lower()
        if embedding_provider in {"local_bge", "bge-local", "local"}:
            if not settings.GRAPHRAG_EMBEDDING_LOCAL_PATH:
                raise GraphRagRunError("GRAPHRAG_NOT_CONFIGURED")
        elif not all((
            settings.GRAPHRAG_EMBEDDING_API_BASE,
            settings.GRAPHRAG_EMBEDDING_API_KEY,
        )):
            raise GraphRagRunError("GRAPHRAG_NOT_CONFIGURED")

    @staticmethod
    def _make_config(
        *,
        artifact_root: Path,
        output_dir: Path,
        reports_dir: Path,
        cache_dir: Path,
        vector_dir: Path,
        policy_context: dict[str, Any] | None = None,
    ):
        from graphrag.config.models.graph_rag_config import GraphRagConfig
        from graphrag.prompts.index.extract_graph import GRAPH_EXTRACTION_PROMPT
        from graphrag.prompts.index.summarize_descriptions import SUMMARIZE_PROMPT

        completion_provider = settings.GRAPHRAG_COMPLETION_PROVIDER or "openai"
        embedding_provider = settings.GRAPHRAG_EMBEDDING_PROVIDER or "openai"
        embedding_api_base = settings.GRAPHRAG_EMBEDDING_API_BASE
        embedding_api_key = settings.GRAPHRAG_EMBEDDING_API_KEY
        # This pipeline intentionally stops before GraphRAG's vector workflow.
        # Bundle indexing uses the configured production EmbeddingProvider.
        if embedding_provider.strip().lower() in {"local_bge", "bge-local", "local"}:
            embedding_provider = "openai"
            embedding_api_base = settings.GRAPHRAG_COMPLETION_API_BASE
            embedding_api_key = settings.GRAPHRAG_COMPLETION_API_KEY
        prompt_path = artifact_root / "input" / "edu_extract_graph_prompt.txt"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(
            _educational_extraction_prompt(
                GRAPH_EXTRACTION_PROMPT,
                policy_context or {},
            ),
            encoding="utf-8",
        )
        summary_prompt_path = artifact_root / "input" / "edu_summarize_descriptions_prompt.txt"
        summary_prompt_path.write_text(
            _educational_summary_prompt(SUMMARIZE_PROMPT),
            encoding="utf-8",
        )
        return GraphRagConfig.model_validate({
            "workflows": [
                "load_input_documents",
                "create_base_text_units",
                "create_final_documents",
                "extract_graph",
                "finalize_graph",
                "create_final_text_units",
            ],
            "completion_models": {
                "default_completion_model": {
                    "model_provider": completion_provider,
                    "model": settings.GRAPHRAG_COMPLETION_MODEL,
                    "api_base": settings.GRAPHRAG_COMPLETION_API_BASE,
                    "api_key": settings.GRAPHRAG_COMPLETION_API_KEY,
                    "retry": {
                        "type": "exponential_backoff",
                        "max_retries": settings.GRAPHRAG_MAX_RETRIES,
                    },
                },
            },
            "embedding_models": {
                "default_embedding_model": {
                    "model_provider": embedding_provider,
                    "model": settings.GRAPHRAG_EMBEDDING_MODEL,
                    "api_base": embedding_api_base,
                    "api_key": embedding_api_key,
                    "retry": {
                        "type": "exponential_backoff",
                        "max_retries": settings.GRAPHRAG_MAX_RETRIES,
                    },
                },
            },
            "input_storage": {"type": "file", "base_dir": str(artifact_root / "input")},
            "output_storage": {"type": "file", "base_dir": str(output_dir)},
            "update_output_storage": {"type": "file", "base_dir": str(output_dir / "update")},
            "reporting": {"type": "file", "base_dir": str(reports_dir)},
            "cache": {
                "type": "json",
                "storage": {"type": "file", "base_dir": str(cache_dir)},
            },
            "vector_store": {"type": "lancedb", "db_uri": str(vector_dir)},
            "embed_text": {
                "embedding_model_id": "default_embedding_model",
                "names": ["text_unit_text", "entity_description"],
            },
            "extract_graph": {
                "completion_model_id": "default_completion_model",
                "prompt": str(prompt_path),
                "entity_types": [
                    "concept", "principle", "method", "procedure", "formula",
                    "skill", "misconception", "example", "assessment",
                ],
                "max_gleanings": settings.GRAPHRAG_MAX_GLEANINGS,
            },
            "summarize_descriptions": {
                "completion_model_id": "default_completion_model",
                "prompt": str(summary_prompt_path),
            },
            "community_reports": {
                "completion_model_id": "default_completion_model",
            },
            "extract_claims": {"enabled": False},
        })

    @staticmethod
    def _read_output_table(output_dir: Path, name: str) -> list[dict]:
        path = output_dir / f"{name}.parquet"
        if not path.is_file():
            raise GraphRagRunError(f"GRAPH_OUTPUT_INVALID:{name}")
        frame = pd.read_parquet(path)
        return [_clean_row(row) for row in frame.to_dict(orient="records")]

    def _load_complete_outputs(
        self,
        output_dir: Path,
        *,
        manifest: GraphRagInputManifest,
    ) -> dict[str, list[dict]] | None:
        """Reuse immutable run output after a worker dies during post-processing."""
        paths = {
            name: output_dir / f"{name}.parquet"
            for name in self.required_outputs
        }
        if not all(path.is_file() and path.stat().st_size > 0 for path in paths.values()):
            return None
        try:
            outputs = {
                name: self._read_output_table(output_dir, name)
                for name in self.required_outputs
            }
        except (OSError, ValueError):
            return None
        if not outputs["documents"] or not outputs["text_units"]:
            return None
        expected_documents = {document.source_key for document in manifest.documents}
        actual_documents = {str(row.get("id") or "") for row in outputs["documents"]}
        if actual_documents != expected_documents:
            raise GraphRagRunError("GRAPH_INPUT_MANIFEST_MISMATCH")
        return outputs

    @staticmethod
    def _load_typed_relationships(
        path: Path,
        *,
        source_relationships: list[dict],
    ) -> list[dict] | None:
        if not path.is_file():
            return None
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(rows, list) or len(rows) != len(source_relationships):
            return None
        source_ids = {str(row.get("id") or "") for row in source_relationships}
        typed_ids = {str(row.get("id") or "") for row in rows}
        if typed_ids != source_ids:
            return None
        return rows


def _clean_row(row: dict[str, Any]) -> dict:
    cleaned: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, float) and pd.isna(value):
            cleaned[key] = None
        elif hasattr(value, "tolist"):
            cleaned[key] = value.tolist()
        else:
            cleaned[key] = value
    return cleaned


def _normalize_relationship_endpoints(
    entities: list[dict],
    relationships: list[dict],
) -> list[dict]:
    """GraphRAG 3.1 relations use entity titles; the domain uses run UUIDs."""
    by_id = {str(entity.get("id")): str(entity.get("id")) for entity in entities}
    by_title: dict[str, str] = {}
    ambiguous_titles: set[str] = set()
    for entity in entities:
        title = str(entity.get("title") or "").strip().casefold()
        if not title:
            continue
        entity_id = str(entity.get("id") or "")
        if title in by_title and by_title[title] != entity_id:
            ambiguous_titles.add(title)
        else:
            by_title[title] = entity_id
    normalized: list[dict] = []
    for relation in relationships:
        row = dict(relation)
        for key in ("source", "target"):
            raw = str(row.get(key) or "")
            if raw in by_id:
                continue
            title = raw.strip().casefold()
            if title in ambiguous_titles or title not in by_title:
                raise GraphRagRunError("GRAPH_OUTPUT_INVALID:relationship_endpoint")
            row[key] = by_title[title]
        normalized.append(row)
    return normalized


def _estimate_tokens(texts: list[str]) -> int:
    try:
        import tiktoken
        encoder = tiktoken.get_encoding("cl100k_base")
        return sum(len(encoder.encode(text)) for text in texts)
    except Exception:
        # Conservative fallback for mixed CJK/ASCII teaching material.
        return sum(max(1, len(text.encode("utf-8")) // 2) for text in texts)


def _educational_extraction_prompt(base_prompt: str, policy_context: dict[str, Any]) -> str:
    """Add bounded teacher regeneration intent without treating it as course fact."""
    source_scope = policy_context.get("source_scope") or {}
    required = [str(item) for item in source_scope.get("required_concepts") or []]
    forbidden = [str(item) for item in source_scope.get("forbidden_concepts") or []]
    instructions = str(policy_context.get("instructions") or "").strip()
    reason = str(policy_context.get("reason") or "").strip()

    def safe(value: str) -> str:
        # GraphRAG formats this prompt later; teacher text must not create
        # accidental format placeholders.
        return value.replace("{", "{{").replace("}", "}}")

    policy = (
        "\n-Educational graph policy-\n"
        "Extract concepts and relationships supported by the supplied source text. "
        "Do not infer prerequisite relations from chapter, page, or document order. "
        "A teacher's feedback below is extraction guidance only and is never evidence. "
        "Preserve source-grounded distinctions among concepts, principles, methods, "
        "procedures, formulas, skills, misconceptions, examples, and assessments. "
        "The canonical entity name and every entity or relationship description must be "
        "written in Simplified Chinese. Preserve established English abbreviations and "
        "standard English terms as parenthesized aliases after the Chinese canonical name, "
        "for example: 发动机排量（Engine Displacement） or 电子控制单元（ECU）. "
        "Do not translate formulas, symbols, model numbers, or acronyms into invented Chinese. "
        "When the source only contains an English technical term, infer the conventional Chinese "
        "technical name from that same source context without adding unsupported course facts.\n"
        f"Regeneration reason: {safe(reason) or 'not specified'}\n"
        f"Teacher guidance: {safe(instructions) or 'none'}\n"
        f"Concepts to ensure are considered when supported: "
        f"{safe(', '.join(required)) or 'none'}\n"
        f"Concepts to exclude from the graph: {safe(', '.join(forbidden)) or 'none'}\n"
    )
    prompt = base_prompt.replace(
        "3. Return output in English as a single list",
        "3. Return output in Simplified Chinese as a single list",
    )
    return policy + prompt


def _educational_summary_prompt(base_prompt: str) -> str:
    """Force GraphRAG's entity-description merge step to keep Chinese output."""
    policy = (
        "\n请使用简体中文合并实体描述。规范名称使用中文；已有英文缩写、公式、型号和"
        "标准英文术语作为括号内别名保留。不得把英文描述原样作为最终输出，也不得添加"
        "来源未支持的课程事实。\n"
    )
    return policy + base_prompt
