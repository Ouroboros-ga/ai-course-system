"""Embedding providers used by course vector indexes."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

import httpx

from app.core.config import settings


class EmbeddingConfigurationError(RuntimeError):
    pass


class EmbeddingResponseError(RuntimeError):
    pass


class EmbeddingProvider(Protocol):
    provider_name: str
    model_name: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        ...


def embedding_provider_from_settings() -> EmbeddingProvider:
    provider = settings.GRAPHRAG_EMBEDDING_PROVIDER.strip().lower()
    if provider in {"local_bge", "bge-local", "local"}:
        return LocalBgeEmbeddingProvider.from_settings()
    return OpenAICompatibleEmbeddingProvider.from_settings()


@dataclass
class OpenAICompatibleEmbeddingProvider:
    """Minimal OpenAI-compatible embeddings client.

    Completion and embedding configuration remain intentionally independent.
    The API key is only added to the request header and is never represented in
    manifests or exception messages.
    """

    api_base: str
    api_key: str
    model_name: str
    expected_dimension: int = 0
    timeout_seconds: float = 120.0
    batch_size: int = 64
    max_retries: int = 2
    provider_name: str = "openai-compatible"

    @classmethod
    def from_settings(cls) -> "OpenAICompatibleEmbeddingProvider":
        if not settings.GRAPHRAG_EMBEDDING_API_BASE:
            raise EmbeddingConfigurationError("GRAPHRAG_EMBEDDING_API_BASE is required")
        if not settings.GRAPHRAG_EMBEDDING_API_KEY:
            raise EmbeddingConfigurationError("GRAPHRAG_EMBEDDING_API_KEY is required")
        if not settings.GRAPHRAG_EMBEDDING_MODEL:
            raise EmbeddingConfigurationError("GRAPHRAG_EMBEDDING_MODEL is required")
        return cls(
            api_base=settings.GRAPHRAG_EMBEDDING_API_BASE,
            api_key=settings.GRAPHRAG_EMBEDDING_API_KEY,
            model_name=settings.GRAPHRAG_EMBEDDING_MODEL,
            expected_dimension=settings.GRAPHRAG_EMBEDDING_DIMENSION,
            batch_size=max(1, settings.GRAPHRAG_EMBEDDING_BATCH_SIZE),
            max_retries=max(0, settings.GRAPHRAG_MAX_RETRIES),
            provider_name=settings.GRAPHRAG_EMBEDDING_PROVIDER or "openai-compatible",
        )

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for offset in range(0, len(texts), self.batch_size):
            vectors.extend(self._embed_batch(texts[offset:offset + self.batch_size]))
        return vectors

    def _embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        endpoint = self.api_base.rstrip("/")
        if not endpoint.endswith("/embeddings"):
            endpoint += "/embeddings"
        response = None
        for attempt in range(self.max_retries + 1):
            try:
                response = httpx.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.model_name, "input": list(texts)},
                    timeout=self.timeout_seconds,
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= self.max_retries:
                    raise EmbeddingResponseError(
                        f"embedding provider unavailable: {type(exc).__name__}"
                    ) from exc
                time.sleep(min(2 ** attempt, 4))
                continue
            if response.status_code < 500 and response.status_code != 429:
                break
            if attempt >= self.max_retries:
                break
            time.sleep(min(2 ** attempt, 4))
        if response is None:
            raise EmbeddingResponseError("embedding provider unavailable")
        if response.status_code >= 400:
            raise EmbeddingResponseError(
                f"embedding provider returned HTTP {response.status_code}"
            )
        payload = response.json()
        ordered = sorted(payload.get("data") or [], key=lambda item: item.get("index", 0))
        vectors = [list(item.get("embedding") or []) for item in ordered]
        if len(vectors) != len(texts):
            raise EmbeddingResponseError("embedding result count does not match input count")
        dimensions = {len(vector) for vector in vectors}
        if not dimensions or 0 in dimensions or len(dimensions) != 1:
            raise EmbeddingResponseError("embedding vectors have inconsistent dimensions")
        dimension = next(iter(dimensions))
        if self.expected_dimension and dimension != self.expected_dimension:
            raise EmbeddingResponseError(
                f"embedding dimension mismatch: expected {self.expected_dimension}, got {dimension}"
            )
        if not self.expected_dimension:
            self.expected_dimension = dimension
        if any(not math.isfinite(value) for vector in vectors for value in vector):
            raise EmbeddingResponseError("embedding vectors contain non-finite values")
        return vectors


@dataclass
class FixedEmbeddingProvider:
    """Deterministic provider for isolated tests; never selected by settings."""

    dimension: int = 8
    provider_name: str = "fixed-test"
    model_name: str = "fixed-test/1"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            values = [0.0] * self.dimension
            for offset, byte in enumerate(text.encode("utf-8")):
                values[offset % self.dimension] += (byte + 1) / 256.0
            norm = math.sqrt(sum(value * value for value in values)) or 1.0
            vectors.append([value / norm for value in values])
        return vectors


@dataclass
class LocalBgeEmbeddingProvider:
    """Production local BGE provider with offline-only model loading."""

    model_path: Path
    model_name: str
    expected_dimension: int = 0
    batch_size: int = 32
    max_length: int = 512
    query_instruction: str = ""
    provider_name: str = "local_bge"

    @classmethod
    def from_settings(cls) -> "LocalBgeEmbeddingProvider":
        raw_path = settings.GRAPHRAG_EMBEDDING_LOCAL_PATH.strip()
        if not raw_path:
            raise EmbeddingConfigurationError(
                "GRAPHRAG_EMBEDDING_LOCAL_PATH is required"
            )
        model_path = Path(raw_path).resolve()
        required = ("config.json", "tokenizer.json", "model.safetensors")
        if not model_path.is_dir() or any(
            not (model_path / name).is_file() for name in required
        ):
            raise EmbeddingConfigurationError("local BGE model files are incomplete")
        return cls(
            model_path=model_path,
            model_name=(
                settings.GRAPHRAG_EMBEDDING_MODEL
                or model_path.name
            ),
            expected_dimension=settings.GRAPHRAG_EMBEDDING_DIMENSION,
            batch_size=max(1, settings.GRAPHRAG_EMBEDDING_BATCH_SIZE),
            max_length=max(8, settings.GRAPHRAG_EMBEDDING_MAX_LENGTH),
            query_instruction=settings.GRAPHRAG_EMBEDDING_QUERY_INSTRUCTION,
        )

    def __post_init__(self) -> None:
        import torchgen  # noqa: F401
        import torch
        from transformers import AutoModel, AutoTokenizer

        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(
            str(self.model_path),
            local_files_only=True,
        )
        self._model = AutoModel.from_pretrained(
            str(self.model_path),
            local_files_only=True,
        )
        self._model.eval()

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        prepared = [
            f"{self.query_instruction}{text}" if self.query_instruction else str(text)
            for text in texts
        ]
        vectors: list[list[float]] = []
        with self._torch.inference_mode():
            for offset in range(0, len(prepared), self.batch_size):
                batch = self._tokenizer(
                    prepared[offset:offset + self.batch_size],
                    padding=True,
                    truncation=True,
                    max_length=self.max_length,
                    return_tensors="pt",
                )
                output = self._model(**batch).last_hidden_state[:, 0]
                output = self._torch.nn.functional.normalize(output, p=2, dim=1)
                vectors.extend(output.cpu().tolist())
        dimensions = {len(vector) for vector in vectors}
        if len(dimensions) != 1 or 0 in dimensions:
            raise EmbeddingResponseError("local BGE vectors have invalid dimensions")
        dimension = next(iter(dimensions))
        if self.expected_dimension and dimension != self.expected_dimension:
            raise EmbeddingResponseError(
                f"embedding dimension mismatch: expected {self.expected_dimension}, got {dimension}"
            )
        if not self.expected_dimension:
            self.expected_dimension = dimension
        if any(not math.isfinite(value) for vector in vectors for value in vector):
            raise EmbeddingResponseError("local BGE vectors contain non-finite values")
        return vectors
