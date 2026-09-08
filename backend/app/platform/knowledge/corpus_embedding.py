"""CR2 本地 embedding：E5 适配、模型指纹、向量缓存与 HTTP 客户端。

与课程 BGE 链路的关系：
- 学科 embedding 配置独立于 ``GRAPHRAG_*``（见 ``app.core.config`` 的
  ``CORPUS_EMBEDDING_*``）；绝不复用 ``LocalBgeEmbeddingProvider`` 的
  CLS pooling——E5 必须用 attention-mask mean pooling + ``query: `` /
  ``passage: `` 前缀 + L2 归一化，否则跨语言检索语义漂移。
- ``encode(texts, kind, model_config)`` 为统一签名；``E5Provider`` 为
  真实实现（需已下载模型，离线加载，请求时绝不下载）。

指纹与缓存（§3.3）：
- ``model_fingerprint_for(config)`` 绑定 model_id / revision / files_hash /
  tokenizer / pooling / prefixes / dimension / max_length / code_version，
  任一变化即新指纹，旧向量不混算距离；
- ``input_hash_for(text, kind, model_fingerprint)`` 绑定完整向量输入；
  标题/元数据进入向量输入时必须由调用方拼入 ``text``（变化即新 hash，
  正确使缓存失效）；
- ``VectorCache`` 为 ``discipline_corpus_vectors`` 的真实仓储
  （``unique(model_fingerprint, input_hash)``），同维不同模型必然 miss。
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol, Sequence

from sqlmodel import Session, select

from app.models.discipline_corpus_index_model import DisciplineCorpusVector

#: 向量输入前缀（E5 官方约定；查询与文档必须区分）。
QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "

#: 本模块代码版本（实现变化即新指纹，不复用旧向量）。
CODE_VERSION = "corpus-embedding/1"

#: E5 small 的维度（配置声明值；运行时以前向探测核验为准）。
E5_SMALL_DIMENSION = 384


class EmbeddingConfigurationError(RuntimeError):
    pass


class EmbeddingValidationError(ValueError):
    """向量输出校验失败（维度/非有限/零向量/数量不一致）。"""

    def __init__(self, error_code: str, message: str):
        super().__init__(f"{error_code}: {message}")
        self.error_code = error_code


#: 支持的模型族：池化与前缀由族注册表决定（配置声明必须与族一致）。
#: - e5：attention-mask mean ＋ ``query: `` / ``passage: `` 前缀（官方约定）；
#: - bge-zh：CLS pooling ＋ 中文查询指令前缀（BGE v1.5 官方建议，文档侧无前缀）。
MODEL_FAMILIES: dict[str, dict[str, Any]] = {
    "e5": {
        "pooling": "attention-mask mean",
        "prefixes": {"query": QUERY_PREFIX, "passage": PASSAGE_PREFIX},
    },
    "bge-zh": {
        "pooling": "cls",
        "prefixes": {"query": "为这个句子生成表示以用于检索相关文章：", "passage": ""},
    },
}
DEFAULT_FAMILY = "e5"

#: 兼容旧名（E5 单族时期的常量；新代码请用 family_spec()）。
REQUIRED_POOLING = MODEL_FAMILIES[DEFAULT_FAMILY]["pooling"]


def family_spec(family: str | None) -> dict[str, Any]:
    """取模型族规格（缺省 e5，兼容未声明 family 的旧配置）。"""
    key = str(family or DEFAULT_FAMILY).strip().lower() or DEFAULT_FAMILY
    spec = MODEL_FAMILIES.get(key)
    if spec is None:
        raise EmbeddingConfigurationError(
            f"未知模型族 {family!r}（支持：{sorted(MODEL_FAMILIES)}）")
    return {"family": key, **spec}


def validate_model_config(config: dict) -> None:
    """校验配置声明的族/池化/前缀与实现一致（fail-closed，不静默改语义）。

    指纹的意义是"同指纹 ⇒ 同加工"。声明 ``pooling="cls"`` 却按 mean 编码，
    指纹就名不符实；此处按 ``family`` 注册表逐项校验（serve/worker/预检
    同一条路径）。未声明 family 视为 e5（兼容旧配置）。
    """
    if not isinstance(config, dict):
        raise EmbeddingConfigurationError("model config must be an object")
    spec = family_spec(config.get("family"))
    pooling = str(config.get("pooling") or "")
    if pooling != spec["pooling"]:
        raise EmbeddingConfigurationError(
            f"pooling 必须为 {spec['pooling']!r}（族 {spec['family']}；"
            f"收到 {pooling!r}）")
    prefixes = config.get("prefixes")
    if not isinstance(prefixes, dict) or {
            str(k): str(v) for k, v in prefixes.items()} != spec["prefixes"]:
        raise EmbeddingConfigurationError(
            f"prefixes 必须为 {spec['prefixes']}（族 {spec['family']}；"
            f"收到 {prefixes!r}）")


def model_fingerprint_for(config: dict) -> str:
    """由完整模型处理配置生成指纹；缺字段直接拒绝，不补默认。"""
    if not isinstance(config, dict):
        raise EmbeddingConfigurationError("model config must be an object")
    required = ("model_id", "revision", "files_hash", "tokenizer",
                "pooling", "prefixes", "dimension", "max_length")
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise EmbeddingConfigurationError(
            f"model config missing fields: {missing}（冻结前不得编码）")
    canonical = {
        "family": family_spec(config.get("family"))["family"],
        "model_id": config["model_id"],
        "revision": config["revision"],
        "files_hash": config["files_hash"],
        "tokenizer": config["tokenizer"],
        "pooling": config["pooling"],
        "prefixes": config["prefixes"],
        "dimension": config["dimension"],
        "max_length": config["max_length"],
        "code_version": CODE_VERSION,
    }
    digest = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return "emfp_" + digest[:32]


def input_hash_for(text: str, kind: str, model_fingerprint: str) -> str:
    """完整向量输入（含前缀与标题拼入后的文本）的缓存 key。"""
    if kind not in ("query", "passage"):
        raise EmbeddingConfigurationError("kind must be query|passage")
    return hashlib.sha256(
        "|".join([model_fingerprint, kind, str(text or "")]).encode("utf-8")
    ).hexdigest()


def build_vector_input(title: str, text: str, kind: str,
                       prefixes: dict | None = None) -> str:
    """组装进入模型的完整输入：族前缀 +（标题 + 换行）+ 正文。

    标题参与输入即参与 ``input_hash``（调用方必须如实传入，不得事后
    拼接标题却复用无标题向量）。``prefixes`` 缺省用 e5 约定（兼容旧调用）。
    """
    if kind not in ("query", "passage"):
        raise EmbeddingConfigurationError("kind must be query|passage")
    table = prefixes if isinstance(prefixes, dict) else \
        MODEL_FAMILIES[DEFAULT_FAMILY]["prefixes"]
    prefix = str(table.get(kind) or "")
    title = str(title or "").strip()
    body = str(text or "")
    if title:
        return f"{prefix}{title}\n{body}"
    return f"{prefix}{body}"


def mean_pool(hidden: Any, mask: Any) -> Any:
    """attention-mask mean pooling（E5 官方池化；CLS 在此禁用）。

    ``hidden`` 为 (batch, seq, dim)，``mask`` 为 (batch, seq) 的
    0/1 权重；全零 mask 行抛错，不产生 NaN。
    """
    import torch

    weights = mask.to(dtype=hidden.dtype).unsqueeze(-1)
    denom = weights.sum(dim=1).clamp(min=1e-9)
    pooled = (hidden * weights).sum(dim=1) / denom
    empty_rows = (mask.sum(dim=1) == 0).tolist()
    if any(empty_rows):
        raise EmbeddingValidationError(
            "EMPTY_INPUT", "attention mask 全零（空输入不得编码）")
    return pooled


def cls_pool(hidden: Any, mask: Any) -> Any:
    """CLS pooling（BGE 中文系列官方约定）：取 [CLS] 位向量。

    全零 mask 行抛错（空输入不得编码，与 mean_pool 同语义）。
    """
    if bool((mask.sum(dim=1) == 0).any()):
        raise EmbeddingValidationError(
            "EMPTY_INPUT", "attention mask 全零（空输入不得编码）")
    return hidden[:, 0]


def pool_by_family(hidden: Any, mask: Any, pooling: str) -> Any:
    """按声明的池化方式池化（未知方式拒绝，不静默回退）。"""
    if pooling == "attention-mask mean":
        return mean_pool(hidden, mask)
    if pooling == "cls":
        return cls_pool(hidden, mask)
    raise EmbeddingConfigurationError(f"未知池化方式：{pooling!r}")


def l2_normalize(matrix: Any) -> Any:
    """行 L2 归一化（零向量抛错，不输出零向量）。"""
    import torch

    norms = matrix.norm(p=2, dim=1, keepdim=True).clamp(min=1e-12)
    if bool((matrix.norm(p=2, dim=1) == 0).any()):
        raise EmbeddingValidationError("ZERO_VECTOR", "拒绝输出零向量")
    return matrix / norms


def validate_vectors(
    vectors: Sequence[Sequence[float]],
    *,
    expected_dimension: int,
    expected_count: int,
) -> None:
    """校验 embedding 输出：数量、维度、有限性、非零。"""
    if len(vectors) != expected_count:
        raise EmbeddingValidationError(
            "COUNT_MISMATCH",
            f"向量数量 {len(vectors)} 与输入 {expected_count} 不一致（批次顺序/数量必须一致）")
    for index, vector in enumerate(vectors):
        if len(vector) != expected_dimension:
            raise EmbeddingValidationError(
                "DIMENSION_MISMATCH",
                f"第 {index} 条维度 {len(vector)} != 期望 {expected_dimension}")
        if any(not math.isfinite(x) for x in vector):
            raise EmbeddingValidationError(
                "NON_FINITE_VALUE", f"第 {index} 条含 NaN/Inf")
        if all(x == 0.0 for x in vector):
            raise EmbeddingValidationError(
                "ZERO_VECTOR", f"第 {index} 条为零向量")


class EmbedClient(Protocol):
    """worker 侧推理客户端协议（HTTP 实现与测试 fake 共用）。"""

    def embed(self, texts: Sequence[str], kind: str) -> dict[str, Any]:
        """返回 ``{vectors, token_counts, model_fingerprint}``。"""
        ...


@dataclass
class E5Provider:
    """本地 E5 embedding（离线加载，请求时绝不下载）。

    用法：``E5Provider.load(model_dir, config)`` ——校验目录文件存在、
    tokenizer 名称一致、维度经固定探针前向核验；任一失败拒绝启动。
    ``encode`` 超长输入直接抛错（禁止静默截断，调用方必须正确分块）。
    """

    model_dir: Path
    config: dict[str, Any] = field(default_factory=dict)
    model_fingerprint: str = ""
    dimension: int = 0
    max_length: int = 512
    _tokenizer: Any = field(default=None, repr=False)
    _model: Any = field(default=None, repr=False)

    @classmethod
    def load(cls, model_dir: Any, config: dict) -> "E5Provider":
        # 先校验声明与实现一致（fail-closed），再加载模型
        validate_model_config(config)
        import torch
        from transformers import AutoModel, AutoTokenizer

        directory = Path(str(model_dir or ""))
        if not directory.is_dir():
            raise EmbeddingConfigurationError(
                f"模型目录不存在：{directory}（离线加载，不做下载）")
        fingerprint = model_fingerprint_for(config)
        dimension = int(config["dimension"])
        max_length = int(config["max_length"])
        try:
            tokenizer = AutoTokenizer.from_pretrained(
                str(directory), local_files_only=True, trust_remote_code=False)
            model = AutoModel.from_pretrained(
                str(directory), local_files_only=True, trust_remote_code=False)
        except Exception as exc:
            raise EmbeddingConfigurationError(
                f"模型离线加载失败（拒绝下载）：{exc}") from exc
        if str(getattr(tokenizer, "name_or_path", "") or "").split("/")[-1] != \
                str(config["tokenizer"]).split("/")[-1]:
            # 名称不一致只告警维度核验兜底？不——直接拒绝，防止 tokenizer 错位。
            raise EmbeddingConfigurationError(
                "tokenizer 与冻结配置不一致，拒绝启动")
        model.eval()
        provider = cls(model_dir=directory, config=dict(config),
                       model_fingerprint=fingerprint, dimension=dimension,
                       max_length=max_length, _tokenizer=tokenizer, _model=model)
        provider._probe()
        return provider

    def _probe(self) -> None:
        """固定输入前向探测：维度/有限性/确定性（部署健康检查同源）。"""
        import torch

        probe = ["probe ping", "固定探针测试"]
        first = self.encode(probe, "passage")
        validate_vectors(first, expected_dimension=self.dimension,
                         expected_count=len(probe))
        second = self.encode(probe, "passage")
        for a, b in zip(first, second):
            if any(abs(x - y) > 1e-6 for x, y in zip(a, b)):
                raise EmbeddingValidationError(
                    "NON_DETERMINISTIC", "固定探针两次编码不一致")

    def encode(self, texts: Sequence[str], kind: str) -> list[list[float]]:
        """编码一批文本；空串/超长直接抛错，不截断不补零。"""
        import torch

        if kind not in ("query", "passage"):
            raise EmbeddingConfigurationError("kind must be query|passage")
        texts = list(texts or [])
        if not texts:
            return []
        if any(not str(t).strip() for t in texts):
            raise EmbeddingValidationError("EMPTY_INPUT", "空文本不得编码")
        prefixed = [build_vector_input("", text, kind,
                                       self.config.get("prefixes"))
                    for text in texts]
        encoded = self._tokenizer(
            prefixed, padding=True, truncation=False,
            max_length=self.max_length, return_tensors="pt")
        lengths = encoded["attention_mask"].sum(dim=1).tolist()
        if any(n > self.max_length for n in lengths):
            raise EmbeddingValidationError(
                "INPUT_TOO_LONG",
                f"输入超 {self.max_length} tokens（调用方必须正确分块，禁止静默截断）")
        with torch.no_grad():
            hidden = self._model(**encoded).last_hidden_state
        pooled = pool_by_family(hidden, encoded["attention_mask"],
                                str(self.config.get("pooling") or ""))
        normalized = l2_normalize(pooled)
        vectors = normalized.cpu().tolist()
        validate_vectors(vectors, expected_dimension=self.dimension,
                         expected_count=len(texts))
        return vectors


@dataclass
class HttpEmbedClient:
    """loopback embedding 服务客户端（worker 用；指纹不一致拒绝）。"""

    base_url: str
    expected_fingerprint: str = ""
    timeout_seconds: float = 120.0
    max_retries: int = 2

    def embed(self, texts: Sequence[str], kind: str) -> dict[str, Any]:
        import httpx

        texts = list(texts or [])
        if not texts:
            return {"vectors": [], "token_counts": [],
                    "model_fingerprint": self.expected_fingerprint}
        payload = {"kind": kind, "texts": texts,
                   "expected_model_fingerprint": self.expected_fingerprint}
        url = self.base_url.rstrip("/") + "/embed"
        response = None
        for attempt in range(self.max_retries + 1):
            try:
                response = httpx.post(url, json=payload,
                                      timeout=self.timeout_seconds)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= self.max_retries:
                    raise EmbeddingValidationError(
                        "PROVIDER_UNAVAILABLE",
                        f"embedding 服务不可达：{type(exc).__name__}")
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= self.max_retries:
                    break
                continue
            break
        if response is None:
            raise EmbeddingValidationError(
                "PROVIDER_UNAVAILABLE", "embedding 服务不可达")
        if response.status_code == 429:
            raise EmbeddingValidationError("PROVIDER_BUSY", "embedding 服务限流（可重试）")
        if response.status_code >= 400:
            raise EmbeddingValidationError(
                "PROVIDER_UNAVAILABLE",
                f"embedding 服务 HTTP {response.status_code}")
        body = response.json()
        fingerprint = str(body.get("model_fingerprint") or "")
        if self.expected_fingerprint and fingerprint != self.expected_fingerprint:
            raise EmbeddingValidationError(
                "MODEL_MISMATCH",
                "服务端模型指纹与构建冻结指纹不一致（拒绝混算，不可重试）")
        vectors = body.get("vectors") or []
        token_counts = body.get("token_counts") or []
        dimension = int(body.get("dimension") or (len(vectors[0]) if vectors else 0))
        validate_vectors(vectors, expected_dimension=dimension,
                         expected_count=len(texts))
        return {"vectors": vectors, "token_counts": list(token_counts),
                "model_fingerprint": fingerprint, "dimension": dimension}


# ---------------------------------------------------------------------------
# 向量缓存仓储（真实 DB；key 含完整模型处理指纹）
# ---------------------------------------------------------------------------


def _new_embedding_id() -> str:
    import uuid

    return "emb_" + uuid.uuid4().hex[:16]


class VectorCache:
    """``discipline_corpus_vectors`` 仓储：一次计算，多构建复用。

    - ``get`` 未命中（含同维不同模型）返回 None，绝不跨指纹复用；
    - ``put_many`` 同一事务内批量写入、冲突复用（单 commit，不逐条提交）。
    """

    def __init__(self, session: Session):
        self._session = session

    def get(self, model_fingerprint: str, input_hash: str
            ) -> Optional[DisciplineCorpusVector]:
        return self._session.exec(
            select(DisciplineCorpusVector).where(
                DisciplineCorpusVector.model_fingerprint == model_fingerprint,
                DisciplineCorpusVector.input_hash == input_hash,
            )
        ).first()

    def put(self, *, model_fingerprint: str, input_hash: str,
            vector: Sequence[float], dimension: int, token_count: int,
            commit: bool = True) -> DisciplineCorpusVector:
        existing = self.get(model_fingerprint, input_hash)
        if existing is not None:
            return existing
        row = DisciplineCorpusVector(
            embedding_id=_new_embedding_id(),
            model_fingerprint=model_fingerprint,
            input_hash=input_hash,
            dimension=dimension,
            embedding=list(vector),
            token_count=token_count,
        )
        self._session.add(row)
        try:
            if commit:
                self._session.commit()
            else:
                self._session.flush()
        except Exception:
            self._session.rollback()
            existing = self.get(model_fingerprint, input_hash)
            if existing is None:
                raise
            return existing
        return row

    def put_many(self, rows: list[dict[str, Any]]) -> list[DisciplineCorpusVector]:
        """批量写入（单事务）；已存在 key 跳过并回读已有行。"""
        stored: list[DisciplineCorpusVector] = []
        for item in rows:
            existing = self.get(item["model_fingerprint"], item["input_hash"])
            if existing is not None:
                stored.append(existing)
                continue
            row = DisciplineCorpusVector(
                embedding_id=_new_embedding_id(),
                model_fingerprint=item["model_fingerprint"],
                input_hash=item["input_hash"],
                dimension=item["dimension"],
                embedding=list(item["vector"]),
                token_count=int(item.get("token_count") or 0),
            )
            self._session.add(row)
            stored.append(row)
        self._session.flush()
        return stored
