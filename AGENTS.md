# AGENTS.md

## 1. 当前阶段

当前阶段目标是：

> Product 1 Phase A：前后端契约对齐；并为已授权的 Phase B--E 建立可验证、可回滚的生产化实现路径。

8 月初决赛前，以现有功能稳定和兼容性为最高优先级。

所有审计、测试、文档和可测试性工作都必须服务于：

- 不退化；
- 不破坏；
- 不误报；
- 可验证；
- 可回滚。

本阶段允许 Product 1 的契约、学习闭环、课程知识图谱、认知推荐和
Evidence 生产化工作；不授权无关的 V3.1 全量重构。

---

## 2. 当前阶段允许的工作

默认允许进行以下工作：

1. 阅读和审计现有代码、配置、文档和测试。
2. 在 `docs/phase1/` 下新增第一阶段审计与测试文档。
3. 新增或完善自动化测试。
4. 新增测试 fixture、stub、fake client 和 Mock。
5. 配置临时测试数据库、临时目录和测试环境变量。
6. 修复测试发现、测试隔离和测试基础设施问题。
7. 在确实无法建立测试时，进行最小的行为保持型可测试性修改。
8. 记录现有缺陷、风险、未实现功能和后续重构建议。
9. Phase A：新增兼容性的公开 View Model、课程能力声明、公开 ID、
   权限、错误和降级契约，以及其前后端测试。
10. Phase B：新增 Quiz/题库/答题尝试/学习证据的生产模型、迁移、API、
    教师管理能力与测试；允许在正式数据库结构中新增表和字段，但不得
    静默改变既有字段语义或破坏既有 API。
11. Phase C/D：接入经课程隔离、版本化、可回滚的 LearningEvent、
    评分证据、GraphSnapshot、认知推荐和图谱治理能力。未隔离的学生
    代码不得在主应用进程执行；代码执行必须经独立沙箱服务。
12. Phase E：在获得材料授权、隐私处理、人工校对和可回滚方案后，接入
    真实 DocumentIR/Evidence Shadow 与逐步 Canary；不得通过删除
    admin-only/503 保护直接把 Shadow 暴露给学生。

每项生产化改动仍必须有迁移、回滚、课程/学生作用域校验和自动化测试。
真实学生数据仅可在获授权的最小范围内使用，并必须假名化、访问受控、
不得进入测试 fixture 或提交仓库。

---

## 3. 禁止范围

### 3.1 禁止实现未来能力

1. 禁止实现计算机学科垂类能力。
2. 禁止实现 BKT。
3. 禁止实现 HMM。
4. 禁止实现 LSTM 学习困难预测。
5. 禁止实现 GraphRAG。
6. 禁止实现复杂多智能体竞争、协商、投票或反思系统。
7. 禁止仅为了符合规划文档而创建未使用的目录、类和占位模块。

### 3.2 禁止破坏兼容性

1. 禁止改变公开 API 路径。
2. 禁止改变现有请求字段。
3. 禁止改变现有响应结构。
4. 禁止改变数据库生产结构。
5. 禁止改变数据库现有字段语义。
6. 禁止改变启动方式。
7. 禁止改变用户可见行为。
8. 禁止删除现有功能。
9. 禁止未经授权拆分或重写核心业务模块。
10. 禁止因代码风格问题顺手进行大范围重构。

### 3.3 禁止不可信测试行为

1. 禁止调用真实付费 LLM 服务执行自动化测试。
2. 禁止调用真实付费 TTS 服务执行自动化测试。
3. 禁止调用真实 PPT 生成服务执行自动化测试。
4. 禁止调用真实数字人服务执行自动化测试。
5. 禁止读取生产 API Key、Token 或其他密钥。
6. 禁止使用生产数据库运行测试。
7. 禁止删除失败测试以获得全绿结果。
8. 禁止无理由增加 `skip`、`xfail` 或忽略规则。
9. 禁止弱化有效断言以迎合现有实现。
10. 禁止只断言 Mock 固定字符串而不验证业务调用关系。
11. 禁止伪造功能状态、准确率、性能数据和测试结果。

