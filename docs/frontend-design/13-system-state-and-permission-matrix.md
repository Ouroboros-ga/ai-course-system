# 全系统状态、权限、版本与异常矩阵

> 目的：补齐两张核心原型之外的生产级边角。所有教师/学生页面都必须复用这些语义；页面可以改变布局，但不能为同一状态发明不同含义。

## 1. 能力成熟度

| 模式 | 用户可见范围 | 数据写入 | 导航规则 |
|---|---|---|---|
| off | 不可见 | 无 | 不注册或不展示 |
| prototype | 开发/评审账号 | 独立Mock | 仅DEV或显式VITE_ENABLE_FRONTEND_PROTOTYPES |
| internal | 管理员/内部测试 | 内部数据 | 独立入口 |
| shadow | 不影响V1结果 | 独立Shadow store | 不向学生返回 |
| canary | 获批课程/账号 | 可回滚隔离数据 | 明确Beta说明 |
| production | 授权用户 | 正式数据 | 正式导航 |

当前prototype路由无条件注册是风险。产品化第一步应将其改为DEV或显式环境变量注册，不能只依赖“不放进导航”。

## 2. 通用请求状态

| 状态 | 页面行为 | 恢复动作 |
|---|---|---|
| initial | 保留稳定壳，局部骨架 | 自动 |
| refreshing | 保留旧数据并显示更新时间 | 继续使用/取消 |
| empty | 说明为什么为空和下一步 | 创建/清除筛选/返回 |
| offline | 保留本地可用内容，标记未同步 | 重连/稍后同步 |
| timeout | 说明请求超时，不自动重复写操作 | 重试 |
| partial | 展示成功区域和失败区域 | 重试失败区域 |
| forbidden | 不泄露资源内容 | 返回/申请权限 |
| unauthenticated | 保存安全草稿后登录 | 重新登录 |
| conflict | 不覆盖新版本 | 对比/刷新/另存草稿 |
| unavailable | 说明服务暂不可用 | 重试/降级 |
| validation_error | 错误贴近字段或对象 | 修正 |
| success | 局部确认和保存时间 | 无连续弹窗 |

异步按钮提交后禁用并显示进行中。重复点击不得产生多个课程、发布版本、审核记录或删除请求。

## 3. 课程与内容状态

### 3.1 课程生命周期

draft、published、archived来自CourseStatus。前端派生：

- unpublished_changes：草稿领先于发布版本。
- blocked：存在发布阻断项。
- warning：可发布但有警告。
- processing：存在影响当前课程的运行中任务。
- stale_content：存在旧产物，不改变CourseStatus。

### 3.2 生产步骤

~~~text
not_started
queued
running
generated
review_required
confirmed
warning
failed
stale
blocked
~~~

generated表示机器产物完成；confirmed表示教师确认。一个步骤可以generated+warning，不能把所有状态压成单枚举。

### 3.3 长任务

后端事实状态：pending、running、succeeded、failed、cancelled、timeout、partial_success。

前端派生：

- retrying：存在新的关联任务。
- stale_result：任务成功但产物版本已过期。
- review_required：任务成功且需要人工检查。

## 4. Citation与Evidence状态

| 领域事实 | 定位精度 | 用户表达 |
|---|---|---|
| active + verified | span/block | 已核对，可定位 |
| active + partial | block/page | 依据可读，定位可能有偏差 |
| active + mismatch | 任意 | 引用与原文不一致 |
| stale | 任意 | 来源已更新，不作为当前依据 |
| suspended | 任意 | 来源暂不用于回答 |
| no_evidence | none | 课程资料不足，停止强结论 |
| API unavailable | none | 来源暂不可打开 |
| forbidden | none | 当前无权访问来源 |

Evidence存在不等于Citation已验证；Citation已验证不等于学生有权限打开原始文件。

## 5. 知识治理状态

候选状态使用proposed、needs_review、accepted、rejected、superseded。额外校验维度：

- evidence_complete。
- type_valid。
- direction_valid。
- no_cycle。
- no_conflict。
- review_current。
- snapshot_eligible。

只有所有阻断校验通过的accepted对象可以进入snapshot。自动accepted阈值必须由评测校准，不写死在前端。

## 6. 学习证据、结论和Memory

### 6.1 三层分离

~~~text
LearningEvent：发生了什么
LearningEvidence：哪些事件支持某个观察
Mastery/Recommendation/Memory：基于证据的可解释候选结论
~~~

页面不得把Event直接渲染为“已掌握”。观看、停留和提问次数只能作为上下文或参与证据。

### 6.2 Memory状态

active、expiring、expired、corrected、soft_deleted。UI还需要：

- personalization_disabled：学生关闭使用。
- pending_deletion：删除处理中。
- deletion_failed：删除失败，可恢复。
- consent_required：尚未授权。

## 7. 权限矩阵

### 7.1 角色与课程范围

