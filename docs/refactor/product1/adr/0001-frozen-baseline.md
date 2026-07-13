# ADR-0001: Product 1 冻结基线与 integration 分支

- 状态: Accepted
- 日期: 2026-07-13
- 决策者: P1-00
- 影响范围: 全部 Product 1 Agent

## 背景

Product 1 多 Agent 并行开发需要一个所有人共同引用的冻结基线 SHA 与 integration 分支，避免 Agent 从脏工作树或移动 HEAD 创建分支。`产品一多CodingAgent并行开发任务分配方案.md` §7.1/§7.2 要求每个 Agent 从 P1-00 发布的冻结 SHA 创建分支。

## 既定事实（来自仓库）

| 项 | 值 |
| --- | --- |
| 规划基线 | `feature/r2d-document-ir` @ `d1eea62`（方案撰写时） |
| Product 1 冻结基线 SHA | `f98ce191c17fe8ee25992d93a0adb426c678990d`（`f98ce19`） |
| 冻结基线包含 | 产品定义文档、多 Agent 方案、`.claude/agents/*` 角色定义、`CLAUDE.md`、`settings.json` |
| M7 维护线 | `refactor/codemind-v3` @ `3895002`，仅 hotfix |
| M7 tag | `m7-baseline-20260713` |
| R2D 集成事实线 | `feature/document-kg-v2` |
| Product 1 integration 分支 | `feature/product1-integration` @ `f98ce19`（本 ADR 建立） |

## 决策

1. 以 `f98ce19` 作为 Product 1 当前轮次的冻结基线 SHA。所有第一/二/三批 Agent 的分支须从该 SHA（或其后续经 P1-00 重新冻结的 SHA）创建。
2. 建立 `feature/product1-integration` 分支，指针与基线 SHA 一致，作为 Product 1 集成事实线与 P1-09 共享文件唯一工作区的基线。P1-00 协调文档（`docs/refactor/product1/`）登记于此线。
3. 冻结时工作树干净；`stash@{0}` 等历史 stash 不恢复、不修改。
4. M7 基线（`m7-baseline-20260713` / `refactor/codemind-v3`）只允许 hotfix 流程；禁止把 feature 线反向合入 M7。

## 第一批 Agent 分支与 worktree（均基于 f98ce19）

| Agent | 分支 | worktree |
| --- | --- | --- |
| P1-01 | `agent/p1-01-document-ir` | `E:/smartcarb/worktrees/ai-course-p1-01` |
| P1-07 | `agent/p1-07-learning-cognition` | `E:/smartcarb/worktrees/ai-course-p1-07` |
| P1-08 | `agent/p1-08-safety-governance` | `E:/smartcarb/worktrees/ai-course-p1-08` |
| P1-10 | `agent/p1-10-quality-gate` | `E:/smartcarb/worktrees/ai-course-p1-10` |

worktree 位于仓库同级 `E:/smartcarb/worktrees/`，不嵌套于主仓库内。

## 重新冻结规则

当 integration 线出现新的、所有受影响 Owner 确认的基线点（例如 G1 契约合流后），P1-00 发布新的冻结 SHA 并更新本 ADR 或追加 ADR。在新的冻结 SHA 发布前，后续批次 Agent 仍从当前冻结 SHA 分支。

## 合规检查

- 任何 Agent 分支的 `git merge-base <branch> f98ce19` 必须等于 `f98ce19`（或更新的冻结 SHA）。
- 任何 Agent 不得从 `refactor/codemind-v3` 或 M7 tag 直接创建 feature 分支。
