# 教师/学生产品前端与真实能力实施计划

> 本计划替代上一版“只做两张Mock原型、不改后端”的实施边界。当前已获得前端设计层、后端新增接口和真实算法接入授权；仍必须保持现有公开路径、请求字段、响应结构、数据库生产语义和用户可见主链兼容。GraphRAG、BKT、HMM、LSTM学习困难预测和复杂多智能体仍不进入范围。

## 1. 总体策略

采用四条并行但有门禁的工作流：

1. 前端产品化：角色工作空间、页面、组件、适配层和状态系统。
2. 后端产品接口：新增聚合、权限、任务、版本、审核、Evidence和Memory接口。
3. 算法与领域能力：DocumentIR、Evidence、Citation、教育图谱、学习证据、推荐和Memory。
4. 质量与晋级：offline → Shadow → Canary → production，任何阶段可回到V1。

依赖顺序：

~~~text
稳定ID与权限
→ 前端ViewModel/adapter
→ DocumentIR真实产物
→ Evidence/Citation
→ 知识审核与快照
→ 学生可信问答/教师RAG质量
→ LearningEvent/Evidence
→ 推荐与Memory
~~~

RAG不等待GraphRAG；可信检索先消费DocumentIR和Evidence。交互语义不等待产品页面，但在评测通过前不影响MasteryState和正式推荐。

## 2. 当前基线

### 已完成

- 项目审计、角色流程、信息架构、页面规格、设计系统和组件清单。
- 学生学习空间、教师生产工作台的独立Mock原型。
- DocumentIR、Evidence、Citation、教育图谱、LearningEvent、LearningEvidence、StudentMemory和TaskResult领域契约或代码基础。
- admin/internal Evidence Viewer正式独立路由。

### 尚未产品化

- 完整学生/教师工作空间。
- 知识与Evidence治理页面。
- 统一任务、版本、stale传播和发布门禁。
- 学生Citation授权入口。
- 教师问题/RAG质量聚合。
- 学生建议和Memory正式接口。
- 生产级异常、权限和可访问性验收。

### 立即风险

- 两条prototype路由当前无条件注册，会进入正式构建。
- request.js生产baseURL写死localhost，需要单独配置治理；本计划不顺手改变部署方式，先建立环境配置验收。
- lint脚本带--fix，验证前应先使用只检查模式或确认工作区，避免自动改动无关用户文件。
- StudentMemory registry状态与enums.py头部draft说明不一致，产品接入前必须由契约Owner统一。

## 3. 发布列车

### Release A：核心工作空间产品化

目标：在不依赖未成熟算法的情况下，把现有真实课程、播放、进度、问答、映射和生成能力放进新设计。

包含M0–M4。决赛前优先完成；Evidence仍可保持internal/Shadow。

### Release B：可信课程与证据治理

目标：将真实DocumentIR/Evidence/Citation和教育图谱审核接入教师/学生页面。

包含M5–M7。必须通过G5/G6质量、授权和回滚门禁，不以日期强行上线。

### Release C：学情、建议与Memory

目标：用LearningEvent/Evidence构建可解释建议和可控Memory。

包含M8–M9。只使用经验证的规则和证据；交互语义先Shadow。

## 4. 里程碑

### M0 设计与契约冻结

状态：本轮文档完成后可进入评审。

交付：

- 03–06更新。
- 09教师端、10学生端、11知识治理、12契约/API、13状态权限文档。
- 页面—能力—接口—成熟度矩阵。
- 决策记录：双模式主次交换、知识治理为第三核心页面。

负责人：产品设计、前端、后端契约Owner。

验证：

- 每个页面有角色、入口、区域、状态、权限、接口和优先级。
- 已实现、Shadow、规划和研究能力分开。
- 契约名称与registry/领域代码一致。
- Markdown UTF-8和链接检查通过。

回滚：仅设计文档，无运行时影响。

### M1 前端壳、路由隔离与适配层

依赖：M0。

前端范围：

