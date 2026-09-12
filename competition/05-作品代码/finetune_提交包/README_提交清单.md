# finetune_提交包 —— 微调交付自洽提交包(Qwen2.5-7B 与 星火 X2.5-4B 分列)

> 作用:挑战杯 XH-202620「05 作品代码」**微调部分的完整、自洽提交包**——评审/打包时无需再回仓库多处翻找。
> 两套交付物**彼此独立**(各自模型文件 + 曲线 + 评测 + 模型卡),共用代码/数据集/MaaS 提交物在根目录。
> adapter 均不含基座权重,需自行加载基座;zip 本体本地留存(建议上传 ModelScope 建仓后把「模型仓下载地址」填回材料 05)。

## 目录结构

```
finetune_提交包/
├── README_提交清单.md                 ← 本文件
├── model_spark_x25_4b/                ★ 交付 ①(主交付,发榜单位模型)
│   ├── adapter_spark_x25_4b_final.zip     LoRA 权重包(7 文件;SHA256 a5333425…cfcf1)
│   ├── model_card_spark_x25_4b.md         模型卡(Apache-2.0 / r16 / 32.45M 可训练 / 边界)
│   ├── SHA256SUMS_spark_x25_4b.txt        逐文件哈希
│   └── evidence/
│       ├── spark_x25_4b_评测与曲线.md     训练记录 + 曲线 + 评测对照
│       ├── spark4b_loss_curve.csv         **逐步 loss 曲线 588 点**
│       ├── spark4b_loss_curve_eval.csv    训练中 eval_loss(3 点)
│       └── eval_spark_x25_4b.txt          基准 10 问逐条判定 + 6 组样例
├── model_qwen25_7b_v22/               ☆ 交付 ②(对照交付,早期 7B 路线)
│   ├── adapter_qwen25_7b_v22_final.zip    LoRA 权重包(11 文件;SHA256 548974c1…cdb50)
│   ├── model_card_qwen25_7b_v22.md
│   ├── SHA256SUMS_微调交付.txt
│   └── evidence/
│       ├── 微调交付_模型与对照表.md         A–G 表
│       ├── loss_curve_qwen25_7b_v22.csv   逐步 loss 曲线 417 点
│       ├── eval_基座vs微调_结果与样例.txt   基准 10 问逐条 + 6 组样例
│       └── 交付记录_2026-09-09.md
├── dataset/                          共用数据(按用途分组)
│   ├── DATASET_MANIFEST.md                统合清单(画像/任务构成/防污染/去向)
│   ├── benchmark10_only.jsonl             基准 10 问(只进评测)
│   ├── v2.2_qwen25_7b/                    Qwen 用:2212 训练 + 50 评测
│   └── v3_spark_x25_4b/                   星火用:3127 训练 + 231 评测(来源 dev-liu d1c2be0)
├── code/                             共用复现入口(cloud_gpu_pack:train_lora.py + 数据 + 操作清单)
└── maas/                             共用 MaaS 提交物(spark_train_messages 等;ServiceID 二选一时可选)
```

## 两套模型逐项对照

| 项 | 星火 X2.5-4B(交付 ①,主) | Qwen2.5-7B(交付 ②,对照) |
|---|---|---|
| 基座 / 许可 | `XHToken/Spark-X2.5-4B` / **Apache-2.0** | `Qwen/Qwen2.5-7B-Instruct` |
| 数据 | v3 **3127 训练 / 231 评测** | v2.2 **2212 训练 / 50 评测** |
| LoRA | r16/α32,6 类目标层(融合 QKV) | r16/α32,7 类目标层 |
| 可训练参数 | 32.45M(0.78%) | 40.37M(0.53%) |
| 训练 | 3 epochs / 588 步 / **26 分钟**(4090) | 3 epochs / 417 步 / **15 分钟**(4090) |
| 训练损失 | train_loss **0.2032**;eval_loss 0.1053→**0.0987**→0.1068 | train_loss **0.667–0.669**(两次一致) |
| 同分布对照 | 231 条:**基座 eval_loss 2.39647(ppl 10.98)→ 微调 0.05497(ppl 1.057)** | 基准 10 问 contains 4/8 vs 3/8(未做 loss 对照) |
| 基准 10 问(自动) | **4/8 vs 4/8**(如实,不宣称提升) | 4/8 vs 3/8(如实,不宣称提升) |
| 模型文件 | `model_spark_x25_4b/adapter_spark_x25_4b_final.zip`(90.8MB) | `model_qwen25_7b_v22/adapter_qwen25_7b_v22_final.zip`(146.4MB) |

## 使用说明

1. **模型文件交付**:分别上传两个 zip(建议主交付星火包优先)到 ModelScope 建仓或网盘,
   材料 05「模型文件下载地址」填对应地址;本地即留底。
2. **复现训练**:`code/README.md` + `code/AutoDL_操作清单.md`;星火需 `transformers==4.57.6` 系
   (实测 5.16/5.17 不兼容),LoRA 目标层见各模型卡。
3. **ServiceID(二选一,无需)**:赛题允许"模型文件或 ServiceID 二选一",本包已提供模型文件;
   如需讯飞生态服务 ID,用 `maas/spark_train_messages.jsonl` 在 training.xfyun.cn 训练后发布获取。
4. **评测现状**:两套均已做基准 10 问自动判定 + 样例;星火额外完成 231 条同分布 loss 对照。
   50 条/231 条的 judge0_manual 用例仍需沙箱人工,未测部分不填、不宣称。

## 合规红线(打包前核对)

- 包内无 `.env`、真实 Key、学生/敏感数据;训练数据为公开教材摘要 + 自建标准答案 + 开源语料(CC BY-SA 等,逐条溯源)。
- 评测口径诚实:**两套模型均不得宣称"评测提升"**;可写"训练收敛、可复现、输出贴合课程语料风格/领域拟合改善"。

## 待办(提交前回填)

- [x] 材料 05:ServiceID 无需提供(已提供模型文件);
- [ ] 两个 adapter zip 上传 ModelScope/网盘后,把下载地址写回材料 05;
- [ ] (可选)judge0_manual 用例补测后更新各自 `evidence/`。
