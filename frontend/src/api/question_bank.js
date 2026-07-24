import request from '@/utils/request'

/**
 * Phase B 题库管理与题源映射 API。
 *
 * 对接 /api/v1/question-bank 与 /api/v1/question-mapping 端点。
 * 响应经 request.js 统一剥离 code/message 层，直接返回 data。
 */

// ── 题库管理 ──────────────────────────────────────────────

/**
 * 未分配题目列表（尚未关联到任何课程的题源）。
 * GET /question-bank/unassigned
 * @param {Object} params - 分页/筛选参数
 */
export function listUnassignedQuestions(params = {}) {
  return request.get('/question-bank/unassigned', { params })
}

/**
 * 课程题库列表。
 * GET /question-bank/course/{courseId}
 * @param {number} courseId
 * @param {Object} params - 分页/筛选参数
 */
export function listCourseQuestions(courseId, params = {}) {
  return request.get(`/question-bank/course/${courseId}`, { params })
}

/**
 * 分配题目到课程。
 * POST /question-bank/assign
 * @param {Object} data - { question_ids, course_id, ... }
 */
export function assignQuestions(data) {
  return request.post('/question-bank/assign', data)
}

/**
 * 更新单个题目。
 * PUT /question-bank/course/{courseId}/{questionId}
 * @param {number} courseId
 * @param {number} questionId
 * @param {Object} data
 */
export function updateQuestion(courseId, questionId, data) {
  return request.put(`/question-bank/course/${courseId}/${questionId}`, data)
}

/**
 * 发布课程题库。
 * POST /question-bank/course/{courseId}/publish
 * @param {number} courseId
 * @param {Object} data
 */
export function publishQuestions(courseId, data) {
  return request.post(`/question-bank/course/${courseId}/publish`, data)
}

/**
 * 获取题目版本历史。
 * GET /question-bank/course/{courseId}/{questionId}/versions
 * @param {number} courseId
 * @param {number} questionId
 */
export function getQuestionVersions(courseId, questionId) {
  return request.get(`/question-bank/course/${courseId}/${questionId}/versions`)
}

/**
 * 检索课程题目。
 * POST /question-bank/course/{courseId}/search
 * @param {number} courseId
 * @param {Object} data - 检索条件
 */
export function searchCourseQuestions(courseId, data) {
  return request.post(`/question-bank/course/${courseId}/search`, data)
}

/**
 * 提交答题尝试。
 * POST /question-bank/course/{courseId}/{questionId}/attempt
 * @param {number} courseId
 * @param {number} questionId
 * @param {string|Object} studentAnswer
 */
export function submitAttempt(courseId, questionId, studentAnswer) {
  return request.post(`/question-bank/course/${courseId}/${questionId}/attempt`, {
    student_answer: studentAnswer,
  })
}

// ── 题源映射 ──────────────────────────────────────────────

/**
 * 课程题源映射列表。
 * GET /question-mapping/course/{courseId}
 * @param {number} courseId
 * @param {Object} params - 分页/筛选参数
 */
export function listMappings(courseId, params = {}) {
  return request.get(`/question-mapping/course/${courseId}`, { params })
}

/**
 * 生成题源映射（AI EduAgent）。
 * POST /question-mapping/course/{courseId}/generate
 * @param {number} courseId
 * @param {Object} data - 可指定 question_id 进行单题重跑
 */
export function generateMappings(courseId, data = {}) {
  return request.post(`/question-mapping/course/${courseId}/generate`, data)
}

/**
 * 更新单个映射。
 * PUT /question-mapping/course/{courseId}/{mappingId}
 * @param {number} courseId
 * @param {number} mappingId
 * @param {Object} data - { page_start, page_end, knowledge_points, ... }
 */
export function updateMapping(courseId, mappingId, data) {
  return request.put(`/question-mapping/course/${courseId}/${mappingId}`, data)
}

/**
 * 更新映射状态（锁定/解锁/拒绝）。
 * POST /question-mapping/course/{courseId}/{mappingId}/status
 * @param {number} courseId
 * @param {number} mappingId
 * @param {Object} data - { status: 'locked' | 'teacher_edited' | 'rejected' }
 */
export function updateMappingStatus(courseId, mappingId, data) {
  return request.post(`/question-mapping/course/${courseId}/${mappingId}/status`, data)
}

/**
 * 获取映射版本历史。
 * GET /question-mapping/course/{courseId}/{mappingId}/versions
 * @param {number} courseId
 * @param {number} mappingId
 */
export function getMappingVersions(courseId, mappingId) {
  return request.get(`/question-mapping/course/${courseId}/${mappingId}/versions`)
}
