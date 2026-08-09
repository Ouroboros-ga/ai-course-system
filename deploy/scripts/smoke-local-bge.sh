#!/usr/bin/env bash
set -euo pipefail

readonly backend_root="/opt/smartcarb-git/backend"
cd "${backend_root}"

"${backend_root}/.venv/bin/python" - <<'PY'
import math

from app.platform.knowledge.embedding import LocalBgeEmbeddingProvider

provider = LocalBgeEmbeddingProvider.from_settings()
vectors = provider.embed(["课程材料向量检索烟测", "无关的合成测试文本"])
assert len(vectors) == 2
assert len(vectors[0]) == len(vectors[1]) > 0
assert all(math.isfinite(value) for vector in vectors for value in vector)
assert all(abs(sum(value * value for value in vector) - 1.0) < 1e-4 for vector in vectors)
print(
    f"Local BGE smoke passed: model={provider.model_name} "
    f"dimension={len(vectors[0])}"
)
PY
