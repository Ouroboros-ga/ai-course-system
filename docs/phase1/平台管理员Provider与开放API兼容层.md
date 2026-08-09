# 平台管理员、Provider 与开放 API 兼容层

更新：2026-08-09。本文记录本地原型中的当前实现，不代表线上生产发布状态。

## 已实现

- 平台管理员 API：`/api/v1/admin/integrations` 与 `/api/v1/admin/users`。
- LLM、TTS、PPT 配置保存到 `platform_integration_configs`；密钥以 Fernet 加密保存，读取只返回 `key_configured` 与末四位。
- 更新配置使用 `expected_version` 乐观锁；在无密钥、Base URL 或模型配置时 fail-closed。
- 账户只有一个 `username`：管理员可按 ID、用户名、角色、启用状态分页筛选，并更新用户名、全局 `user/admin` 角色、启用状态和密码。右上角、个人中心和管理员表格均使用同一个 `username`；数字用户 ID 保持不变。登录先匹配用户名，输入全为数字且未命中用户名时再按用户 ID 登录。
- 用户在个人中心可修改自己的用户名；密码修改必须先验证原密码。用户名修改保留 ID，且对重名返回明确冲突；旧 `real_name` 仅保留为泛雅等外部资料，不再作为账户昵称。
- 密码重置递增 `auth_version`，含该版本声明的 JWT 立即失效。
- 新增 `/app/admin` 的用户管理与 LLM/TTS/PPT 设置 UI；API Key 为空表示保留已有密钥。
- 新增隔离的 `/api/v1/compat/*` 泛雅·超星 AI **示例协议参考兼容包**，采用 `code/msg/data/requestId` 外壳并独立校验 `time/enc`。它位于 `backend/app/external_apis/fanya_chaoxing_ai/`，由 `main.py` 可选发现；仅在该包挂载时才登记其独立签名校验前缀。删除该目录仅取消这组路由，内部 JWT 路由、数据模型和 Course Access API 不被改变。该名称不表示超星集团官方认证或发布。

## 角色迁移

`UserRole` 的正式持久化值为 `user/admin`。`teacher/student` 只作为旧 JWT、旧泛雅同步输入和旧代码别名读取后归一为 `user`；不再创建全局教师角色。课程教学权限继续由 `CourseMembership`、`CourseRole.TEACHER/OWNER`、`CourseCapability` 和 `PlatformPermissionAssignment` 解析。

迁移 `0041` 将已有 `student/teacher` 统一为 `user`，并添加 `auth_version`、平台集成配置和管理员审计表。针对早期数据库实际保存的大写 `TEACHER/STUDENT`，纠正迁移 `0043` 会把 `TEACHER` 账号升级为全局 `ADMIN`，补齐 `platform.admin` 授权，并把 `STUDENT` 归一为 `USER`；迁移可重复执行且不改课程成员的 `CourseRole.TEACHER`。回滚会把 `user` 降为旧系统可识别但最低权限的 `student`，不会尝试伪造已无法恢复的 teacher 区分。

全局角色与显式平台授权必须保持一致：管理后台把用户提升为 `admin` 时同步补发有效的 `platform.admin` 分配，降级为 `user` 时撤销该分配（`platform_admin_service._sync_admin_assignment`）；`init_users.py` 创建的演示管理员同样补齐分配。迁移 `0044`（可重入）为 `role=ADMIN` 但缺 `platform.admin` 的存量账号回填分配，并撤销已降级账号遗留的 `ADMIN` 授权。课程内加入（邀请码/选课）不再校验 `user.role`，任何活跃用户（含管理员）都可作为学习者加入课程。

## Provider 运行时边界

管理员保存的配置先做无内容的可达性探针，探针失败不会写入新配置；成功后进程内 Provider Manager 再原子替换 LLM/TTS/PPT 客户端。PPT 的 Base URL 不再固定为代码常量。多进程实例的配置通知/轮询尚未实现，当前每个进程需在自身内执行刷新。

测试环境不会发起付费调用；健康探针也不提交 prompt、音频或 PPT 生成请求。

## 超星规范映射与限制

PDF 示例接口映射为 `/api/v1/compat/lesson/*`、`/api/v1/compat/qa/*`、`/api/v1/compat/progress/*`。文本问答、`progress/track` 与 `progress/adjust` 均先解析既有泛雅用户/课程标识并经 Course Access v1 校验；`lessonId` 目前必须等同于已映射课程，`currentSectionId` 必须是同课程脚本节点 ID。外部 URL 下载、ASR、脚本/媒体资源映射与未映射标识返回明确的 `COMPAT_ADAPTER_UNAVAILABLE`、`ASR_UNAVAILABLE`、`SECTION_MAPPING_UNAVAILABLE` 或 `USER_OR_COURSE_NOT_FOUND`，不返回伪造成功。

现有 `/api/v1/platform/syncCourse`、`/api/v1/platform/syncUser` 保持为迁移兼容入口，不重复注册；泛雅传入的 `teacher/student` 只会归一为平台 `user`，课程教师语义改由课程成员关系与平台权限维护。

## 代码证据与验证

- 模型/服务：`backend/app/models/platform_admin_model.py`、`backend/app/services/platform_admin_service.py`、`backend/app/services/platform_provider_manager.py`。
- 迁移：`backend/alembic/versions/20260807_1400_0041_platform_admin.py`、`backend/alembic/versions/20260807_1800_0043_upgrade_legacy_teacher_roles.py`。
- 路由：`backend/app/api/v1/endpoints/user.py`、`backend/app/api/v1/endpoints/admin_platform.py`、`backend/app/external_apis/fanya_chaoxing_ai/router.py`；后者由 `backend/app/main.py::_mount_optional_fanya_chaoxing_ai_compat` 可选挂载。
- 前端：`frontend/src/app/pages/admin/PlatformAdminPage.vue`、`frontend/src/app/pages/account/AccountPage.vue`、`frontend/src/components/profile/LoginIn/login/Login.vue`、`frontend/src/api/admin_platform.js`。
- 已运行：账户收敛后的平台管理员服务测试（3 passed）与 Vite production build；此前迁移 `0040 → 0041 → 0040` SQLite 演练、`tests/test_fanya_chaoxing_ai_compat.py`（5 passed）及该包/挂载代码 `compileall`。兼容包测试不会调用付费 Provider。
