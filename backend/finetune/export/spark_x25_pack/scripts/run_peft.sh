#!/usr/bin/env bash
# 已验证路径(不依赖 LLaMA-Factory):用本包内 train_lora.py 直接 PEFT LoRA
# 前置:transformers==4.57.6 + torch>=2.3(cu128) + peft>=0.12(本机与 cloud_gpu_pack 已验证)
# 用法: bash scripts/run_peft.sh 4B|1.7B
set -e
cd "$(dirname "$0")/.."
WHICH="${1:-4B}"
TARGETS="q_k_v_proj,out_proj,gate_proj,up_proj,down_proj,g_proj"

if [ "$WHICH" = "4B" ]; then
  BASE="XHToken/Spark-X2.5-4B"; OUT="lora_output_spark_x25_4b"; BS=2; ACC=8
else
  BASE="XHToken/Spark-X2.5-1.7B"; OUT="lora_output_spark_x25_1_7b"; BS=4; ACC=4
fi

# 数据:包内 v2.2 ChatML 训练集(脚本按 messages 模板化)
DATA="${DATA:-data/instruction_train_v2.jsonl}"

python train_lora.py \
  --base-model "$BASE" \
  --data-file "$DATA" \
  --output-dir "$OUT" \
  --epochs 3 --batch-size "$BS" --gradient-accumulation-steps "$ACC" \
  --save-steps 100 --logging-steps 10 \
  --target-modules "$TARGETS" 2>&1 | tee "train_$(echo "$WHICH" | tr 'A-Z' 'a-z').log"
echo "== 完成;adapter 在 $OUT =="
