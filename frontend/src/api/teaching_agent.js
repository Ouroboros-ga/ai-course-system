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
 * @param {string} payload.student_id - 学生用户 ID（必须为当前登录用户）
 * @param {string} payload.course_id - 课程 ID
 * @param {string} payload.session_id - 学习会话 ID（由前端生成，贯穿一次学习会话）
 * @param {string} payload.message - 学生提问内容
 * @param {string} [payload.resource_id] - 当前学习资源（知识点节点 ID）
 * @param {string} [payload.exercise_id] - 关联练习 ID
 * @param {string} [payload.code_submission_id] - 关联代码提交 ID
 * @param {boolean} [payload.skipErrorToast=true] - 503/失败时静默回退，不弹错误提示
 * @returns {Promise<Object>} TeachingAgent 响应（含 trace_id/answer/citations 等）
 */
export function respondTeachingAgent(payload) {
  return request({
    url: '/teaching-agent/respond',
    method: 'post',
    data: {
      student_id: payload.student_id,
      course_id: payload.course_id,
      session_id: payload.session_id,
      message: payload.message,
      resource_id: payload.resource_id ?? null,
      exercise_id: payload.exercise_id ?? null,
      code_submission_id: payload.code_submission_id ?? null,
    },
    allowFlatResponse: true,
    // Agent 不可用属预期降级场景，调用方负责回退到 V1，不应弹错误提示。
    skipErrorToast: payload.skipErrorToast ?? true,
  })
}