| 能力 | 学生 | teacher owner/editor | teacher reviewer | admin/internal |
|---|---|---|---|---|
| 读取已选课程 | 自己选课 | 预览模式 | 预览模式 | 按内部授权 |
| 写学习进度 | 自己 | 否 | 否 | 否 |
| 查看自己的Evidence引用 | 已选课程且可见 | 预览 | 预览 | 内部 |
| 编辑课程 | 否 | 允许 | 默认只读 | 否，除非切换工作空间 |
| 审核知识候选 | 否 | 权限允许时 | 允许 | 内部观察 |
| 发布快照/课程 | 否 | publish权限 | 可建议，不默认发布 | 不默认 |
| 查看聚合学情 | 否 | 自有课程 | 审核课程 | 按授权 |
| 查看单学生证据 | 自己 | 课程授权 | 课程授权 | 严格内部授权 |
| 查看/删除学生Memory | 自己 | 默认不可读全文 | 默认不可读全文 | 隐私流程授权 |
| 管理用户角色 | 否 | 否 | 否 | 允许 |

当前后端只有粗粒度student/teacher/admin时，前端可以先隐藏协作功能，但新增写接口必须预留course permission校验。路由守卫不是安全边界。

## 8. 版本矩阵

| 对象 | 版本/ID | 可变性 | 回退方式 |
|---|---|---|---|
| 原始资料 | artifactId + version | 新版本追加 | 切换引用版本 |
| DocumentIR | documentId/runId/version | run不可变 | active解析指针 |
| Evidence | evidenceId/versionRef | 状态可变，源引用稳定 | 使用旧版只读审计 |
| 脚本 | scriptVersion/snapshot | 快照不可变 | 创建回滚版本 |
| 映射 | mappingVersion | 草稿可编辑 | 恢复已保存版本 |
| 图谱 | snapshotId/ontologyVersion | snapshot不可变 | active pointer |
| 媒体 | artifactRef/sourceVersion | 产物不可变 | 切换产物或重生成 |
| 课程发布 | releaseId | 已发布记录不可变 | 发布新回退版本 |
| 推荐/Memory | sourceVersion/evidenceRefs | 生命周期变更 | corrected/soft_deleted |

前端顶部只显示与当前任务有关的主版本，详情页提供完整矩阵，避免“当前V3”含义不明。

## 9. 高风险操作

| 操作 | 风险说明 | 必须展示 | 恢复 |
|---|---|---|---|
| 删除课程 | 可能影响资料、版本和学生入口 | 删除范围、学生数据、不可恢复项 | 优先归档 |
| 删除Memory | 个性化变化和审计保留 | 单条/全部、软删/硬删、处理时间 | 按政策 |
| 删除映射 | 脚本和RAG可能stale | 下游影响 | 版本恢复 |
| 重新解析 | 新DocumentIR和Evidence | 旧active继续服务 | 回退active |
| 局部重生成 | 覆盖候选产物 | 最小单元、费用/时间、复用产物 | 保留旧产物 |
| 发布课程 | 学生可见变化 | 版本、阻断、警告、确认者 | 新回退发布 |
| 激活图谱快照 | RAG/先修关系变化 | 快照差异、索引状态 | pointer回退 |
| 重建索引 | 服务窗口和版本一致性 | 目标snapshot、切换方式 | 旧索引保留 |

不可逆操作使用确认对话框；可撤销操作优先使用短时撤销条。确认按钮文本写具体动作，不用“确定”。

## 10. 无障碍验收

### 通用

- 正文对比度至少4.5:1；大文本至少3:1。
- 键盘焦点始终可见，Tab顺序符合视觉顺序。
- 图标按钮有可访问名称；输入有label。
- 触控目标至少44×44px。
- 状态不用颜色单独表达。
- 动态错误、保存和任务结果使用适度aria-live。
- prefers-reduced-motion下关闭非必要移动和循环动画。

### 学习

- 视频字幕、倍速和键盘播放控制。
- PPT有页码、标题和文本替代。
- 公式、代码和表格可阅读，不使用图片作为唯一内容。
- 目录tree、模式tabs、智能体drawer均可键盘操作。
- 回到讲解、补学返回和引用关闭恢复触发焦点。

### 教师

- 流程步骤、审核队列和数据表有语义标题。
- 拖拽编辑必须有键盘替代。
- 图表提供数据表或摘要。
- 错误关联具体字段、候选或任务。
- 对话框焦点陷阱、Esc策略和关闭后焦点恢复正确。

## 11. 响应式验收

验证视口：1440×900、1280×720、1024×768、768×1024、390×844。

每个页面检查：

1. 无全局横向溢出。
2. 固定顶栏/底栏不遮挡内容。
3. 抽屉互斥规则正确。
4. 表格关键列保留，次要列进入详情。
5. 教师复杂编辑在移动端明确只读或提示桌面。
6. 中文、公式、代码和长文件名不破坏布局。
7. 浏览器缩放200%时核心操作仍可用。
