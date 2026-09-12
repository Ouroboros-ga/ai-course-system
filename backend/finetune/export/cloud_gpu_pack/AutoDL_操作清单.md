# AutoDL RTX 4090 操作清单 —— 7B LoRA 微调(取回 adapter)

> 场景:XH-202620 决赛 —— Qwen2.5-7B-Instruct LoRA,2212 条 v2.2 数据,3 epochs,产物 = adapter 模型文件。
> 适用卡型:RTX 4090 24GB(首选)/ RTX 4090D / RTX 3090 24GB(备选,命令相同,时长约 1.5 倍)。
> 预算:整单(训练+下载+上传)约 1–5 元。以下界面文案以 AutoDL 控制台实时为准,操作逻辑不变。

## 0. 准备(5 分钟)

1. 注册 autodl.com(手机号 + 支付宝实名),充 **10 元**足够。
2. 本地上传包:把本目录(`cloud_gpu_pack/`,含 `train_lora.py`、`data/`、本清单)打成 zip:
   ```bash
   # 在本目录的上一级执行
   # Windows 资源管理器选中 cloud_gpu_pack 右键→压缩,得到 cloud_gpu_pack.zip(约 1.3 MB)
   ```

## 1. 租卡(3 分钟)

1. 控制台 →「算力市场」→ 筛选:**单卡 RTX 4090 / 24GB**(无货选 4090D 或 3090)。
2. 地区随意(选有余量的);计费方式「按量计费」。
3. 镜像:选择带 **PyTorch 2.x + CUDA 12.x** 的镜像(例如 `PyTorch 2.5.1 / CUDA 12.4 / Python 3.12`,Miniconda 版)。
4. 数据盘:**≥ 50GB**(默认一般够;基座 15GB + 依赖/cache)。
5. 开机。计费立即开始;**不用时点「关机」只收存储费(约每小时 0.1 元级),别用「释放」**(释放会删盘)。

## 2. 连接并上传(5 分钟)

1. 实例列表中「JupyterLab」进入网页终端;或按控制台提示用 SSH(密钥登录)。
2. 上传:JupyterLab 文件区把 `cloud_gpu_pack.zip` 拖进 `/root/autodl-tmp/`(数据盘,空间大),然后终端解压:
   ```bash
   cd /root/autodl-tmp
   unzip cloud_gpu_pack.zip && cd cloud_gpu_pack
   ```

## 3. 环境与基座(10–20 分钟,大头是下载 15GB)

```bash
# 依赖(镜像自带 CUDA torch,requirements 中 torch>=2.3 已满足,不会重下大包)
pip install -r requirements.txt

# 加速下载:AutoDL 学术加速(只对本机会话生效)
source /etc/network_turbo 2>/dev/null || true

# 预下载基座(约 15GB;国内直连失败时加 HF_ENDPOINT=https://hf-mirror.com)
export HF_ENDPOINT=https://hf-mirror.com
python -c "from transformers import AutoModelForCausalLM, AutoTokenizer; AutoTokenizer.from_pretrained('Qwen/Qwen2.5-7B-Instruct'); AutoModelForCausalLM.from_pretrained('Qwen/Qwen2.5-7B-Instruct', torch_dtype='auto')"
# 若上面卡住/过慢,改用:
#   pip install -U "huggingface-cli[cli]" 2>/dev/null; huggingface-cli download Qwen/Qwen2.5-7B-Instruct
```

## 4. 训练(4090 预计 20–40 分钟;3090 约 40–70 分钟)

```bash
# 挂到 tmux 里,SSH/Jupyter 断开不中断
tmux new -s train
python train_lora.py \
  --base-model Qwen/Qwen2.5-7B-Instruct \
  --data-file data/instruction_train_v2.jsonl \
  --output-dir lora_output_qwen25_7b_v22 \
  --epochs 3 \
  --batch-size 4 --gradient-accumulation-steps 4 \
  --save-steps 139 --logging-steps 10
# 离开会话:Ctrl+B 然后按 D;回来:tmux attach -t train
```

- 每 139 步(=1 epoch)落一个 `checkpoint-139/278/417`,日志每 10 步一行 loss。
- 24GB 下 batch4 显存约 18–20GB;若 OOM:降 `--batch-size 2 --gradient-accumulation-steps 8`,或加 `--gradient-checkpointing`。
- 中途断了(实例还在):`--resume-from-checkpoint lora_output_qwen25_7b_v22/checkpoint-139` 续跑(改 epochs 仍写 3,脚本自动跳过已完成步)。
- 3090 备选:命令完全一致;嫌慢可保持 batch2/accum8(README 原默认)。

## 5. 取回 adapter(3 分钟)

训练结束输出 `[OK] LoRA adapter 已保存到 ...`,目录内容约几十 MB:
```bash
cd /root/autodl-tmp/cloud_gpu_pack
zip -r adapter_qwen25_7b_v22.zip lora_output_qwen25_7b_v22
```
JupyterLab 文件区勾选该 zip → 下载回本地;解压后**核心交付文件**:
- `adapter_model.safetensors` + `adapter_config.json`(填材料 05「LoRA 权重下载地址」)
- 其余为 tokenizer/adapter 附属文件,一起保留。

## 6. 验证与后续(可选)

```bash
# 本地/云端 sha256 与上传前对比(见 SHA256SUMS.txt 只覆盖包内源文件,adapter 是新产物)
python -c "from peft import PeftModel; from transformers import AutoModelForCausalLM; import torch; \
m=AutoModelForCausalLM.from_pretrained('Qwen/Qwen2.5-7B-Instruct', torch_dtype=torch.bfloat16, device_map='auto'); \
PeftModel.from_pretrained(m,'lora_output_qwen25_7b_v22').merge_and_unload().save_pretrained('merged_7b')"
# 合并后可在同机 vLLM 起 OpenAI 兼容端点跑 evaluate.py 对比;或只交 adapter(推荐)
```

## 7. 用完关停

- 训练/评测完 → 控制台「关机」(保盘,省钱);确认无需保留再「释放」。

## 常见问题速查

| 现象 | 处理 |
|---|---|
| pip 慢 | `pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple` |
| HF 下载失败/卡 0 | `source /etc/network_turbo` 或 `export HF_ENDPOINT=https://hf-mirror.com` 后重跑第 3 步 |
| CUDA OOM | batch2/accum8 或加 `--gradient-checkpointing`(24G 通常不需要) |
| loss 不降 | 先确认日志有 `'loss'`;lr 2e-4 为默认,2212 条 3 epochs 属常规 SFT 范围 |
| 网页终端断开训练没停 | tmux 会话还在,重连 `tmux attach -t train`;若进程真没了,用 checkpoint 续训 |
