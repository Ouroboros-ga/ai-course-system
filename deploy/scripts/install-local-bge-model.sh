#!/usr/bin/env bash
set -euo pipefail

readonly backend_root="/opt/smartcarb-git/backend"
readonly app_python="${backend_root}/.venv/bin/python"
readonly models_root="${backend_root}/models"
readonly target_dir="${models_root}/bge-small-zh-v1.5"
readonly repo_id="BAAI/bge-small-zh-v1.5"
readonly revision="7999e1d3359715c523056ef9478215996d62a620"
readonly model_sha256="354763b9b1357bc9c44f62c6be2276321081ed2567773608c0d0785b61d5a026"

mkdir -p "${models_root}"
if [[ -f "${target_dir}/config.json" \
      && -f "${target_dir}/tokenizer.json" \
      && -f "${target_dir}/model.safetensors" ]]; then
  echo "Pinned local BGE model is already installed"
  exit 0
fi

staging_dir="$(mktemp -d "${models_root}/.bge-small-zh-v1.5.incoming.XXXXXX")"
cleanup() {
  rm -rf -- "${staging_dir}"
}
trap cleanup EXIT

"${app_python}" - "${repo_id}" "${revision}" "${staging_dir}" <<'PY'
from pathlib import Path
import sys

from huggingface_hub import snapshot_download

repo_id, revision, target = sys.argv[1:]
snapshot_download(
    repo_id=repo_id,
    revision=revision,
    local_dir=target,
    allow_patterns=[
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "vocab.txt",
        "model.safetensors",
    ],
)
required = ("config.json", "tokenizer.json", "model.safetensors")
missing = [name for name in required if not (Path(target) / name).is_file()]
if missing:
    raise SystemExit(f"downloaded BGE snapshot is incomplete: {missing}")
PY

printf '%s  %s\n' "${model_sha256}" "${staging_dir}/model.safetensors" \
  | sha256sum --check --status

if [[ -e "${target_dir}" ]]; then
  mv "${target_dir}" "${target_dir}.incomplete.$(date -u +%Y%m%dT%H%M%SZ)"
fi
mv "${staging_dir}" "${target_dir}"
trap - EXIT

(
  cd "${target_dir}"
  find . -type f ! -path './.cache/*' ! -name model.sha256 -print0 \
    | sort -z \
    | xargs -0 sha256sum > model.sha256
)
chmod -R a-w "${target_dir}"
echo "Pinned local BGE model installed"
