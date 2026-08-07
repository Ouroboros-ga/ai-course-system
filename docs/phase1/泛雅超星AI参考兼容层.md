# 泛雅·超星 AI 参考兼容层

更新：2026-08-07。本文记录本地 Demo 的可选外部 API 适配包。它参考提供的“超星 AI 互动智课服务系统开放 API 设计规范与示例”PDF，不表示超星集团的官方认证、发布或 SDK。

## 目标与隔离边界

适配包位于 `backend/app/external_apis/fanya_chaoxing_ai/`，对外前缀为 `/api/v1/compat`。它只转换外部协议的签名和响应外壳，内部能力仍通过既有 Course Access v1、TeachingAgent 与进度模型执行；不会复制内部 JWT API、数据模型或迁移。

`backend/app/main.py` 只做可选发现。删除 `fanya_chaoxing_ai/` 目录后：

- 不再注册 `/api/v1/compat/*`；
- 不再登记该包自己的签名校验前缀；
- 内部 API、数据模型、数据库迁移和服务启动保持不变。

## 协议与当前能力

响应统一为 `code`、`msg`、`data`、`requestId`。参考示例的 `time`、`enc` MD5 签名由适配包自行校验；生产对接须配置独立的 `FANYA_CHAOXING_AI_COMPAT_STATIC_KEY`，本地兼容才可回退到 `STATIC_KEY`。

| 参考端点 | 当前语义 |
| --- | --- |
| `POST /qa/interact` | 文本问答复用 TeachingAgent，并先做 Course Access v1 校验。 |
| `POST /qa/voiceToText` | 明确返回 `503 ASR_UNAVAILABLE`。 |
| `POST /progress/track` | 经授权后更新既有 `LearningProgress`，进度单调增加。 |
| `POST /progress/adjust` | 返回确定性的补充/正常/加速建议，不写正式掌握度证据。 |
| `POST /lesson/parse` | 返回 `503 EXTERNAL_URL_IMPORT_UNAVAILABLE`。 |
| `POST /lesson/generateScript` | 返回 `503 SCRIPT_MAPPING_UNAVAILABLE`。 |
| `POST /lesson/generateAudio` | 返回 `503 MEDIA_MAPPING_UNAVAILABLE`。 |

外部 `courseId` 必须映射到 `Course.fanya_course_id`，`userId` 应映射到 `User.fanya_account_id`，`lessonId` 与当前映射课程对应，`currentSectionId` 必须属于同一课程脚本节点。缺少映射、跨课程节点、学校不匹配或无课程能力时均拒绝，不伪造成功。

## 验证

已运行：

```text
backend/.venv/Scripts/python.exe -m pytest \
  tests/test_fanya_chaoxing_ai_compat.py \
  tests/test_m4a_route_contract.py -q
12 passed, 4 warnings
```

测试只使用本地测试数据库与 Fake/Mock 路径，未调用付费 LLM、TTS、ASR 或外部泛雅服务。
