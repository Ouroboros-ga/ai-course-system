# finetune_提交包 —— 微调交付自洽提交包(2026-09-09)

> 作用:挑战杯 XH-202620「05 作品代码」**微调部分的完整、自洽提交包**——评审/打包时
> 无需再回仓库多处翻找;除 adapter zip 外均随仓库提交,zip 本体本地留存(建议上传
> ModelScope 建仓后把「模型仓下载地址」填回材料 05)。
> 基座声明:**Qwen/Qwen2.5-7B-Instruct** 与 **XHToken/Spark-X2.5-4B**(Apache-2.0)两个 LoRA adapter;
> adapter 均不含基座权重,需自行加载基座。数据:训练集 v2.2(2212)与 v3(3127)/评测 231(见 `dataset/`)。

## 目录与逐项对照

| 材料05 要求 | 本包位置 | 说明 |
|---|---|---|
| 模型文件(LoRA 权重/下载地址) | `model_files/adapter_qwen25_7b_v22_final.zip` | 11 文件 146.4MB;SHA256 `548974c198ec81f54a6ac7caa7d358531eab8aa12d4697841aa6dfec7d1cdb50` |
| 模型说明/基座声明 | `model_files/model_card_qwen25_7b_v22.md` | 概述、用途边界、数据合规、评测诚实口径、复现命令 |
| 完整性校验 | `model_files/SHA256SUMS_微调交付.txt` | zip 与内部 11 文件逐项哈希 |
| 训练记录/对照表 | `evidence/微调交付_模型与对照表.md` | A–G 表:清单、训练记录、loss 曲线、数据速查、评测、材料填写、费用 |
| Loss 曲线(逐步) | `evidence/loss_curve_qwen25_7b_v22.csv` | 417 点(global_step/epoch/loss/grad_norm/lr) |
| 基座 vs 微调评测明细 | `evidence/eval_基座vs微调_结果与样例.txt` | 逐条判定 + 6 组样例;基准10 自动 4/8 vs 3/8(如实,不宣称提升) |
| 交付记录(归档) | `evidence/交付记录_2026-09-09.md` | 做了什么/交付/成本/坑/待办 |
| 代码复现入口 | `code/` | `cloud_gpu_pack`:train_lora.py + v2.2 数据 + requirements + README + AutoDL 操作清单 |
| **模型文件 ②(星火 4B,推荐主交付)** | `model_files/adapter_spark_x25_4b_final.zip` | 7 文件 95.2MB(解压 140MB);SHA256 `a5333425d9b42b5837628cc6d3819de77a821007a2b54ee57c5c16265fcafcf1` |
| 星火 4B 模型卡 | `model_files/model_card_spark_x25_4b.md` | 基座 Apache-2.0 / LoRA r16 / 32.45M 可训练(0.78%)/ 边界与复现 |
| 星火 4B 完整性校验 | `model_files/SHA256SUMS_spark_x25_4b.txt` | zip 与内部 7 文件逐项哈希 |
| 星火 4B 评测与曲线 | `evidence/spark_x25_4b_评测与曲线.md` | 训练记录 + **逐步 loss 曲线 588 点** + eval_loss + 基座/微调对照 + 基准10 |
| 星火 4B 曲线数据 | `evidence/spark4b_loss_curve.csv`、`spark4b_loss_curve_eval.csv` | 588 步 loss / 3 点 eval_loss |
| 星火 4B 生成式评测 | `evidence/eval_spark_x25_4b.txt` | 基准 10 问逐条判定 + 6 组样例(基座/微调/参考答案) |
| **数据集统合** | `dataset/` | v2.2(2212/50)+ **v3(3127/231,来源 dev-liu `d1c2be0`)** + 基准10 + `DATASET_MANIFEST.md` |
| MaaS 提交物(可选补充) | `maas/` | spark_train_messages(2212)/alpaca、评测 50、防污染 10、manifest |
| ServiceID(二选一,无需) | — | 赛题允许"模型文件或 ServiceID 二选一";本包已提供模型文件,故无需 ServiceID |

## 使用说明

1. **模型文件交付**:把 `model_files/` 下两个 zip(**Qwen2.5-7B v2.2** 与 **星火 X2.5-4B v3**,后者为主交付)
   上传 ModelScope 建仓(或网盘),材料 05「模型文件下载地址」填模型仓/下载地址;本地即留底。
2. **云端微调 ServiceID(可选,二选一)**:赛题允许"模型文件或 ServiceID 二选一",本包已提供
   模型文件,ServiceID **非必需**;如需讯飞生态服务 ID:登录 training.xfyun.cn → 建数据集 →
   上传 `maas/spark_train_messages.jsonl`(2212 条 ≥ lite 100 门槛)→ 选基座 spark/Qwen2.5 →
   训练 → 发布为服务 → 得到 ServiceID。MaaS 不提供权重下载,权重由本包 model_files 补齐。
3. **复现训练**:按 `code/README.md` + `code/AutoDL_操作清单.md`(4090 约 15 分钟/3 epochs);
   需 ≥16GB 显存 Linux;本机 8GB 仅可 3B 冒烟。
4. **评测**:50 条指令集 + judge0_manual 用例尚未全量评测(需沙箱);基准 10 问已测,结论如实。

## 合规红线(打包前核对)

- 包内无 `.env`、真实 Key、学生/敏感数据;训练数据为公开教材摘要 + 自建标准答案 +
  CC BY-SA 等开源语料(溯源见数据卡)。
- 评测口径诚实:基准 10 问 基座 4/8 vs 微调 3/8,**不得**宣称"评测提升";材料表述限
  "LoRA 训练收敛(0.67)、可复现、输出贴合课程语料风格"。

## 待办(提交前回填)

- [x] 材料 05:ServiceID 无需提供(已提供模型文件,赛题允许"模型文件或 ServiceID 二选一");
- [ ] (可选)50 条评测 + 沙箱用例补测后更新 `evidence/` 中 E 表;
- [ ] adapter zip 上传 ModelScope/网盘后,将下载地址写回材料 05 与 `model_files/SHA256SUMS_微调交付.txt` 旁说明。
