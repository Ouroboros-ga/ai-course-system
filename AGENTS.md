# AGENTS.md

## 1. 当前阶段：本地原型 Demo 自主实现

当前项目处于本地原型和 Demo 构建阶段。目标是把 Product 1 从已有的
页面、接口和研究原型推进为可运行、可体验、可持续迭代的完整教学系统。

Agent 默认拥有实现权，可以大胆试验、重构和学习；重点是尽快形成真实的
端到端闭环，而不是维持历史代码的形式不变。允许推进 Phase A--E、G1--G9
以及与其直接相关的前后端、数据库、部署和研究工作。

本阶段的工作原则是：

- 优先完成可体验的产品闭环；
- 允许试错、替换旧实现和局部/模块级重构；
- 用测试、样例数据、日志和文档记录结论，而非假定旧实现正确；
- 每次有意义的改动保持可理解、可运行、可回退；
- 历史 Demo、Shadow 和旧 API 可以被替代，但必须明确迁移或下线语义。

这不是线上生产环境授权。真实学生数据、真实生产数据库、真实密钥和未经
授权的付费外部服务仍不进入开发、测试或提交物。

---

## 2. 默认授权范围

除本文件明确禁止的事项外，Agent 可以自主完成以下工作，无需逐模块等待
批准：

1. 阅读、审计、修复、重构和替换现有前端、后端、配置、测试、文档及构建脚本。
2. 新增、修改或删除本地 Demo 所需的生产代码路径、服务、API、View Model、
   页面、组件、任务、模型和部署配置。
3. 新增数据库表、字段、索引、迁移、种子数据、迁移预检和回滚脚本；允许修正
   旧字段和旧模型的错误语义，但必须提供迁移路径并更新实际消费者。
4. 为 Phase A--E、G1--G9 实现题库、练习与答题、学习证据、图谱治理、认知推荐、
   R2 检索、Citation/Evidence、TeachingAgent、WebResearch、算法可视化、代码实验、
   TTS、数字人和媒体时间轴。
5. 实现白名单算法动画、CodingEduAgent 和独立代码沙箱；可以试验开源方案、
   Docker、独立虚拟环境、模型运行时及本地服务。
6. 新增或重组模块、目录、类、协议和依赖；删除已确认未使用的死代码、过时端点、
   重复实现和占位模块，并同步修改调用方、路由、迁移和测试。
7. 新增单元、集成、端到端、迁移、回归、性能和人工冒烟测试，以及 fixture、fake、
   stub、mock、临时数据库和本地样例数据。
8. 在 `docs/phase1/`、`docs/research/` 或直接相关的模块文档中记录架构决定、
   外部依赖、风险、已知限制、部署和回滚方式。
9. 使用课程能力开关、Demo 配置或明确的发布状态，逐步把新能力接入本地体验；
   新能力不必永久保持 Shadow 状态。

实施时按风险匹配验证强度：小改动至少运行相关测试；跨域、数据库、权限、沙箱或
外部服务改动应增加针对性测试、迁移检查和可操作的回退方案。无需为了试验而维持
已被替代的旧实现。

---

## 3. 硬边界

### 3.1 安全与数据边界

1. 不得把学生代码放入主应用进程执行；代码执行必须经过独立沙箱服务。
2. 不得把真实学生聊天、Memory、身份数据或生产数据库复制到 fixture、日志、
   文档或仓库；Demo 使用合成或经授权且假名化的数据。
3. 不得读取、输出或提交真实 API Key、Token、密码或其他密钥。
4. 不得在自动化测试中调用真实付费 LLM、TTS、PPT、数字人或其他付费服务。
5. 不得让外网资料、LLM 输出或交互频次无证据地直接成为正式掌握度、课程事实或
   已发布图谱关系；它们必须作为可审计候选或独立证据处理。
6. 不得绕过 Course Access v1 的课程、学生、成员和能力校验。

### 3.2 兼容、迁移与重构

1. 允许改变公开 API、请求/响应结构、数据库结构、启动配置和用户可见行为，前提是
   同步更新真实调用方、迁移、测试和文档；对仍在使用的接口保留兼容层，或提供明确
   的版本化/迁移方案。
2. 允许重构或替换核心模块；重构前应识别实际路由、调用链和数据模型，重构后必须
   覆盖主流程和失败/降级路径。
3. 不得静默删除仍有消费者的数据、接口或功能。删除前需迁移消费者，或在本地 Demo
   中明确标记为废弃并给出替代入口。
4. 不得为了“看起来完成”创建未接线的空目录、空类、伪实现或虚构成功状态。

### 3.3 测试与结果诚实性

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
