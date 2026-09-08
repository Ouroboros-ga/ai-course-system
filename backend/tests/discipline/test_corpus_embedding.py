"""CR2 embedding 单元验收：指纹、池化、前缀、校验与真实缓存仓储。

不下载模型、不调网络：E5 前向只用 torch 手工张量验证池化/归一；
``E5Provider.load`` 只测缺目录拒绝（离线语义）；真实小批评测走独立命令。
"""

from __future__ import annotations

import hashlib
import math

import pytest

from app.platform.knowledge.corpus_embedding import (
    CODE_VERSION,
    EmbeddingConfigurationError,
    EmbeddingValidationError,
    E5Provider,
    VectorCache,
    build_vector_input,
    input_hash_for,
    l2_normalize,
    mean_pool,
    model_fingerprint_for,
    validate_model_config,
    validate_vectors,
)

BASE_CONFIG = {
    "model_id": "intfloat/multilingual-e5-small",
    "revision": "synth-rev-001",
    "files_hash": "synth-files-hash",
    "tokenizer": "intfloat/multilingual-e5-small",
    "pooling": "attention-mask mean",
    "prefixes": {"query": "query: ", "passage": "passage: "},
    "dimension": 384,
    "max_length": 512,
}


def test_fingerprint_stable_and_sensitive():
    first = model_fingerprint_for(BASE_CONFIG)
    assert first == model_fingerprint_for(dict(BASE_CONFIG))
    assert first.startswith("emfp_")
    for field in ("model_id", "revision", "files_hash", "tokenizer",
                  "pooling", "dimension", "max_length"):
        mutated = dict(BASE_CONFIG, **{field: "changed"})
        assert model_fingerprint_for(mutated) != first
    mutated_prefixes = dict(BASE_CONFIG, prefixes={"query": "Q: ", "passage": "P: "})
    assert model_fingerprint_for(mutated_prefixes) != first
    with pytest.raises(EmbeddingConfigurationError):
        model_fingerprint_for({"model_id": "x"})


def test_validate_model_config_enforces_family_processing():
    """P2-7＋族注册表：声明与实现必须一致；cls 只对 bge-zh 族合法。"""
    validate_model_config(dict(BASE_CONFIG))  # e5 合法
    with pytest.raises(EmbeddingConfigurationError) as exc_info:
        validate_model_config(dict(BASE_CONFIG, pooling="cls"))
    assert "attention-mask mean" in str(exc_info.value)
    with pytest.raises(EmbeddingConfigurationError):
        validate_model_config(dict(
            BASE_CONFIG, prefixes={"query": "q: ", "passage": "p: "}))
    with pytest.raises(EmbeddingConfigurationError):
        validate_model_config(dict(BASE_CONFIG, prefixes={}))
    # bge-zh 族：CLS ＋ 中文查询指令前缀合法；改成 mean 即拒绝。
    bge = dict(BASE_CONFIG, family="bge-zh", pooling="cls", dimension=512,
               prefixes={"query": "为这个句子生成表示以用于检索相关文章：",
                         "passage": ""})
    validate_model_config(bge)
    with pytest.raises(EmbeddingConfigurationError):
        validate_model_config(dict(bge, pooling="attention-mask mean"))
    with pytest.raises(EmbeddingConfigurationError):
        validate_model_config(dict(BASE_CONFIG, family="unknown-family"))


def test_family_changes_fingerprint_and_vector_input():
    """同模型不同族 ⇒ 不同指纹；向量输入按族前缀组装。"""
    bge = dict(BASE_CONFIG, family="bge-zh", pooling="cls", dimension=512,
               prefixes={"query": "为这个句子生成表示以用于检索相关文章：",
                         "passage": ""})
    assert model_fingerprint_for(bge) != model_fingerprint_for(BASE_CONFIG)
    assert build_vector_input("", "页表", "passage", bge["prefixes"]) == "页表"
    assert build_vector_input("", "页表", "query",
                              bge["prefixes"]).startswith("为这个句子")
    assert build_vector_input("", "页表", "query") == "query: 页表"  # 旧调用兼容


def test_input_hash_binds_kind_text_and_model():
    fp = model_fingerprint_for(BASE_CONFIG)
    assert input_hash_for("页表", "query", fp) != input_hash_for("页表", "passage", fp)
    assert input_hash_for("页表", "query", fp) != input_hash_for("页表X", "query", fp)
    assert input_hash_for("页表", "query", fp) != input_hash_for("页表", "query", "emfp_other")
    with pytest.raises(EmbeddingConfigurationError):
        input_hash_for("x", "doc", fp)


