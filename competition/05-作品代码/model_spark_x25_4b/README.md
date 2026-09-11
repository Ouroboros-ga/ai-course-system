# 本地 CS 微调权重：Spark-X2.5-4B 学科 LoRA（数据 v3）

> 挑战杯 XH-202620 · 2026-09-10 交付 · 管线 `backend/finetune/`（数据集 v3 与训练脚本）
> 基座换成发榜单位科大讯飞的星火 X2.5-4B，同 CS 学科指令集 LoRA SFT。

## 目录

| 路径 | 说明 |
|---|---|
| `adapter_spark_x25_4b/` | LoRA 适配器：权重分片索引 `adapter_model.safetensors.index.json`、adapter_config、tokenizer 全套、chat_template、README。**权重分片本体（2×65MB）不在库内，见下节** |
| `evidence/` | 评测报告、评测明细、训练/eval loss 曲线 CSV（已去重） |
| `model_card_spark_x25_4b.md` | 模型卡（基座/数据/训练/评测口径/已知限制） |
| `SHA256SUMS.txt` | 本目录库内 12 个文件的 SHA-256（LF 行尾） |

## 权重分片获取（不在库内）

`adapter_model-00001/00002-of-00002.safetensors`（各约 65MB）因体积未入库，
与索引文件同目录放置即可加载。下载地址：**（待填写，ModelScope/HF 链接）**。
下载后必验 SHA（须与下完全一致，否则不得用于评审演示）：

```
adapter_model-00001-of-00002.safetensors  64927968 字节
  SHA256 = 4d945d661cf6136bafc21943fc84f53828f3d1d1e06420989c9708d6ff83528e
adapter_model-00002-of-00002.safetensors  64927920 字节
  SHA256 = e3507eb8ceb5afbfabd9b12024f3cac0d100b6e8b5dfcae68f6a40ca6b5d50e4
```

切分说明：原始单文件 129.9MB 超 GitHub 100MB 上限；已按标准分片格式切分，
432 张量与原始文件逐值比对一致。`PeftModel.from_pretrained` 可直接加载分片格式，
无需合并。原始单文件与 `final.zip` 留存于原始交付包，不入库。

## 完整性校验

```bash
cd competition/05-作品代码/model_spark_x25_4b
sha256sum -c SHA256SUMS.txt   # 须 12 个 OK（Windows：certutil -hashfile <文件> SHA256 逐个比对）
```

## 加载（推理服务侧）

```bash
pip install -r backend/finetune/requirements.txt  # transformers==4.57.6 系（4.57.1+；5.16/5.17 实测不兼容）
```

```python
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

base = AutoModelForCausalLM.from_pretrained(
    "XHToken/Spark-X2.5-4B", trust_remote_code=True, torch_dtype="auto")
model = PeftModel.from_pretrained(
    base, "competition/05-作品代码/model_spark_x25_4b/adapter_spark_x25_4b")
```

## 平台接线（LLM 提供商选项）

后端新增 `LLM_PROVIDER=local_cs`（`backend/app/common/llm_client.py` 的
`SparkCSLocalClient`，OpenAI 兼容协议），指向自建推理服务：

```bash
# .env（密钥只进 .env，不进仓库）
LLM_PROVIDER=local_cs
LOCAL_CS_BASE_URL=http://127.0.0.1:8001/v1
LOCAL_CS_MODEL=spark-x25-4b-cs
LOCAL_CS_API_KEY=
```

推理服务（如 vLLM）由部署方另行启动并加载本目录权重；服务未启动时调用按连接
失败 fail-closed，不回退其他提供商。空 `LOCAL_CS_API_KEY` 时仍发送空 Bearer 头，
vLLM 默认忽略；若服务端配置了鉴权密钥，请如实填写。

## 评测口径（诚实声明，见模型卡与 evidence）

- 同分布 231 条对照：基座 eval_loss 2.39647 → 微调 0.05497（领域拟合，非开放域泛化）；
- 防污染基准 10 问：基座 4/8 vs 微调 4/8，**不宣称提升**；
- 训练末段 loss 极低提示小数据集强拟合，必要时改用第 2 轮 checkpoint（checkpoint-392）。
