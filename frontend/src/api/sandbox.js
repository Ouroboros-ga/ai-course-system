import request from '@/utils/request.js'

/**
 * 代码沙箱 API（API 契约 §2：sandbox，状态 available）。
 * 端点前缀：/api/v1/sandbox，后端代理 Judge0。
 * 当前是「运行能力」，不是完整实验业务（实验定义/尝试/评分均为 planned）。
 */

/**
 * 沙箱健康检查。
 * GET /sandbox/health → { enabled, available, allowed_languages }
 */
export function getSandboxHealth() {
  return request.get('/sandbox/health', { skipErrorToast: true })
}

/**
 * 允许的编程语言列表。
 * GET /sandbox/languages → { languages: string[] }
 */
export function getSandboxLanguages() {
  return request.get('/sandbox/languages')
}

/**
 * 在课程上下文内执行代码（课程级隔离与审计）。
 * POST /sandbox/course/{courseId}/execute
 * payload: { language, source_code, stdin? }
 */
export function executeCourseCode(courseId, payload) {
  return request.post(`/sandbox/course/${courseId}/execute`, payload, { skipErrorToast: true })
}