---

## 4. 文档处理原则

历史材料用于审计，不作为真实实现证据。

以下内容不得直接作为功能已完成的依据：

- README；
- ARCHITECTURE；
- 旧比赛申报材料；
- 功能规划；
- V3.1 重构文档；
- 产品宣传文案；
- 未验证的测试数据。

设计文档与实际代码不一致时，必须以以下证据为准：

1. 实际注册的路由；
2. 实际执行的函数和调用链；
3. 数据库模型；
4. 前端真实调用；
5. 可运行行为；
6. 自动化测试；
7. 命令输出。

本阶段原则上不得直接修改历史比赛材料和旧规划文档。

发现历史文档描述不准确时，应记录到：

```text
docs/phase1/功能现状审计表.md
```

---

## 5. Course-access architecture (effective immediately)

The Course Access v1 architecture is the sole authorization model for any
runtime operation that reads, changes, generates, publishes, or delivers
course-scoped data.

### 5.1 Authoritative runtime sources

Authorization decisions must be resolved from the following models and the
shared resolver in `backend/app/services/course_access_service.py`:

1. `CourseMembership`: a user's effective role, membership status, and
   per-course overrides.
2. `CourseCapability`: whether a course capability is available, experimental,
   shadow-only, or disabled.
3. `PlatformPermissionAssignment`: explicit, auditable cross-course platform
   powers.
4. `CourseAccessContext`, `course_permission`, and
   `require_course_permission`: the shared request-time enforcement path.

`User.role`, `Course.teacher_id`, and `StudentEnrollment` are legacy
compatibility/migration inputs only. They must not be used as a fallback
authorization source, and a request must never silently acquire a course role
because of one of those fields.

### 5.2 Required behavior

1. Every registered endpoint that accepts or derives a `course_id` must
   establish course scope before accessing course data, then enforce the
   relevant course permission and capability.
2. Missing, inactive, suspended, or mismatched membership must fail closed
   with the stable authorization error; do not return filtered or partial
   course data.
3. A new course must establish its owner membership, default capabilities, and
   necessary creator platform assignment through
   `establish_course_access_baseline` in the same unit of work.
4. Enrollment, re-enrollment, withdrawal, and removal must update
   `CourseMembership` via the shared lifecycle helpers, not only the legacy
   enrollment table.
5. Cross-course administration must require an explicit
   `PlatformPermissionAssignment`; a global role is not enough.
6. Platform-wide or account-owned operations that are not course-scoped must
   use an explicit platform permission. Do not disguise them as a course-owner
   shortcut.
7. Frontend code must consume the course access/capability view model. It must
   not infer "current-course teacher" from the global user role or from UI
   state.

### 5.3 Migration and rollback gate

1. Before any access-control migration, run
   `access_control_preflight` against the target database and stop on orphaned
   course owners, orphaned enrollments, or ambiguous mappings.
2. The backfill is idempotent and marked by `access-control-v1`; it may not
   overwrite an existing explicit membership, capability, or platform grant.
3. Every created access-control row carries the migration batch identity.
   `rollback_access_control_backfill` may remove only rows from that batch.
4. Database rollback is a deployment companion to application rollback, not a
   runtime recovery mechanism. Never run it on a live system while the new
   application version is serving traffic.
5. Do not use production data as a test fixture. Test migrations use an
   isolated temporary database and must verify both idempotency and rollback
   scope.

### 5.4 Compatibility and verification

1. Existing public paths and response fields remain compatible unless an
   explicitly versioned contract changes them. New access information is added
   through the public course-access view model.
2. Changes to course authorization require regression coverage in
   `backend/tests/test_course_access.py`, including cross-course denial,
   capability denial, lifecycle transitions, migration preflight, and rollback.
3. Frontend changes require both unit coverage and a production build check.
4. When legacy behavior and the new model conflict, record the compatibility
   decision and its evidence in `docs/phase1/`; do not introduce an untracked
   role-check exception.
