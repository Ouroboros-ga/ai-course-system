# Product 1 权限架构重构 Goal

> 2026-08-07 更新：平台全局身份已收敛为 `user/admin`；`teacher/student` 仅作为历史输入兼容读取后归一。历史库中实际保存为大写 `TEACHER` 的账号由迁移 `0043` 升级为全局管理员并补齐 `platform.admin`，课程内的 owner/teacher/student 继续通过 Course Access v1 解析，不得用全局 role 代替课程授权。实施证据见 [平台管理员、Provider 与开放 API 兼容层](平台管理员Provider与开放API兼容层.md)。

## 目标

将系统从“用户全局 `student / teacher / admin` + `Course.teacher_id` +
`StudentEnrollment`”重构为统一的权限解析模型：

```text
已认证用户
  → 平台权限
  → 有效课程成员关系
  → 课程能力开关
  → 成员权限覆盖
  → 有效课程权限与参与模式
```

课程资源的运行时访问结论只能由该链路给出。旧用户角色、课程
`teacher_id` 和选课记录只作为一次性迁移输入与历史审计数据，不能继续
作为课程端点的授权依据。

## 交付范围

1. 新增平台权限分配、课程成员、课程能力和课程参与模式的数据模型。
2. 统一的 `EffectivePermissionResolver`、FastAPI 权限依赖和稳定错误码。
3. 将所有带 `course_id` 的读取、建设、成员、统计、播放、引用、问答、
   图谱、实验、认知和智能体端点迁移到统一依赖。
4. 前端改为消费课程 access/capabilities View Model；不得再以全局角色
   近似当前课程角色。
5. 一次性、幂等的数据迁移：旧课程所有者转为 `owner`，有效选课转为
   `student`，旧管理员转为显式平台管理员权限。
6. 完整权限矩阵、跨课程隔离、失效成员、覆盖权限、能力禁用、教师预览
   学情排除、迁移和回滚测试。

## 权威模型

### 平台权限

平台权限只处理跨课程治理：`platform.admin`、`platform.course.create`、`platform.course.audit`、
`platform.user.manage`、`platform.safety.manage`、`platform.capability.manage`。
它们不自动伪造普通成员关系；只有明确的 `platform.admin` 可按审计规则
执行跨课程管理操作。

### 课程成员

角色为 `owner`、`teacher`、`teaching_assistant`、`student`、`observer`；
成员状态为 `invited`、`pending`、`active`、`withdrawn`、`removed`、
`completed`、`archived`。只有 `active` 成员可以取得课程权限。

### 有效权限

```text
role default permissions
+ explicit grants
- explicit denies
∩ enabled course capabilities
∩ active membership
∩ platform hard boundaries
```

### 学情参与模式

`learner`、`teacher_preview`、`staff_test`、`observer` 必须由后端生成。
仅 `active student + learner + analytics_eligible` 可以进入正式进度、认知、
课程统计、推荐训练或排行计算。

## 失败关闭与回滚

- 缺失成员、状态非 active、能力缺失、权限未声明或作用域不匹配，一律
  返回拒绝，不降级到旧 `user.role` 或 `teacher_id` 判断。
- 数据迁移先执行预检，发现无法归属、重复冲突或无效用户时报告并停止，
  不部分放量。
- 旧字段保留只读审计期；回滚通过切回已验证的数据库快照与部署版本，
  而不是在新代码中恢复双重授权路径。

## 不在本 Goal 内

- 不改变既有公开 URL、请求字段或成功响应字段；新增 access/capabilities
  View Model 是补充接口。
- 不实现 BKT、HMM、DKT、GraphRAG 或与权限无关的产品功能。
- 不读取生产学生数据作为测试样本，也不在自动化测试调用真实外部服务。

## 完成门禁

1. 全部课程端点不再直接以 `current_user['role']`、`teacher_only`、
   `student_only` 或 `course.teacher_id` 作授权结论。
2. 前端没有以全局教师/管理员身份推断课程教师身份的逻辑。
3. 数据迁移在空库、历史库、重复成员和失效选课场景中可重复执行。
4. 权限矩阵和关键主线回归全部通过，且无跨课程访问回归。
5. 迁移、部署、回滚和剩余历史字段退役计划可审计。
