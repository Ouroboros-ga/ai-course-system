# Spark-X2.5-4B LoRA 评测与曲线(数据 v3 · 2026-09-10)

> 训练:4090 24GB,3 epochs / 588 步 / 26.0 分钟;数据 v3 3127 训练 + 231 评测(来源 dev-liu `d1c2be0`)。

## 1. 交付文件

| 文件 | 说明 |
|---|---|
| `adapter_spark_x25_4b_final.zip` | adapter 交付包(7 文件,140MB);SHA256 `a5333425d9b42b5837628cc6d3819de77a821007a2b54ee57c5c16265fcafcf1` |
| `model_card_spark_x25_4b.md` | 模型卡(基座/许可/超参/边界) |
| `spark4b_loss_curve.csv` | **逐步 loss 曲线 588 点** |
| `spark4b_loss_curve_eval.csv` | 训练中 eval_loss(3 点) |
| `eval_spark_x25_4b.txt` | 基准 10 问逐条判定 + 6 组样例(基座/微调/参考答案) |

## 2. 训练损失

| 阶段 | 值 |
|---|---|
| train_loss(3 epochs 汇总) | **0.2032** |
| 逐步 loss:首/最低/末 | 2.5147 / 0.0012 / 0.0014 |
| 各 epoch 均值(1→3) | 0.4840 → 0.0797 → 0.0508 |
| 训练中 eval_loss(231 条) | epoch1 0.1053 → epoch2 **0.0987** → epoch3 0.1068 |

## 3. 基座 vs 微调(同分布 231 条,token 级)

| 模型 | eval_loss | perplexity |
|---|---|---|
| 基座 Spark-X2.5-4B | 2.39647 | 10.98 |
| + LoRA(本 adapter) | **0.05497** | **1.057** |

## 4. 基准 10 问(防污染集,自动 contains)

```
B:C1 type=contains base_pass=False lora_pass=False
B:C2 type=contains_grouped base_pass=None lora_pass=None
B:C3 type=judge0_manual base_pass=None lora_pass=None
B:C4 type=contains base_pass=False lora_pass=False
B:C5 type=contains base_pass=True lora_pass=True
B:C6 type=contains base_pass=True lora_pass=False
B:C7 type=contains base_pass=True lora_pass=True
B:C8 type=contains base_pass=False lora_pass=False
B:C9 type=contains base_pass=False lora_pass=True
B:C10 type=contains base_pass=True lora_pass=True
SUMMARY auto_count=8 base_pass=4/8 lora_pass=4/8
```

**结论(诚实)**:自动 8 题 **基座 4/8 vs 微调 4/8**(C6 基座过/微调未过,C9 相反);C2(分组)/C3(沙箱)未计。
严格 markers 口径下**无净提升**;提升体现在同分布 loss/perplexity 与课程风格贴合(见样例)。材料中不得宣称"评测提升"。

## 5. 复现命令

```bash
# 训练(4B,4090 预设)
python backend/finetune/train_lora.py --gpu-profile 4090 \
  --data-file backend/finetune/data/instruction_train.jsonl \
  --eval-file backend/finetune/data/instruction_eval.jsonl \
  --output-dir lora_output_spark_x25_4b
# 基座/微调 likelihood 对照
python scripts/eval_loss.py --model XHToken/Spark-X2.5-4B --eval-file data/instruction_eval.jsonl [--adapter <adapter_dir>]
# 生成式评测(基准 10 + 样例)
python scripts/eval_spark.py --model XHToken/Spark-X2.5-4B --adapter <adapter_dir> \
  --baseline data/eval_baseline.json --eval-jsonl data/instruction_eval.jsonl --out eval_spark_4b.txt
```
