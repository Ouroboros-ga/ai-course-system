# 云 GPU 一键包 —— Qwen2.5 LoRA 微调(挑战杯 XH-202620)

> 生成:2026-09-09 · 数据:`instruction_train_v2.jsonl` 2212 条训练 / 50 条评测(数据卡见 `data/DATACARD.md`)
> 目的:在云 GPU(Linux,无 WDDM 降频问题)上跑出 **adapter 模型文件**(`adapter_model.safetensors + adapter_config.json`,几十 MB),作为本提交的微调模型文件交付。
> 本地 8GB 笔记本实测结论:**3B/7B 小 batch 训练受 Windows WDDM 限制仅 ~60–80 tok/s,3 epochs 需 6–9h**,不建议本地跑满;云 GPU 4090 约 0.5–1.5h、成本数元。

## 目录

```
cloud_gpu_pack/
├── train_lora.py                  # 训练脚本(已含 --gradient-checkpointing / --resume-from-checkpoint / --save-steps / --logging-steps)
├── requirements.txt               # pip 依赖
├── data/
│   ├── instruction_train_v2.jsonl # 训练集 2212 条(ChatML messages)
│   ├── instruction_eval_v2.jsonl  # 评测集 50 条(含基准 10 问,防污染:不进训练)
│   └── DATACARD.md                # 数据卡 v2.2
└── SHA256SUMS.txt                 # 文件校验(可选)
```

## 操作步骤(建议 AutoDL / 矩池云,4090 24G 或同档)

```bash
# 0) 租 4090(24G)实例,系统镜像选 PyTorch 2.x(CUDA 12.x);约 1-2 元/小时
# 1) 上传本包(拖进 JupyterLab 或 scp)
# 2) 安装依赖(30 秒-1 分钟)
pip install -r requirements.txt

# 3) 下载基座(国内网络用 hf-mirror;或先用 ModelScope 下载到本地目录)
export HF_ENDPOINT=https://hf-mirror.com
# 首次运行会自动下载 Qwen2.5-7B-Instruct(~15GB,约 5-15 分钟)
# 想显式预下载:
#   pip install -U "huggingface_hub[cli]" && huggingface-cli download Qwen/Qwen2.5-7B-Instruct

# 4) 训练(7B 推荐;3B 可换 Qwen/Qwen2.5-3B-Instruct)
python train_lora.py \
  --base-model Qwen/Qwen2.5-7B-Instruct \
  --data-file data/instruction_train_v2.jsonl \
  --output-dir lora_output_qwen25_7b_v22 \
  --epochs 3 \
  --batch-size 2 --gradient-accumulation-steps 8 \
  --save-steps 139 --logging-steps 10

# 5) 训练产出
#    lora_output_qwen25_7b_v22/adapter_model.safetensors  (~几十 MB)
#    lora_output_qwen25_7b_v22/adapter_config.json
#    每 139 步(=1 epoch)存 checkpoint-*/ 便于中断续训
# 6) 下载 adapter 两个文件回本地 → 填材料 05「LoRA 权重下载地址」
```

## 断点续训 / 参数说明

- 中断后续跑(会自动跳过已完成步):`--resume-from-checkpoint lora_output_qwen25_7b_v22/checkpoint-139`
- 显存紧张再加 `--gradient-checkpointing`(24G 卡跑 7B batch2 不需要)
- 评测/合并对比(可选,回本地或继续用云卡):
  - 对比评测 `python evaluate.py --model <本地 vLLM 或 ServiceID>`(评测脚本见仓库 `backend/finetune/evaluate.py`,需自有端点 Key)
  - 合并全量权重:`python -c "from peft import PeftModel; from transformers import AutoModelForCausalLM; m=AutoModelForCausalLM.from_pretrained('Qwen/Qwen2.5-7B-Instruct'); PeftModel.from_pretrained(m,'lora_output_qwen25_7b_v22').merge_and_unload().save_pretrained('merged_7b')"`
  - vLLM 部署为 OpenAI 兼容端点(等效 ServiceID 可评测):`vllm serve merged_7b --max-model-len 2048`

## 数据要点(2212 条,来自仓库 v2.2)

- 13 类任务:知识点讲解/图谱关系/解题推演/代码三件套/多轮教学/误区澄清/带引用作答/判断题/术语对照/知识定位/T11 出处溯源/T12 真实课件问答/T13 学科语料接地问答(LLM 生成+三重过滤,1099 条)。
- 单条内容 ≤793 字符,远低于 1024 token 上限,**训练不会发生截断**。
- 评测 50 条含防污染基准 10 问,只进 eval。

## 成本与时间(4090/24G 参考)

| 基座 | 显存 | 3 epochs 预计 | 费用(1-2 元/h) |
|---|---|---|---|
| Qwen2.5-7B-Instruct(推荐,与申报口径一致) | ~18-20GB | 0.5–1.5h | ≈ 1–3 元 |
| Qwen2.5-3B-Instruct(快速验证) | ~8-9GB | 0.2–0.5h | < 1 元 |
