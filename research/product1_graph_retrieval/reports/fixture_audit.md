# B-G0a micro-contract fixture 审计报告

> Fixture：`micro_contract_v1`  
> Schema：`product1-graph-retrieval-fixture/1.1`  
> 审计日期：2026-07-16

## 结论

Level A micro fixture 已通过 schema、hash、稳定 ID、引用闭合、课程闭包、offset/snippet、分级 qrels、多页映射、split 和 gold 隔离测试。

它只用于证明工具链正确，manifest 明确禁止用来报告 BM25、Dense、Hybrid、Graph 或映射算法效果。

## 冻结规模

| 项目 | 数量 |
| --- | ---: |
| 课程 | 2 |
| source blocks | 22 |
| research Evidence | 22 |
| active corpus chunks | 20 |
| queries | 18 |
| knowledge points | 10 |
| slides | 20 |

覆盖：同词异课、stale-only、无课程 scope、课程内无答案、0/1/2 分级 qrels、七类 query stratum 和多页知识点映射。

## 复现标识

```text
manifest_sha256 = eb4717feb7213f463873c6c6a88b85d695d882542deabc7e59aa94d7b882fb8f
canonical_dataset_sha256 = 309f865cc613f6b063d03e78e45789b8432b6f89d4ec155fcb0311bd30a1ecc0
```

生成器在两个独立普通测试目录中产生逐文件相同字节。时间戳不参与 research ID。

## 测试

标准库 `unittest` 共 18 项通过，覆盖：

- identity/citation/chapter distance；
- manifest/hash/reference/offset/course closure；
- deterministic generation；
- query label leakage；
- human annotation independence/adjudication；
- retrieval/mapping contract-oracle metrics；
- synthetic gold 禁止算法比较；
- P1-00/P1-10 release gate 保持 blocked。

项目 `.venv` 当前没有安装 pytest，因此没有修改依赖或锁文件；使用同一 `.venv` 的标准库 `unittest` 完成验证。

## 未完成门禁

- 真实 Level B 课程材料尚未提供；
- 两名真实团队成员尚未独立标注；
- 人工仲裁尚未完成；
- P1-00 尚未确认；
- P1-10 尚未复核；
- B-R1/B-R2 仍未放行。
