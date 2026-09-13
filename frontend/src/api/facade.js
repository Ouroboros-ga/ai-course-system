import request from '@/utils/request.js'

/**
 * Page Design 的聚合读模型。
 *
 * 课程可见性由服务端的 CourseMembership + CourseCapability 解析；客户端只
 * 消费返回的 role/access/capabilities，不再从 User.role 或 teacher_id 推断。
 */
export function getHomeFacade(params = {}) {
  return request.get('/facade/home', { params })
}

export function listFacadeCourses(view, params = {}) {
  return request.get('/facade/courses', { params: { view, ...params } })
}

/**
 * `GET /facade/courses` 的**条目数组**。
 *
 * ⚠️ 该端点返回的是 `{ items, next_cursor, total, has_next }`（游标分页协议），
 * **不是裸数组**。直接 `courses.value = await listFacadeCourses('building')`
 * 会把整个信封对象当数组用：`courses[0]` 与 `courses.length` 都是 undefined，
 * 表现为「课程下拉不出现 + courseId 为空」——而 courseId 为空又会连累下游
 * 拼出 `/app/course//experiments` 这类不存在的路径，点击后直接落到首页
 * （2026-09-13 教师页实测）。
 *
 * 统一走这个包装；页面里不要再手写解包。
 */
export async function listFacadeCourseItems(view, params = {}) {
  const data = await listFacadeCourses(view, params)
  return Array.isArray(data?.items) ? data.items : []
}

export function getFacadeCourseOverview(courseId) {
  return request.get(`/facade/course/${courseId}/overview`)
}

export function getLearningContext(courseId) {
  return request.get(`/facade/course/${courseId}/learning-context`)
}

export function recordLearningEvent(courseId, payload) {
  return request.post(`/facade/course/${courseId}/learning-events`, payload)
}

export function completeLearningAction(courseId, params) {
  const query = new URLSearchParams(params).toString()
  return request.post(`/facade/course/${courseId}/learning-actions/complete?${query}`, null)
}

export function getLearningAnalytics(courseId, params = {}) {
  return request.get(`/facade/course/${courseId}/analytics`, { params })
}

export function getStudentLearningAnalytics(courseId, studentId, params = {}) {
  return request.get(`/facade/course/${courseId}/analytics/students/${studentId}`, { params })
}
