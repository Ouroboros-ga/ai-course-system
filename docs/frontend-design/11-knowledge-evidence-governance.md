# 课程知识与 Evidence 治理工作台

> 产品定位：教师端第三个P0核心页面，与课程生产工作台、学生学习空间并列。它把知识点、关系、PPT、文档原文、脚本节点和Evidence放进同一审核上下文。它不是GraphRAG页面，也不是只读知识图谱大屏。

## 1. 依据与成熟度

| 能力 | 当前证据 | 产品成熟度 |
|---|---|---|
| 知识点—PPT页映射 | mapping.py、mapping.js、MappingEditor.vue | V1已实现，弹窗体验 |
| 应用映射到脚本 | mapping apply接口 | V1已实现 |
| DocumentIR/Geometry | 冻结领域契约 | Shadow/基础能力，产品数据仍需门禁 |
| Evidence/Citation | evidence/1.0、citation/1.0、internal Evidence API | 冻结契约；当前主要admin/internal |
| 教育图谱节点/关系/审核状态 | edu-graph/1.0领域模型 | 领域代码/Shadow，缺教师产品接口 |
| 图谱快照与active pointer | GraphSnapshot契约和规划 | 需持久化、审核和发布接口 |
| 下游stale传播 | 规划和依赖关系可推导 | 需真实依赖服务与状态存储 |

因此第一阶段不能把页面全部做成“正式可用”。同一页面采用能力分层：

- V1 Mapping模式：接现有真实mapping接口。
- Evidence Shadow模式：仅内部/教师试用，Feature Flag控制。
- Graph Review模式：只有审核队列、权限、持久化和快照接口通过门禁后开放。
- 未接能力显示成熟度说明，不用可点击假按钮。

## 2. 页面目标与进入条件

主要用户：课程owner/editor，以及未来具有reviewer权限的教师。

用户进入时要完成：

1. 检查AI识别的知识点和关系。
2. 对照PPT、原文和脚本判断候选是否可靠。
3. 修正知识点、页码、脚本和先修关系。
4. 确认哪些候选可以进入课程知识快照。
5. 了解修改会让哪些RAG索引、脚本和媒体产物失效。
6. 发布或回退一个可追踪的课程知识快照。

进入条件：课程存在；用户拥有课程查看权限。编辑、审核、发布分别做后端授权，不以是否能进入页面替代。

## 3. 页面布局

### 3.1 顶部上下文栏

字段：返回生产、课程名、资料版本、候选run、active snapshot、未审核数、保存状态、对比版本、发布快照。

发布按钮只在以下条件同时成立时可用：

- 当前候选run已冻结。
- 不存在阻断校验错误。
- accepted节点和语义关系都有Evidence或人工创建记录。
- 先修关系无未解决环。
- 当前用户拥有publish权限。
- 影响检查已完成。

### 3.2 左侧治理轨，280px

Tab：

1. 知识树：章节、知识点、概念、例题等。
2. 审核队列：proposed、needs_review、conflict。
3. 关系：按类型和来源筛选。
4. 映射缺口：无PPT页、无原文、无脚本的节点。

节点行显示名称、类型、审核状态、Evidence数量和警告。默认不展开全图；局部关系视图只展示当前节点一到两跳，避免关系云失去可读性。

### 3.3 中央证据画布

顶部资源Tab：PPT、文档原文、教学脚本。三者共享KnowledgeAnchor。

- PPT：页缩略图、当前页、映射区域、页面角色。
- 文档：页图、block高亮、文本模式、坐标定位。
- 脚本：ScriptNode定位、生成/教师修改标记、版本。
- 对比：左右查看旧版与新版；不在同一视区同时显示四个资源面板。

Evidence定位层级依次为span、block、page、source-only。定位精度降低时明确说明，不能伪造bbox。

### 3.4 右侧候选检查轨，360px

字段：

- 候选类型、名称、别名、关系方向。
- AI/规则来源、runId、sourceVersion。
- Evidence列表、引用状态和定位精度。
- confidence仅作为审核辅助，并显示校准状态；不单独决定accept。
- 结构校验、类型矩阵、重复候选、环检测、冲突原因。
- 审核动作：接受、修改后接受、驳回、稍后处理。
- reviewer、时间、理由、影响范围。

驳回需要选择或输入理由；修改后接受必须保存before/after差异。批量接受只适用于相同规则、无冲突、证据完整的候选。

### 3.5 下游影响抽屉

展示当前修改的依赖结果：

| 对象 | 可能状态 | 典型动作 |
|---|---|---|
| Evidence | current/stale/missing | 重新解析或重新绑定 |
| 知识映射 | current/needs_review | 审核映射 |
| 脚本 | current/stale | 局部重生成/人工编辑 |
| TTS | current/stale | 重生成受影响音频段 |
| 数字人 | current/stale | 重生成受影响节点 |
| RAG索引 | current/rebuild_required/building | 建立新索引并原子切换 |
| 课程发布 | ready/blocked/warning | 进入发布检查 |

影响检查必须由后端依赖服务计算；前端不能根据文件名变化猜测。

## 4. 核心流程

### 4.1 V1知识点—PPT映射

~~~text
选择知识点
→ 查看已有页码
→ 打开PPT页文本
→ 执行自动/AI匹配
→ 查看候选页和依据
→ 人工调整pageStart/pageEnd
→ 保存单点或批量映射
→ 应用到脚本
~~~

当前接口可支持该流程。产品化时将MappingEditor的能力搬入页面中央和右轨，不在生产工作台继续打开巨型弹窗。

### 4.2 图谱候选审核