- Prototype路由仅在DEV或VITE_ENABLE_FRONTEND_PROTOTYPES=true时注册。
- 新建RoleWorkspaceShell、StudentShell、TeacherShell，不立即删除NavigationBar。
- 建立domains/*/adapters和运行时parser。
- 建立统一页面状态、PermissionBoundary和GlobalTaskDock空壳。
- 目标路由先使用alias/Feature Flag，不改变现有深链。
- Token从prototypes作用域迁移到新工作空间作用域，不全局覆盖旧页。

后端范围：无必需改动；只确认权限和环境变量。

完成标准：

- 正式构建不包含可访问prototype路由。
- 旧路由全部可用。
- 新壳关闭Feature Flag时不影响现有页面。
- adapter contract tests覆盖正常、空、非法和未知版本。
- 1440/1024/390无全局溢出。

回滚：关闭workspace flag；保留旧路由与旧页面。

### M2 学生核心页面产品化

依赖：M1。

范围：

- 学生首页和我的课程。
- LearningWorkspace接入课程、目录、播放器、进度和问答。
- 跟随讲解：视频/数字人主画面+PPT辅助画面。
- 课件研习：PPT主画面+笔记本地草稿。
- 前置补学恢复锚点接现有prerequisite接口。
- Citation、Memory、认知建议保持禁用或内部标识，不能用Mock混入正式页。

建议文件边界：

- pages/student/StudentHomePage.vue。
- pages/student/CourseLearningPage.vue。
- domains/learning/adapters/playerAdapter.js。
- domains/learning/stores/learningWorkspace.js。
- shared/states/*。

后端增量：

- 优先新增GET /courses/{courseId}/learning-context聚合接口；若来不及，adapter组合现有接口。
- 进度保存增加optional revision前先做兼容契约和冲突策略。

验证：

- 继续学习、双模式、主次调换、折叠、问答、补学返回。
- 不写Mock数据到生产store。
- 进度失败不阻断播放。
- 旧StudentDashboard和StudentPlayer回归。

回滚：课程级/用户级Feature Flag回旧页面。

### M3 教师生产工作台产品化

依赖：M1；可与M2不同文件域并行。

范围：

- TeacherDashboard外包课程上下文壳、流程轨和检查轨。
- 先复用现有上传、脚本、mapping、TTS、PPT和数字人工具。
- 统一前端LongTaskViewModel，不先强制后端所有provider改造。
- 生成成功与教师确认分离。
- 发布检查先只使用真实可验证规则；未知规则不作为阻断。

后端增量：

- GET /tasks和GET /tasks/{id}聚合现有任务。
- retry创建新taskId并关联parentTaskId。
- GET /courses/{id}/publish-check返回真实阻断和警告。

验证：

- 创建课程到预览完整走查。
- 单节点/批量任务失败、超时、部分成功和重试。
- 离页任务继续且可返回。
- 现有TeacherDashboard行为和API不退化。

回滚：关闭teacher_workspace flag，回旧TeacherDashboard。

### M4 V1知识映射工作区

依赖：M1、M3。

范围：

- 新建KnowledgeGovernanceShell的V1 Mapping模式。
- 将MappingEditor能力迁入独立工作区，但保留旧弹窗作为回退。
- 支持知识点、PPT页文本、单点/批量映射、auto/ai-match和apply。
- Evidence/图谱审核区域只在对应flag开启时出现。

后端：复用现有mapping接口；只修真实契约缺陷，不改变旧响应。

验证：

- 同一课程在新旧编辑器映射结果一致。
- 批量保存、失败恢复和apply回归。
- 无Evidence时页面仍能完成V1映射。
- 移动端只读和桌面提示正确。

回滚：关闭knowledge_governance_ui flag，继续旧MappingEditor。

### M5 DocumentIR与Evidence生产门禁

依赖：现有G1–G4契约、独立算法评测；不依赖M4上线。

算法/后端：

- 真实parser provider通过固定基准，不再用V1映射出的fake IR冒充质量。
- DocumentIR页、block、Geometry、质量warning可回放。
- EvidenceSpan引用真实stable IDs和versionRef。
- 页面渲染、Evidence列表和Citation验证返回真实数据。
- 失败run不改变V1或active V2 pointer。
- 为教师课程范围增加只读Evidence授权，不直接扩大admin端点。

前端：

- SourceEvidenceCanvas接入internal/canary。
- 展示active/stale/suspended和定位精度。
- 坐标异常fail-closed。

验证：

- contract tests、固定文档回放、页面高亮、stale测试、跨课程403。
- Shadow至少满足现有评测方案的运行和回滚门禁。
- 无付费外部服务进入自动化测试。

回滚：关闭document/evidence flag；保留Shadow产物只读审计。

### M6 图谱审核、快照与影响传播

依赖：M5真实Evidence。

后端：

- 持久化candidate、review、snapshot和active pointer。
- accepted节点/语义关系必须有Evidence或人工创建记录。
- 类型矩阵、关系方向、自环、先修DAG由确定性代码校验。
- 新增审核、冻结run、创建/激活/回退snapshot接口。
- 实现依赖影响服务，输出StaleDependency。

前端：

- 开放ReviewQueue、CandidateInspector、SnapshotBar和ImpactPanel。
- 支持接受、修改后接受、驳回、批量安全操作、版本冲突。
- 关系图仅为局部辅助。

验证：

- accepted无Evidence必须失败。
- 并发reviewVersion冲突返回409。
- 快照不可变、原子激活、5分钟内回退演练。
- 修改PPT后stale传播到映射/脚本/媒体/RAG索引。

回滚：active pointer回旧snapshot并关闭graph flag。当前不接GraphRAG。

### M7 学生可信Citation与教师RAG质量

依赖：M5；图谱不是前置依赖。

后端：

- chat/ask增量返回optional citations、validation和answer_scope。
- 学生Citation/Evidence接口执行选课和课程授权。
- 无Evidence或stale时validator可abstain。
- 教师RAG质量聚合verified/partial/mismatch/stale/no_evidence、知识点和问题。

前端：

- 学习空间开放CitationList和EvidencePreview。
- 教师分析开放RAG质量Tab。
- 历史问答记录课程和来源版本。

验证：

- 点击引用定位到正确页/block。
- 不可定位、旧版本、无权限和服务不可用状态。
- 无Evidence不产生伪key。
- 学生不能读取未选课程或其他课程Evidence。

回滚：citation flag回V1答案；旧QA响应仍可消费。

### M8 学情与可解释建议

依赖：LearningEvent/LearningEvidence真实采集和隐私批准。

后端/算法：

- LearningEvent append-only、幂等、更正用新事件。
- LearningEvidence保留eventRefs、provider和sourceVersion。
- 第一版仅规则化使用显式作答、重试、完成和教师任务。
- 互动语义只作为reason/uncertainty上下文，保持Shadow。
- Recommendation除continue外必须有evidenceRefs。

前端：

- 学生建议页和首页建议。
- 教师概览、知识点、学生和问题Tab。
- 所有结论展示证据、时间范围、样本量和不确定性。

验证：

- 无证据不得输出强建议。
- 观看时长和提问次数不能单独得出掌握结论。
- Mock/合成数据不进入真实学生报告。

回滚：关闭recommendation flag；保留学习事实页。

### M9 StudentMemory产品化

依赖：M8、Memory契约状态冲突解决、隐私/删除政策批准。

后端：

- Memory CRUD、consent、export和audit。
- 课程隔离、生命周期、soft/hard delete语义。
- Shadow阶段不注入正式QA。
- Canary只对获批课程开放。

前端：

- Memory列表、来源、原因、失效时间、修改/删除。
- 个性化总开关和课程范围。
- 删除全部和导出流程。

验证：

- 关闭后不生成/使用新Memory。
- 删除和审计语义与政策一致。
- 学生只能读取自己的Memory。
- 低置信敏感信息不自动创建。

回滚：关闭memory flag并停止注入；保留可访问的删除/导出入口直到数据处理完成。

### M10 全面质量与迁移收口

依赖：每个已选择上线的里程碑。

范围：

- 删除已不再使用的兼容薄壳前必须经过真实流量和回归观察。
- 前端性能、错误监控、请求ID和审计。
- WCAG基础验收、浏览器缩放、键盘、字幕和图表替代。
- 统一环境配置，不再在生产baseURL写死localhost。
- 设计Token逐页收口；暗色模式另做验证，不强行同步上线。

## 5. 文件与所有权

| 区域 | Owner | 修改规则 |
|---|---|---|
| frontend/src/router/index.js | 前端壳 | 单一Owner；路由alias和flag集中管理 |
| frontend/src/utils/request.js | 前端基础设施 | 不夹带业务适配；变更需全前端回归 |
| frontend/src/domains/* | 各前端领域 | adapter、parser、store边界 |
| frontend/src/pages/student | 学生前端 | 不直接调用request |
| frontend/src/pages/teacher | 教师前端 | 不直接消费provider字段 |
| frontend/src/prototypes | 设计验证 | DEV/flag隔离，不被正式模块反向依赖 |
| backend/app/platform/document_intelligence | DocumentIR Owner | 遵守冻结stable ID |
| backend/app/platform/evidence/retrieval | Evidence Owner | 保留Evidence ID和fail-closed |
| backend/app/domain/education_graph | Graph Owner | candidate/review/snapshot |
| backend/app/domain/learning | Learning Owner | Event/Evidence/Recommendation |
| backend/app/domain/student_memory | Memory Owner | consent/lifecycle/delete/audit |
| backend/app/api/v1/endpoints | API Owner | 新增兼容端点，课程权限 |
| docs/refactor/product1/contracts | 契约Owner | 按registry审批，不由消费方随意改 |

共享热点router、request、main API注册、数据库migration和contract registry不得多人同时修改。

## 6. 验证矩阵

### 前端

- npm.cmd run build。
- lint使用不自动修复模式；当前npm run lint会--fix，需先确认工作区或增加lint:check。
- adapter和组件单测。
- 浏览器流程：1440×900、1280×720、1024×768、390×844。
- 控制台无error、无全局横向溢出、无死按钮。
- 键盘、焦点、抽屉、Tab、引用定位、任务重试和版本冲突。

### 后端

- 项目venv执行pytest，优先离线fake。
- contract tests、权限测试、幂等、409冲突、503 flag关闭。
- 空库和旧库副本migration测试；生产库不用于测试。
- V1主流程回归、M7 smoke和对应领域专项测试。
- 外部LLM/TTS/PPT/数字人使用fake adapter。

### 数据与算法

- 固定fixture、版本化基准和可重复hash。
- Shadow/Canary报告区分合成、离线和真实用户证据。
- 失败run、partial任务和回滚演练。
- 真实学生数据使用前完成授权、脱敏和最小化。

## 7. 每个里程碑完成定义

1. 实现、Shadow和规划状态在UI及文档一致。
2. 新旧路由和API兼容测试通过。
3. 目标功能有正常、空、错、权限、并发和回滚验证。
4. 没有真实接口的按钮禁用并说明，不用Mock进入生产。
5. Feature Flag默认安全，关闭后回到已验证主链。
6. 文档、契约、测试和截图与代码同一次交付更新。
7. 已知缺口登记到08-open-questions.md，不以“后续优化”掩盖阻断项。

## 8. 推荐执行顺序

当前最合理的顺序是：

~~~text
M1 路由隔离与适配层
→ M2 学生核心页面
→ M3 教师生产工作台
→ M4 V1知识映射工作区
→ M5 DocumentIR/Evidence门禁
→ M7 Citation与RAG质量
→ M6 图谱审核与快照
→ M8 学情建议
→ M9 Memory
→ M10 收口
~~~

M6和M7的顺序特意允许Citation先于完整图谱；这符合Evidence优先、RAG不依赖GraphRAG的架构边界。
