"""Print a secret-safe runtime/provider readiness snapshot as JSON.

This script never prints key/token values and performs no external requests.
It is intended for deployment audits, not as an application health endpoint.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings


def _configured(*values: object) -> bool:
    return all(bool(str(value).strip()) for value in values)


def _is_loopback(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() in {
        "127.0.0.1",
        "localhost",
        "::1",
    }


def main() -> int:
    embedding_provider = settings.GRAPHRAG_EMBEDDING_PROVIDER.strip().lower()
    embedding_configured = _configured(settings.GRAPHRAG_EMBEDDING_MODEL)
    if embedding_provider in {"local_bge", "bge-local", "local"}:
        embedding_configured = embedding_configured and Path(
            settings.GRAPHRAG_EMBEDDING_LOCAL_PATH
        ).exists()
    else:
        embedding_configured = embedding_configured and _configured(
            settings.GRAPHRAG_EMBEDDING_API_BASE,
            settings.GRAPHRAG_EMBEDDING_API_KEY,
        )

    tts_provider = settings.STAGE8_TTS_PROVIDER.strip().lower()
    tts_configured = tts_provider in {
        "doubao",
        "doubao_tts",
        "volcengine_doubao_tts",
    } and _configured(
        settings.VOLCENGINE_DOUBAO_TTS_API_KEY,
        settings.VOLCENGINE_DOUBAO_TTS_RESOURCE_ID,
        settings.VOLCENGINE_DOUBAO_TTS_SPEAKER,
    )

    dh_provider = settings.STAGE8_DH_PROVIDER.strip().lower()
    dh_configured = dh_provider not in {"", "fake"} and (
        Path(settings.DHLIVE_ENGINE_BINARY).is_file()
        or settings.DHLIVE_WORKER_PORT > 0
        or dh_provider == "duix"
    )

    payload = {
        "llm": {
            "provider": settings.LLM_PROVIDER,
            "configured": _configured(
                settings.LLM_API_BASE,
                settings.LLM_API_KEY,
                settings.LLM_MODEL_NAME,
            ),
        },
        "graphrag": {
            "enabled": settings.GRAPHRAG_ENABLED,
            "worker_exists": Path(settings.GRAPHRAG_WORKER_PYTHON).is_file(),
            "completion_configured": _configured(
                settings.GRAPHRAG_COMPLETION_API_BASE,
                settings.GRAPHRAG_COMPLETION_API_KEY,
                settings.GRAPHRAG_COMPLETION_MODEL,
            ),
            "embedding_provider": settings.GRAPHRAG_EMBEDDING_PROVIDER,
            "embedding_model": settings.GRAPHRAG_EMBEDDING_MODEL,
            "embedding_configured": embedding_configured,
            "embedding_model_configured": _configured(
                settings.GRAPHRAG_EMBEDDING_MODEL
            ),
            "embedding_local_path_configured": _configured(
                settings.GRAPHRAG_EMBEDDING_LOCAL_PATH
            ),
            "embedding_local_path_exists": bool(
                settings.GRAPHRAG_EMBEDDING_LOCAL_PATH.strip()
            ) and Path(settings.GRAPHRAG_EMBEDDING_LOCAL_PATH).exists(),
            "embedding_local_path_is_absolute": Path(
                settings.GRAPHRAG_EMBEDDING_LOCAL_PATH
            ).is_absolute(),
            "embedding_local_path_looks_windows": (
                len(settings.GRAPHRAG_EMBEDDING_LOCAL_PATH) >= 3
                and settings.GRAPHRAG_EMBEDDING_LOCAL_PATH[1:3] in {":\\", ":/"}
            ),
            "embedding_local_path_name": Path(
                settings.GRAPHRAG_EMBEDDING_LOCAL_PATH
            ).name,
            "max_input_tokens": settings.GRAPHRAG_MAX_INPUT_TOKENS,
            "max_estimated_cost_usd": settings.GRAPHRAG_MAX_ESTIMATED_COST_USD,
        },
        "ocr": {
            "configured": _configured(settings.PADDLEOCR_URL),
            "loopback": _is_loopback(settings.PADDLEOCR_URL),
            "required_for_pdf": settings.PADDLEOCR_REQUIRED_FOR_PDF,
        },
        "judge0": {
            "enabled": settings.JUDGE0_ENABLED,
            "configured": _configured(
                settings.JUDGE0_API_URL,
                settings.JUDGE0_AUTHN_TOKEN,
                settings.JUDGE0_AUTHZ_TOKEN,
            ),
            "loopback": _is_loopback(settings.JUDGE0_API_URL),
        },
        "stage8": {
            "media_demo_mode": settings.MEDIA_DEMO_MODE,
            "tts_provider": tts_provider or "unset",
            "tts_formal_configured": tts_configured,
            "digital_human_provider": dh_provider or "unset",
            "digital_human_formal_configured": dh_configured,
            "ppt_formal_configured": _configured(
                settings.XFYUN_PPT_APP_ID,
                settings.XFYUN_PPT_API_SECRET,
                settings.XFYUN_PPT_DEFAULT_TEMPLATE_ID,
            ),
        },
        "storage": {
            "backend": settings.OBJECT_STORAGE_BACKEND,
            "external_configured": (
                settings.OBJECT_STORAGE_BACKEND.strip().lower()
                in {"s3", "minio", "oss"}
                and _configured(
                    settings.OBJECT_STORAGE_ENDPOINT,
                    settings.OBJECT_STORAGE_BUCKET,
                    settings.OBJECT_STORAGE_ACCESS_KEY_ID,
                    settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
                )
            ),
        },
        "teaching_and_retrieval": {
            "teaching_agent_mode": settings.TEACHING_AGENT_MODE,
            "knowledge_provider": settings.TEACHING_AGENT_KNOWLEDGE_PROVIDER,
            "document_pipeline": settings.DOCUMENT_PIPELINE_VERSION,
            "knowledge_graph_pipeline": settings.KNOWLEDGE_GRAPH_PIPELINE_VERSION,
            "evidence_mode": settings.EVIDENCE_CITATION_MODE,
            "student_memory_mode": settings.STUDENT_MEMORY_MODE,
            "safety_governance_mode": settings.SAFETY_GOVERNANCE_MODE,
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
