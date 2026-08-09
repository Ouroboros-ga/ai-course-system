#!/usr/bin/env bash
set -euo pipefail

readonly node_alias="/opt/node-v22-current"
readonly node_dist_url="https://nodejs.org/dist/latest-v22.x"

if command -v node >/dev/null 2>&1 && [[ "$(node --version)" == v22.* ]]; then
  echo "Node $(node --version) is already installed"
else
  if [[ -e "${node_alias}" && ! -L "${node_alias}" ]]; then
    echo "Refusing to replace non-symlink ${node_alias}" >&2
    exit 1
  fi

  node_tmp_dir="$(mktemp -d /tmp/smartcarb-node22.XXXXXX)"
  trap 'case "${node_tmp_dir:-}" in /tmp/smartcarb-node22.*) rm -rf -- "${node_tmp_dir}" ;; esac' EXIT

  curl -fsSL "${node_dist_url}/SHASUMS256.txt" -o "${node_tmp_dir}/SHASUMS256.txt"
  node_archive="$(awk '/linux-x64.tar.xz$/ {print $2; exit}' "${node_tmp_dir}/SHASUMS256.txt")"
  test -n "${node_archive}"
  curl -fsSL "${node_dist_url}/${node_archive}" -o "${node_tmp_dir}/${node_archive}"

  (
    cd "${node_tmp_dir}"
    grep " ${node_archive}$" SHASUMS256.txt | sha256sum -c -
  )

  node_directory="${node_archive%.tar.xz}"
  if [[ ! -d "/opt/${node_directory}" ]]; then
    tar -xJf "${node_tmp_dir}/${node_archive}" -C /opt
  fi
  ln -sfn "/opt/${node_directory}" "${node_alias}"
fi

for executable in node npm npx corepack; do
  ln -sfn "${node_alias}/bin/${executable}" "/usr/local/bin/${executable}"
done

corepack enable --install-directory /usr/local/bin
corepack install --global pnpm@11.16.0

node --version
npm --version
pnpm --version
