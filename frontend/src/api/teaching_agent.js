import request from '@/utils/request.js'

/**
 * 批次4 TeachingAgent API
 *
 * 受控接入：仅在课程 cognitive_analysis 能力开关开启、且当前用户为
 * analytics_eligible（真实学生）时由调用方决定使用本端点。
 * 后端额外校验 course.question.ask 权限与 KG-MEST Shadow 报告作用域；
 * 无报告或未配置时返回 503，调用方必须回退到 V1 /chat/ask。
 *
 * 端点前缀：/api/v1/teaching-agent
 * 响应为扁平结构（无 code/message 包裹），使用 allowFlatResponse 透传。
 */

/**
 * 请求 TeachingAgent 教学响应。
 * POST /teaching-agent/respond
 *
 * @param {Object} payload - 请求参数
 * @param {string} [payload.student_id] - 旧兼容字段；后端会校验它只能等于当前登录用户
 * @param {string} payload.course_id - 课程 ID
 * @param {string} payload.session_id - 学习会话 ID（由前端生成，贯穿一次学习会话）
 * @param {string} payload.message - 学生提问内容
 * @param {string} [payload.resource_id] - 当前学习资源（知识点节点 ID）
 * @param {string} [payload.exercise_id] - 关联练习 ID
 * @param {string} [payload.code_submission_id] - 关联代码提交 ID
 * @param {Object|null} [payload.questionObservation] - 当次提问瞬间的已冻结播放坐标；缺失时仍正常问答
 * @param {boolean} [payload.skipErrorToast=true] - 503/失败时静默回退，不弹错误提示
 * @returns {Promise<Object>} TeachingAgent 响应（含 trace_id/answer/citations 等）
 */
export function respondTeachingAgent(payload) {
  return request({
    url: '/teaching-agent/respond',
    method: 'post',
    data: {
      ...(payload.student_id != null ? { student_id: payload.student_id } : {}),
      course_id: payload.course_id,
      session_id: payload.session_id,
      message: payload.message,
      resource_id: payload.resource_id ?? null,
      exercise_id: payload.exercise_id ?? null,
      code_submission_id: payload.code_submission_id ?? null,
      question_observation: payload.questionObservation ?? null,
    },
    allowFlatResponse: true,
    // Agent 不可用属预期降级场景，调用方负责回退到 V1，不应弹错误提示。
    skipErrorToast: payload.skipErrorToast ?? true,
  })
}

/**
 * 教师/课程管理员针对指定学习者的受控教学分析。
 * 后端要求调用者拥有 analytics.view_member。
 */
export function respondTeachingAgentForLearner(payload) {
  return request({
    url: '/teaching-agent/respond-for-learner',
    method: 'post',
    data: {
      learner_user_id: payload.learner_user_id,
      course_id: payload.course_id,
      session_id: payload.session_id,
      message: payload.message,
      resource_id: payload.resource_id ?? null,
      exercise_id: payload.exercise_id ?? null,
      code_submission_id: payload.code_submission_id ?? null,
    },
    allowFlatResponse: true,
    skipErrorToast: payload.skipErrorToast ?? true,
  })
}

/**
 * 恢复学生学习会话的教学智能体对话历史（Conversation Domain）。
 * GET /teaching-agent/conversations/{course_id}
 *
 * 返回该学习者在本课程内的历史消息（按时间升序），用于刷新 / 重新进入课程后
 * 重建聊天面板。这是产品体验域；Agent Runtime Context / Audit 表仍保持数据
 * 最小化，不暴露原始消息。
 *
 * @param {string|number} courseId - 课程 ID
 * @param {Object} [options]
 * @param {string} [options.sessionId] - 可选：限定某个学习会话
 * @param {number} [options.limit=200] - 返回消息上限
 * @returns {Promise<Object>} { course_id, session_id, messages: [{id, role, content, concept_id, citations, created_at}] }
 */
export function getConversationHistory(courseId, options = {}) {
  return request({
    url: `/teaching-agent/conversations/${courseId}`,
    method: 'get',
    params: {
      session_id: options.sessionId ?? null,
      limit: options.limit ?? 200,
    },
    allowFlatResponse: true,
    skipErrorToast: options.skipErrorToast ?? true,
  })
}

/**
 * 提问反推：把学生近期提问聚合成结构化学习证据信号。
 * GET /teaching-agent/conversations/{course_id}/inference
 *
 * 学习分析不得直接依赖完整 Conversation（AGENTS.md §5.1）；本接口返回结构化
 * 投影（计数、平均提问深度、薄弱标记、trace 引用），不返回原始问题全文。
 *
 * @param {string|number} courseId - 课程 ID
 * @param {Object} [options]
 * @param {string} [options.conceptId] - 可选：限定某个知识点概念 ID
 * @param {number} [options.lookbackDays=14] - 回看窗口天数
 * @returns {Promise<Object>} { student_id, course_id, total_questions, signals: [{concept_id, question_count, avg_inquiry_depth, inferred_weak, ...}] }
 */
export function getQuestionInference(courseId, options = {}) {
  return request({
    url: `/teaching-agent/conversations/${courseId}/inference`,
    method: 'get',
    params: {
      concept_id: options.conceptId ?? null,
      lookback_days: options.lookbackDays ?? 14,
    },
    allowFlatResponse: true,
    skipErrorToast: options.skipErrorToast ?? true,
  })
}
