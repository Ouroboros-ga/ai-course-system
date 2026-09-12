#!/usr/bin/env bash
# 云端一键:装 LLaMA-Factory(官方推荐 XHToken/LlamaFactory fork)并训练 1.7B / 4B
# 用法: bash scripts/run_llamafactory.sh [1.7B|4B|both]
set -e
cd "$(dirname "$0")/.."

WHICH="${1:-both}"
PY="${PY:-python}"

echo "== 1) 安装依赖 =="
# 官方 fork(需要 github 可达);不可达时退回 PyPI 上游 llamafactory
pip install -q --index-url https://pypi.tuna.tsinghua.edu.cn/simple "transformers>=5.0" "peft" "accelerate" "datasets" "trl" "pyyaml" "safetensors" || true
if git ls-remote https://github.com/XHToken/LlamaFactory >/dev/null 2>&1; then
  echo "-- 使用官方 fork XHToken/LlamaFactory"
  [ -d LlamaFactory ] || git clone --depth 1 https://github.com/XHToken/LlamaFactory
  pip install -q -e LlamaFactory
  CLI="llamafactory-cli"
else
  echo "-- github 不可达,退回 PyPI 上游 llamafactory(需自行确认 spark2_5 模板支持)"
  pip install -q --index-url https://pypi.tuna.tsinghua.edu.cn/simple llamafactory
  CLI="llamafactory-cli"
fi

run_one () {
  local cfg="$1"
  echo "== 训练 $cfg =="
  $CLI train "$cfg" 2>&1 | tee "train_$(basename "$cfg" .yaml).log"
}

if [ "$WHICH" = "1.7B" ] || [ "$WHICH" = "both" ]; then run_one configs/spark_x25_1_7b_lora.yaml; fi
if [ "$WHICH" = "4B" ]  || [ "$WHICH" = "both" ]; then run_one configs/spark_x25_4b_lora.yaml;  fi
echo "== 完成;adapter 在 saves/ 下 =="