def test_vector_input_applies_prefixes_and_title():
    assert build_vector_input("", "正文", "query") == "query: 正文"
    assert build_vector_input("", "body", "passage") == "passage: body"
    # 标题进入输入即进入 hash（调用方如实传入）
    with_title = build_vector_input("标题", "正文", "passage")
    without_title = build_vector_input("", "正文", "passage")
    assert with_title != without_title
    fp = model_fingerprint_for(BASE_CONFIG)
    assert input_hash_for(with_title, "passage", fp) != input_hash_for(
        without_title, "passage", fp)


def test_mean_pool_uses_attention_mask_not_cls():
    import torch

    hidden = torch.tensor([[[1.0, 0.0], [0.0, 2.0], [9.0, 9.0]]])
    mask = torch.tensor([[1, 1, 0]])
    pooled = mean_pool(hidden, mask)
    # 均值 (0.5, 1.0)：mask=0 的第三 token（CLS 位置类比）被排除
    assert pooled.tolist()[0] == pytest.approx([0.5, 1.0])
    with pytest.raises(EmbeddingValidationError) as exc_info:
        mean_pool(hidden, torch.tensor([[0, 0, 0]]))
    assert exc_info.value.error_code == "EMPTY_INPUT"


def test_l2_normalize_rejects_zero_vector():
    import torch

    normalized = l2_normalize(torch.tensor([[3.0, 4.0]]))
    assert normalized.tolist()[0] == pytest.approx([0.6, 0.8])
    with pytest.raises(EmbeddingValidationError) as exc_info:
        l2_normalize(torch.tensor([[0.0, 0.0]]))
    assert exc_info.value.error_code == "ZERO_VECTOR"


def test_validate_vectors_catches_all_defects():
    validate_vectors([[0.1, 0.2]], expected_dimension=2, expected_count=1)
    with pytest.raises(EmbeddingValidationError) as exc_info:
        validate_vectors([[0.1, 0.2]], expected_dimension=2, expected_count=2)
    assert exc_info.value.error_code == "COUNT_MISMATCH"
    with pytest.raises(EmbeddingValidationError) as exc_info:
        validate_vectors([[0.1]], expected_dimension=2, expected_count=1)
    assert exc_info.value.error_code == "DIMENSION_MISMATCH"
    with pytest.raises(EmbeddingValidationError) as exc_info:
        validate_vectors([[0.1, float("nan")]], expected_dimension=2,
                         expected_count=1)
    assert exc_info.value.error_code == "NON_FINITE_VALUE"
    with pytest.raises(EmbeddingValidationError) as exc_info:
        validate_vectors([[0.0, 0.0]], expected_dimension=2, expected_count=1)
    assert exc_info.value.error_code == "ZERO_VECTOR"


def test_e5_load_refuses_missing_dir_without_network():
    with pytest.raises(EmbeddingConfigurationError):
        E5Provider.load("/nonexistent-model-dir-xyz", BASE_CONFIG)


def test_same_dimension_different_model_never_reuses_cache(session):
    from app.platform.knowledge.corpus_embedding import VectorCache
    vector_cache = VectorCache(session)
    vector_cache.put(model_fingerprint="model_A", input_hash="h1",
                     vector=[1.0] + [0.0] * 383, dimension=384, token_count=5)
    assert vector_cache.get("model_B", "h1") is None
    hit = vector_cache.get("model_A", "h1")
    assert hit is not None and hit.dimension == 384


def test_vector_cache_put_many_single_transaction(session):
    cache = VectorCache(session)
    rows = [{
        "model_fingerprint": "emfp_bulk", "input_hash": f"bulk-{i}",
        "vector": [0.5, 0.5], "dimension": 2, "token_count": i,
    } for i in range(5)]
    stored = cache.put_many(rows)
    assert len(stored) == 5
    session.commit()
    # 冲突复用：重复 put 返回已有行，不新增
    again = cache.put_many(rows)
    session.commit()
    assert [r.embedding_id for r in again] == [r.embedding_id for r in stored]
    from sqlmodel import select

    from app.models.discipline_corpus_index_model import DisciplineCorpusVector

    count = len(session.exec(
        select(DisciplineCorpusVector).where(
            DisciplineCorpusVector.model_fingerprint == "emfp_bulk")).all())
    assert count == 5
