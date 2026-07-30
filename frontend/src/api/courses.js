import request from '@/utils/request.js'

/**
 * 课程空间 API（影子前端切片 0.1）。
 * 全部对接真实 V1 端点，无 mock。响应经 request.js 统一剥离 code/message。
 */

/**
 * 当前学生已选课程（含学习进度与上次学习时间）。
 * GET /document/my-courses → { courses: [...], total }
 * 注意：后端限定 student 角色调用，教师/管理员会得到 403 —— 调用方按
 * 「真实空态」处理，不伪造教师视角的学习列表。
 */
export function getMyCourses() {
  return request.get('/document/my-courses')
}

/**
 * 课程完整详情（课程信息 + 当前激活脚本 + 节点 + 解析信息）。
 * GET /document/course/{courseId} → { course, script, nodes, parse_info }
 */
export function getCourseDetail(courseId) {
  return request.get(`/document/course/${courseId}`)
}

export function getCourseAccess(courseId) {
  return request.get(`/course-access/courses/${courseId}/access`)
}

/**
 * 课程所有者永久删除课程及其课程专属产物。
 * DELETE /document/course/{courseId}
 */
export function deleteCourse(courseId, confirmationTitle) {
  return request.delete(`/document/course/${courseId}`, {
    data: { confirmation_title: confirmationTitle },
  })
}

/**
 * 课程大厅（已发布课程列表）。
 * GET /document/courses
 */
export function getCourseHall(params = {}) {
  return request.get('/document/courses', { params })
}

// ---------------------------------------------------------------------------
// 批次1：邀请码入课与课程关闭
// ---------------------------------------------------------------------------

/**
 * 教师设置/更新课程邀请码。
 * POST /course-access/courses/{courseId}/invite-code
 */
export function setInviteCode(courseId, code = null) {
  return request.post(`/course-access/courses/${courseId}/invite-code`, { invite_code: code })
}

/**
 * 教师清除课程邀请码。
 * DELETE /course-access/courses/{courseId}/invite-code
 */
export function clearInviteCode(courseId) {
  return request.delete(`/course-access/courses/${courseId}/invite-code`)
}

/**
 * 学生通过邀请码加入课程。
 * POST /course-access/courses/join-by-code
 */
export function joinByCode(inviteCode) {
  return request.post('/course-access/courses/join-by-code', { invite_code: inviteCode })
}

/**
 * 教师关闭课程（拒绝新成员，已加入可继续学习）。
 * POST /course-access/courses/{courseId}/close
 */
export function closeCourse(courseId) {
  return request.post(`/course-access/courses/${courseId}/close`)
}

/**
 * 教师重新开放已关闭课程。
 * POST /course-access/courses/{courseId}/reopen
 */
export function reopenCourse(courseId) {
  return request.post(`/course-access/courses/${courseId}/reopen`)
}
