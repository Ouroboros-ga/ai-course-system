# Spark-X2.5 训练包(1.7B / 4B · CS 学科数据 v2.2)

> 目标:用同一份 2212 条 v2.2 指令集,对科大讯飞 **星火 X2.5-1.7B / X2.5-4B** 做 LoRA SFT,
> 产出可提交的 adapter 模型文件(与 Qwen2.5-7B adapter、MaaS ServiceID 形成多基座证据)。
> 数据、评测、脚本与记录同源:`backend/finetune/export/微调交付_模型与对照表.md`。

## 0. 已实测结论(2026-09-09,本机 RTX 5070 Laptop 8GB)

| 项 | 结论 |
|---|---|
| 权重来源 | **ModelScope 亦托管**:`XHToken/Spark-X2.5-1.7B`(~3.4GB,2 分片)/ `XHToken/Spark-X2.5-4B`(~8.6GB,5 分片) |
| 许可 | **Apache-2.0**(模型卡 front-matter),可用于提交与商用 |
| 架构 | 自定义 `spark2_5`(`trust_remote_code=True`);3 层滑窗(512)+ 1 层全注意力混合;原生 1M 上下文 |
| 关键兼容性 | **transformers 5.17.0 不可用**(RoPE 校验收紧:`'float' object has no attribute 'get'`);**5.16.0 不可用**(`_tied_weights_keys` list/dict 不兼容);**4.57.6 完整可用**(本机已实测加载 1.7B:1707.7M 参数,chat_template 正常) |
| LoRA 目标层 | `q_k_v_proj,out_proj,gate_proj,up_proj,down_proj,g_proj`(**不是** Qwen 的 q/k/v/o_proj) |

**因此本仓已验证栈(`torch 2.11.0+cu128` + `transformers 4.57.6` + `peft 0.20.0`)可直接训练**,
无需 LLaMA-Factory(官方推荐其 fork,但该 fork 需 github 可达且自带版本锁定;本包提供等价 PEFT 路径并已实测加载)。

## 1. 目录

```
spark_x25_pack/
├── data/
│   ├── instruction_train_v2.jsonl   # 2212 条 ChatML(PEFT 路径用,= 权威训练集)
│   ├── spark_x25_alpaca.jsonl       # 2212 条 Alpaca(带 input 字段,LLaMA-Factory 用)
│   ├── dataset_info.json            # LLaMA-Factory 数据集注册
│   ├── instruction_eval_v2.jsonl    # 评测 50 条
│   └── eval_baseline.json           # 基准 10 问(防污染,只进评测)
├── configs/*.yaml                   # LLaMA-Factory 配置(1.7B / 4B)
└── scripts/
    ├── run_peft.sh                  # ★已验证路径:仓库 train_lora.py + 正确 target modules
    ├── run_llamafactory.sh          # 可选:官方 fork / 上游 LLaMA-Factory
    └── eval_spark.py                # 基座 vs 微调 评测(基准 10 contains + 样例)
```

## 2. 推荐执行(已验证路径,4090 24GB)

```bash
# 1) 取权重(ModelScope 国内快;hf-mirror/HF 亦可)
python -c "from modelscope import snapshot_download; snapshot_download('XHToken/Spark-X2.5-4B')"   # 可选,或用 HF 直连
# 2) 环境(与本仓 cloud_gpu_pack 相同):pip install -r ../../cloud_gpu_pack/requirements.txt
#    并确认: transformers==4.57.6  torch>=2.3+cu128  peft>=0.12
# 3) 训练(4B ≈ 8–15 分钟 / 3 epochs;1.7B ≈ 3–6 分钟)
bash scripts/run_peft.sh 4B
bash scripts/run_peft.sh 1.7B
# 4) 评测(基座 vs 微调)
python scripts/eval_spark.py --model XHToken/Spark-X2.5-4B \
  --adapter lora_output_spark_x25_4b --baseline data/eval_baseline.json \
  --eval-jsonl data/instruction_eval_v2.jsonl --out eval_spark_4b.txt
```

显存参考:4B bf16 ≈ 8.6GB 权重,4090 上 bs2 宽裕;1.7B ≈ 3.4GB,bs4 宽裕,本机 8GB 亦可(bs1)。

## 3. LLaMA-Factory(可选,官方推荐其 fork)

```bash
bash scripts/run_llamafactory.sh both      # 内部会尝试 clone XHToken/LlamaFactory;github 不可达时退回 PyPI 上游
```
注意:用上游 LLaMA-Factory 时若其 transformers 版本落进 5.16/5.17,会命中上表两个已知不兼容点;
届时以 `scripts/run_peft.sh` 为准(已验证)。

## 4. 产物与提交

- adapter:`lora_output_spark_x25_4b/`(adapter_model.safetensors + adapter_config.json + tokenizer)
- 评测:`eval_spark_4b.txt`(基准 10 问 contains 自动判定 + 6 组样例)
- 提交:拷入 `competition/05-作品代码/finetune_提交包/model_files/` 并更新 `DATASET_MANIFEST.md` 去向表。