~~~text
打开needs_review候选
→ 查看类型、关系和所有Evidence
→ 定位PPT/原文/脚本
→ 检查冲突、重复和先修环
→ 接受 / 修改后接受 / 驳回
→ 写入review记录
→ 队列移动到下一项
~~~

AI或LLM只产候选，不直接写入active snapshot。accepted语义节点和关系必须满足Evidence不变量；人工创建也记录reviewer和reason。

### 4.3 修改上游资料

~~~text
上传新资料版本
→ 新DocumentIR run
→ 对比block/页变化
→ 标记旧Evidence stale
→ 生成映射和图谱候选差异
→ 教师审核
→ 计算下游影响
→ 新快照发布
→ 新RAG索引建立并切换
~~~

旧active snapshot在新快照完成前继续服务。解析、审核或索引失败不得破坏现有学生课程。

### 4.4 快照发布与回退

~~~text
冻结候选run
→ 执行质量校验
→ 教师确认发布清单
→ 创建不可变snapshot
→ 原子切换active pointer
→ 记录发布审计
~~~

回退是切换active pointer或创建回退发布记录，不删除新旧快照。若RAG索引与snapshot绑定，二者必须成对切换。

## 5. 数据模型与前端对象

页面不直接消费后端dataclass。前端使用以下ViewModel，详细字段见12-frontend-contracts-and-api-plan.md：

- KnowledgeGovernanceSummary
- KnowledgeNodeView
- KnowledgeRelationView
- MappingCandidateView
- EvidenceAnchorView
- ReviewCandidateView
- GraphSnapshotView
- StaleDependencyView
- ReviewDecisionInput

关键稳定标识必须保留：courseId、artifactId、documentId、unitId、blockId、evidenceId、nodeId、relationId、snapshotId、runId和versionRef。

## 6. 审核状态

| 领域状态 | 页面文案 | 可执行操作 |
|---|---|---|
| proposed | AI/规则候选 | 查看、接受、驳回 |
| needs_review | 待教师检查 | 修正、接受、驳回 |
| accepted | 已接受 | 查看审核、在新run中修订 |
| rejected | 已驳回 | 查看理由、重新生成候选 |
| superseded | 已被新快照替代 | 只读、查看差异 |
| stale Evidence | 来源已更新 | 不允许作为当前依据，重新绑定 |
| suspended Evidence | 暂停使用 | 查看原因、具备权限时恢复 |
| conflict | 存在冲突 | 解决冲突前阻断发布 |

“已接受”不等于“已发布”。只有accepted对象进入已激活snapshot后才是学生端可用知识。

## 7. 加载、空、错、成功和权限

- 首次加载：树、画布、检查轨分别骨架；保持课程顶栏。
- 无候选：区分尚未运行、全部审核完成和筛选无结果。
- Evidence缺失：候选不能自动接受；显示缺失的稳定ID或源对象。
- 定位失败：展示可读文本和页码，禁用精确高亮，不清空候选。
- 版本冲突：保存返回最新reviewVersion，要求刷新或对比，不覆盖他人审核。
- 发布失败：active pointer保持原值，显示失败阶段和安全状态。
- 只读权限：允许查看树、Evidence和审核记录；隐藏编辑/发布操作并说明原因。
- 成功：局部更新队列和审核记录；不弹出连续成功对话框。

## 8. 响应式和键盘

- 大于1360px：280px + 弹性画布 + 360px。
- 1100–1359px：左轨232px，右轨默认折叠。
- 768–1099px：左/右轨抽屉，中央资源Tab。
- 小于768px：只支持查看候选、Evidence和轻量审核；合并、拆分、关系编辑和版本差异提示桌面处理。
- 审核队列使用表格或listbox语义；上下项可键盘切换。
- 树支持方向键；资源Tab支持左右键；画布高亮不阻断屏幕阅读器读取文本。
- 接受、驳回、发布等动作必须有清晰焦点和错误说明。

## 9. 接口实施顺序

### P0：复用现有接口

- GET /mapping/{courseId}
- GET /mapping/{courseId}/pages
- POST /mapping/{courseId}/auto
- POST /mapping/{courseId}/ai-match
- PUT /mapping/{courseId}/nodes/{nodeId}
- PUT /mapping/{courseId}/batch
- POST /mapping/{courseId}/apply

### P1：新增只读聚合与审核接口

- GET /courses/{courseId}/knowledge-governance/summary
- GET /courses/{courseId}/graph/candidates
- GET /courses/{courseId}/graph/candidates/{candidateId}
- POST /courses/{courseId}/graph/reviews
- GET /courses/{courseId}/evidence/{evidenceId}
- POST /courses/{courseId}/dependencies/impact

### P2：快照和发布接口

- POST /courses/{courseId}/graph/runs/{runId}/freeze
- POST /courses/{courseId}/graph/snapshots
- POST /courses/{courseId}/graph/snapshots/{snapshotId}/activate
- POST /courses/{courseId}/graph/snapshots/{snapshotId}/rollback
- GET /courses/{courseId}/graph/snapshots/{snapshotId}/diff

这些是新增契约建议，不替换现有V1路径。所有写接口需要幂等键、reviewVersion或If-Match、防跨课程授权和审计事件。

## 10. 上线门禁

1. V1 mapping回归通过，现有课程映射行为不变。
2. Evidence API能返回真实页面/块数据，不是G4空响应或fake shadow。
3. 审核状态持久化，accepted必须有Evidence的契约测试通过。
4. 快照不可变、active pointer原子切换和回滚演练通过。
5. 课程级权限覆盖查看、编辑、审核、发布。
6. 失败run不改变active V1/V2服务状态。
7. 教师完成至少一轮“候选—证据—审核—快照—回退”可用性测试。
