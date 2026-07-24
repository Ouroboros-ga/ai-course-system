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
 * 课程大厅（已发布课程列表）。
 * GET /document/courses
 */
export function getCourseHall(params = {}) {
  return request.get('/document/courses', { params })
}
