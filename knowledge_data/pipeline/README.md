# 学科知识库构建管线（knowledge_data/pipeline/，DK0）

> **状态（2026-09-08）：抽取规范已废弃于当前路线，抽样能力保留复用。** 用户改用原文切块 + 本地 embedding + 混合检索；现行任务见[CS 语料向量化与 RAG 上线实施计划](../../docs/phase1/2026-09-08_CS语料向量化与RAG上线实施计划.md)。不再按旧 DK0–DK8 开发抽取器或模型裁决。
>
> `prepare_knowledge_sample.py` 的分层抽样、固定种子和文档族隔离复用于 CR0；`ontology.json`、`synthetic_cases.jsonl` 与下文概念变形规则仅保留历史，不作为新 RAG 检索准入/质量证明。新检索问题集与参数配置放 `knowledge_data/corpus/rag/`（拟新增，尚未实现）。
>
> 本目录只放规范与离线评测材料，不放业务数据与密钥。以下保留旧材料格式和现有抽样脚本用法；CR1 尚需实现原始五来源到文档登记/抽样清单的适配。

## 目录

| 路径 | 内容 |
|---|---|
| `ontology.json` | 类型 / 谓词（9 个白名单）/ 状态枚举与拒绝示例；抽取输出的封闭契约 |
| `benchmark/sample_manifest.json` | **合成示例**校准批清单（5 来源 × 200 片段 = 1000），由 `prepare_knowledge_sample.py` 以固定种子生成，仅演示清单格式与族不交划分，不代表真实语料分布 |
| `benchmark/synthetic_cases.jsonl` | 至少 200 条规则可判定的自动挑战用例（8 类 × 28 条 = 224 条），期望由确定性规则给出，被测模型不参与出题与判定 |
| `../corpus/prepare_knowledge_sample.py` | 分层抽样工具：`prepare_sample(manifest, seed, per_source, output_dir)` |

## 抽样用法

```bash
# 用登记清单抽样（manifest 由 DK1 的 discipline_document_versions 投影得到，
# DK0 阶段可用合成 fixture；从不默认访问服务器）
python knowledge_data/corpus/prepare_knowledge_sample.py \
  --manifest <文档登记清单.json> --seed 20260908 --per-source 200 \
  --output-dir <输出目录>
```

- `per_source` 可为整数（每类同额）或 JSON 字典（如 `'{"textbook": 200}'`）。
- 注意两种清单不要混用：抽样输入是**文档登记清单**（`document_id`/
  `family_id`/`chunks`，DK1 起由 `discipline_document_versions` 投影），
  导入/构建 scope 用的是**来源记录清单**（`source_kind`/`external_id`/
  内联 `text`，见 `backend/scripts/import_discipline_corpus.py`）。
- 输出 `sample_manifest.json` 记录种子、分层选择、示例/评估文档族、
  各来源请求/实际数量、字符总量与 token 粗估、选择指纹。
- 相同输入两次执行 `chunk_ids` 完全一致；改动一个文档版本只改变该文档
  相关条目与指纹，不改变其他条目的相对顺序。
- 实际不足配额时如实报告实际数量，不扩充无关内容凑数。

## 自动挑战集（8 类）

`no_knowledge`（无应抽知识）/ `homonym`（同名异义）/ `negation`（否定句）/
`conditional`（条件限定）/ `direction_reversal`（方向反转）/
`version_conflict`（版本冲突）/ `prompt_injection`（提示注入）/
`fabricated_citation`（伪造引文）。每条含 `expected_*` 期望与 `rule`
（确定性判定规则）。没有人工真值时，这些用例衡量的是“规则一致性与
隔离正确性”，不得命名为真实准确率/召回率。

## 合成变形测试约定

- 同义改写不改变概念身份（同一 `concept_id`）；
- 否定 / 条件 / 方向反转必须改变陈述或拒绝（`contradicted` /
  `insufficient` / `quarantine`），不得静默发布肯定形式；
- 期望值由本目录的静态规则给出，不由被测抽取模型生成。

## 诚实边界

- `benchmark/` 内全部 ID（`synth-*`）为合成 fixture，不对应真实文档；
  真实语料统计以 `knowledge_data/corpus/manifest.json`（登记统计）与
  DK0 重建的处理清单为准，不用原始 GB 直接推算概念数量。
- token 粗估口径 `tok-est/1`（见抽样脚本 `estimate_tokens`），只用于
  预算与吞吐估算，不作为计费依据。
