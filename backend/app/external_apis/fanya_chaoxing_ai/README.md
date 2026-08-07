# 泛雅·超星 AI 开放 API 参考兼容包

这是本地 Demo 的可选适配器，参考提供的超星 AI 互动智课开放 API 示例；它不是超星集团认证、发布或官方 SDK。

- 对外基址：`/api/v1/compat`。
- 对外响应：`code`、`msg`、`data`、`requestId`。
- 认证：本包独立校验 `time`、`enc`。生产对接应设置 `FANYA_CHAOXING_AI_COMPAT_STATIC_KEY`；未设置时仅为了本地兼容回退到旧 `STATIC_KEY`。
- 当前真实映射：文本问答、学习进度追踪、节奏调整；全部经既有 Course Access v1 校验。
- 当前明确未提供：外部 URL 课件导入、脚本/媒体资源映射、ASR。它们返回结构化 503，不伪造任务或生成结果。

## 移除

删除整个 `fanya_chaoxing_ai/` 目录即可禁用这组接口。`app.main` 使用可选发现逻辑：目录不存在时不会导入它，也不会影响内部 API、数据模型、迁移或服务启动。

## 已声明的参考接口

| 路径 | 当前行为 |
| --- | --- |
| `POST /qa/interact` | 文本问答；复用 TeachingAgent，并先经 Course Access v1 校验。语音问答明确返回不可用。 |
| `POST /qa/voiceToText` | 返回 `503 ASR_UNAVAILABLE`，不伪造转写结果。 |
| `POST /progress/track` | 在 Course Access v1 校验通过后，更新已有 `LearningProgress`。进度只会单调增加。 |
| `POST /progress/adjust` | 根据传入的理解等级返回确定性的“补充/正常/加速”建议；不写入正式掌握度证据。 |
| `POST /lesson/parse` | 返回 `503 EXTERNAL_URL_IMPORT_UNAVAILABLE`。 |
| `POST /lesson/generateScript` | 返回 `503 SCRIPT_MAPPING_UNAVAILABLE`。 |
| `POST /lesson/generateAudio` | 返回 `503 MEDIA_MAPPING_UNAVAILABLE`。 |

所有响应固定为 `code`、`msg`、`data`、`requestId`。HTTP 失败状态与 `code` 一致；业务能力缺口使用结构化 `503`，而不是返回空的成功任务。

## 签名与资源映射

请求使用参考示例的 MD5 规则：按参数名排序拼接非空参数（排除 `enc`），再拼接静态密钥和 `time`，取大写 MD5。`time` 支持项目时钟格式与参考示例的 `%Y-%m-%d%H:%M:%S`。部署时必须设置独立的 `FANYA_CHAOXING_AI_COMPAT_STATIC_KEY`；仅本地兼容时才会回退到旧 `STATIC_KEY`。

调用前需要完成以下映射：

- 外部课程 ID → `Course.fanya_course_id`；
- 外部用户 ID → `User.fanya_account_id`（为迁移兼容也接受用户名）；
- `lessonId` → 当前映射课程；
- `currentSectionId` → 同一课程脚本的 `ScriptNode.id`。

任何映射缺失、跨课程节点、学校不匹配或 Course Access v1 不允许的请求都会被拒绝。

## 移除语义

删除本目录后，主应用发现不到该可选包，因而不挂载 `/api/v1/compat/*`；其独立签名校验前缀也不会登记。内部 JWT 路由和原有签名白名单均不依赖该目录。
