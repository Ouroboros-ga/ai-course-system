# ADR-0002: 第一批并行启动 (P1-01 / P1-07 / P1-08 / P1-10)

- 状态: Accepted
- 日期: 2026-07-13
- 决策者: P1-00
- 影响范围: P1-01、P1-07、P1-08、P1-10

## 背景

依《分配方案》§6 依赖图与 §11 推荐组织，第一批同时启动的 Agent 为 P1-01、P1-07、P1-08、P1-10。这四者均直接依赖冻结基线，彼此无契约依赖，可真正并行。P1-03 可同时起草 Evidence，但实现须等待 P1-01 stable block/geometry 冻结，故不进入第一批实现。

## 决策

启动第一批四个 Agent，各自在专属 worktree 与分支上实现**契约 + contract test**，目标 Gate 为 **G1 Contract**。

| Agent | 契约产出 | 目标 Gate | 上游依赖 |
| --- | --- | --- | --- |
| P1-01 | `DocumentIR`/block union、`Geometry`/`Polygon`、`SourceArtifact`、`ParserRun`/`Provenance`/`QualityReport` | G1 | 仅冻结基线 |
| P1-07 | `LearningEvent`、`LearningEvidence`/`MasteryState`、`MasteryProviderResult`（Provider 仅接口） | G1 | 仅冻结基线 |
| P1-08 | `SafetyPolicy`、`SafetyDecision`、`SourceAccessDecision`、`AuditEvent` | G1 | 仅冻结基线 |
| P1-10 | 测试基建骨架：fake 能力扩展、金标目录、contract test 框架、评测 runner 占位 | G1（基建） | 仅冻结基线 |

## 启动约束（对所有第一批 Agent 共同适用）

1. **只做契约与离线 contract test**，不接公开上传/问答/播放器主链，不写 ORM/Migration，不改共享文件。
2. **不 commit、不 push、不 merge、不 rebase**（CLAUDE.md 与各角色卡均禁止）。实现完成后产出完成报告，由 P1-00 review，提交需用户明确授权。
3. 严守各自角色卡的 Allowed/Forbidden 文件清单；越界需求写 integration proposal。
4. 启动前必须按角色卡“Startup report”报告：身份、分支、HEAD SHA、worktree 路径、`git status --short`、allowed/forbidden、已读文档、契约版本、实现与测试计划。
5. worktree 意外脏、所需改动属于其他 Owner、依赖契约未冻结、需装依赖、需生产数据/凭证、与 M7 冲突 -> 停下报告，不擅自编辑。
6. 测试用 fake/离线 fixture，不调用真实外部服务；contract test 与质量金标分开（质量金标本轮暂不要求，G2/G5 再补）。

## 完成判据（G1 准入）

- 契约模块在专属目录内，schema/ID/scope/delete 语义均有 contract test 覆盖。
- `git diff --check` 无空白错误；改动文件均在 Allowed 列表内。
- 完成报告含：files changed、contract version、tests executed + 真实结果、tests not run、external services（应为 none）、remaining limitations、integration proposal（如有）、`git diff --stat`/`--name-only`/`git status --short`。
- P1-10 出具独立 contract test 结果；业务 Agent 不得自行宣布 Gate 通过。

## 后续衔接

- G1 通过后：P1-02（须 P1-01 minor 冻结）、P1-03（须 P1-01 stable block/geometry 冻结）进入第二批；P1-04、P1-05 进入第三批；P1-06 须 P1-07 `LearningEvent`/`LearningEvidence` 冻结后启动。
- P1-09 贯穿各批次，仅在对应 Gate 后接线共享文件。
