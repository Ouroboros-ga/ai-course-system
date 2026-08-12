import request from '@/utils/request.js'

/**
 * 课程权限与成员 API（API 契约 §2：course-access，状态 available）。
 * 端点前缀：/api/v1/course-access
 * 响应经 request.js 统一剥离 code/message。
 *
 * 注意：members 端点当前只返回 user_id/role/status/joined_at，不返回姓名。
 * 页面必须如实呈现 user_id，不得伪造姓名；姓名聚合由 planned facade 承担。
 */

/**
 * 课程成员列表（需要 membership.view 权限）。
 * GET /course-access/courses/{courseId}/members
 * → { course_id, members: [{ user_id, role, status, analytics_excluded, joined_at, left_at }] }
 */
export function listCourseMembers(courseId) {
  return request.get(`/course-access/courses/${courseId}/members`)
}

/**
 * 新增/修改成员角色与状态（需要 membership.role.change 权限）。
 * PUT /course-access/courses/{courseId}/members/{memberUserId}
 * payload: { role, status, permission_overrides? }
 * 约束：不能通过此接口修改课程所有者（后端 400/403）。
 */
export function upsertCourseMember(courseId, memberUserId, payload) {
  return request.put(`/course-access/courses/${courseId}/members/${memberUserId}`, payload)
}

/**
 * 课程能力开关（ capabilities ）。
 * GET /course-access/courses/{courseId}/capabilities
 */
export function getCourseCapabilities(courseId) {
  return request.get(`/course-access/courses/${courseId}/capabilities`)
}

/**
 * 更新课程能力开关（需要 course.edit 权限）。
 * PUT /course-access/courses/{courseId}/capabilities
 */
export function updateCourseCapabilities(courseId, payload) {
  return request.put(`/course-access/courses/${courseId}/capabilities`, payload)
}

/**
 * Toggle the currently supported, code-sandbox-only experiment platform.
 * This narrow endpoint is available to a course teacher and cannot alter
 * unrelated course capability switches.
 */
export function updateCodeSandboxExperimentPlatform(courseId, enabled) {
  return request.put(`/course-access/courses/${courseId}/experiment-platform`, { enabled })
}
