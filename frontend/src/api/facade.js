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

export function getFacadeCourseOverview(courseId) {
  return request.get(`/facade/course/${courseId}/overview`)
}
