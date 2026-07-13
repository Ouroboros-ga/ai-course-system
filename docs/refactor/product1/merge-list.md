# Product 1 合流顺序与 Gate 映射 (Merge List)

> Owner: P1-00。本文件定义 G0–G6 各 Gate 的进入条件、可合流内容、禁止内容与负责人。任何合流须 P1-00 审批 + P1-10 独立门禁结论。

## Gate 定义（依《分配方案》§8.1）

| Gate | 进入条件 | 可合流内容 | 禁止内容 | 负责人 |
| --- | --- | --- | --- | --- |
| **G0 基线冻结** | Git 干净策略、M7 tag、所有 Owner 确认 | 规划、ADR、基线报告 | 生产接线 | P1-00 |
| **G1 Contract** | schema/ID/scope/delete contract tests 通过 | P1-01、P1-03、P1-07、P1-08 的契约 | ORM/Migration、公开 API | P1-00 + P1-10 |
| **G2 Isolated Implementation** | 各模块离线单元/contract tests 通过 | Provider、Evidence、规则、viewer 独立组件 | 默认启用、V1 写入 | P1-00 + P1-10 |
| **G3 Shadow Integration** | P1-09 接入且默认 `v1_only` | shadow artifacts、trace、diff | 更新 V1 业务表/前端默认体验 | P1-09 + P1-10 |
| **G4 Persistence/API** | Migration 副本测试和 API contract 通过 | 新表、新 optional DTO、只读 UI | preferred 默认开启 | P1-09 + P1-10 |
| **G5 Canary** | 质量、权限、回滚、M7 全通过 | 白名单 1%/5%/25% | 自动全量 | P1-00 + 运维 |
| **G6 Preferred** | 人工批准和持续指标通过 | `v2_preferred_with_v1_fallback` | `v2_only` 自动开启 | P1-00 |

## 当前 Gate 状态

- **G0**: ✅ 完成（2026-07-13）。冻结 SHA `f98ce19`，M7 tag `m7-baseline-20260713`，integration 分支 `feature/product1-integration` 已建。见 ADR-0001。
- **G1**: 🔄 进行中。第一批 P1-01/P1-07/P1-08/P1-10 已启动，目标产出契约 + contract test。见 ADR-0002。
- G2–G6: 未开始。

## 合流顺序（依赖驱动）

1. **G1 契约**：P1-01（DocumentIR/Geometry）-> 解锁 P1-02、P1-03 实现；P1-07（LearningEvent）-> 解锁 P1-06；P1-08（SafetyDecision）；P1-10（测试基建）。四者可并行合流到各自分支，P1-00 review 后登记 `frozen-major`。
2. **G2 隔离实现**：P1-02 Provider、P1-03 Evidence/Retrieval、P1-04 Viewer、P1-05 Graph、P1-06 Memory、P1-07 规则 baseline 各自独立组件合流；禁止默认启用。
3. **G3 Shadow**：P1-09 把已验收模块以 `v1_only` + shadow 接入主链；只写独立 run/artifact/table。
4. **G4 持久化/API**：P1-09 Migration（独立 PR、旧库副本、down/逻辑回滚）+ 新 optional DTO + 只读 UI。
5. **G5 Canary**：白名单灰度，质量/权限/回滚/M7 全通过。
6. **G6 Preferred**：人工批准后 `v2_preferred_with_v1_fallback`；`v2_only` 不得自动开启。

## Feature Flag 默认值（G3 起）

| Flag | 默认 | 说明 |
| --- | --- | --- |
| `DOCUMENT_PIPELINE_VERSION` | `v1_only` | 非法值 fail-closed |
| `KNOWLEDGE_GRAPH_PIPELINE_VERSION` | `v1_only` | 非法值 fail-closed |
| `DOCUMENT_KG_RUNTIME_MODE` | `v1_only` | 非法值 fail-closed |
| 记忆/学情/安全各独立 flag | 关闭 | 不与 DocumentIR 总开关捆绑 |

## 合流检查命令（在仓库根执行，依《分配方案》§12）

```powershell
git status --short
git branch --show-current
git diff --check
git diff --stat
git diff --name-only
git diff --cached --stat

backend\.venv\Scripts\python.exe -m pytest backend\tests\product1 -q
backend\.venv\Scripts\python.exe -m pytest backend\tests -q

Set-Location frontend
npm.cmd run build
Set-Location ..

powershell -ExecutionPolicy Bypass -File backend\scripts\m7_preflight.ps1
git status --short
```

## 合流报告必含项

修改范围、Owner、契约版本、验证命令、真实结果、未运行项、历史失败对比、Feature Flag 默认值、Migration 影响、外部服务是否真实调用、限制、回滚方法。
