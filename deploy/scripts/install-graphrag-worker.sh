#!/usr/bin/env bash
set -euo pipefail

readonly backend_root="/opt/smartcarb-git/backend"
readonly worker_venv="${backend_root}/.venv-graphrag"
readonly worker_python="${worker_venv}/bin/python"

export PIP_NO_CACHE_DIR=1

test -x "${backend_root}/.venv/bin/python"

if [[ ! -x "${worker_python}" ]]; then
  "${backend_root}/.venv/bin/python" -m venv "${worker_venv}"
fi

"${worker_python}" -m pip install --disable-pip-version-check --upgrade pip
"${worker_python}" -m pip install --disable-pip-version-check \
  "graphrag==3.1.1" \
  "sqlmodel>=0.0.37,<0.1" \
  "pydantic-settings>=2.13.1,<3" \
  "httpx>=0.28.1,<0.29" \
  "python-jose[cryptography]>=3.5,<4" \
  "bcrypt>=4,<6" \
  "lancedb==0.34.0"

cd "${backend_root}"
PYTHONPATH="${backend_root}" "${worker_python}" - <<'PY'
from importlib import metadata

import graphrag
from app.platform.knowledge.graphrag_runner import GraphRagRunner

assert graphrag is not None
assert GraphRagRunner is not None
installed = {dist.metadata["Name"].lower() for dist in metadata.distributions()}
unexpected = sorted(
    name for name in installed
    if name == "torch" or name.startswith(("nvidia-", "cuda-"))
)
assert not unexpected, f"unexpected GPU dependencies: {unexpected}"
print("GraphRAG worker imports are ready")
PY
PYTHONPATH="${backend_root}" "${worker_python}" \
  -m app.platform.knowledge.graphrag_worker --help >/dev/null
"${worker_python}" -m pip freeze > "${worker_venv}/installed-packages.txt"
chmod 644 "${worker_venv}/installed-packages.txt"

echo "GraphRAG worker runtime installed"
