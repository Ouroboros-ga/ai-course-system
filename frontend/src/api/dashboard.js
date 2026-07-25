import request from '@/utils/request.js'

/**
 * 仪表盘 API（批次1：课程概览真实待办）。
 * 对接 /api/v1/dashboard 端点。
 * 响应经 request.js 统一剥离 code/message 层，直接返回 data。
 */

/**
 * 首页聚合：继续学习、待办、系统回应。
 * GET /dashboard
 */
export function getHomeDashboard() {
  return request.get('/dashboard')
}

/**
 * 课程概览聚合：继续学习位置、进度、待办（前置知识跳转）、最近理解度分析。
 * GET /dashboard/course/{courseId}
 */
export function getCourseDashboard(courseId) {
  return request.get(`/dashboard/course/${courseId}`)
}
