#!/usr/bin/env bash
set -euo pipefail

readonly backend_root="/opt/smartcarb-git/backend"
readonly app_python="${backend_root}/.venv/bin/python"
readonly graph_python="${backend_root}/.venv-graphrag/bin/python"
temporary_dir="$(mktemp -d /tmp/smartcarb-lancedb-smoke.XXXXXX)"
trap 'rm -rf -- "${temporary_dir}"' EXIT

"${app_python}" - "${temporary_dir}" <<'PY'
import sys

import lancedb

database = lancedb.connect(sys.argv[1])
database.create_table(
    "chunks",
    data=[
        {"id": "near", "text": "课程材料", "vector": [1.0, 0.0, 0.0]},
        {"id": "far", "text": "无关材料", "vector": [0.0, 1.0, 0.0]},
    ],
)
PY

"${graph_python}" - "${temporary_dir}" <<'PY'
import sys

import lancedb
import pyarrow

database = lancedb.connect(sys.argv[1])
rows = database.open_table("chunks").search([1.0, 0.0, 0.0]).limit(1).to_list()
assert rows and rows[0]["id"] == "near", rows
print(
    f"LanceDB Linux cross-venv smoke passed: "
    f"lancedb={lancedb.__version__} pyarrow={pyarrow.__version__}"
)
PY
