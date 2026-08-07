import request from '@/utils/request.js'

/**
 * 笔记 API（批次1：笔记持久化）。
 * 对接 /api/v1/notes 端点，将浏览器本地笔记替换为后端持久化。
 * 响应经 request.js 统一剥离 code/message 层，直接返回 data。
 */

/**
 * 列出当前用户在指定课程的笔记。
 * GET /notes?course_id={courseId}
 */
export function listNotes(courseId) {
  return request.get('/notes', { params: { course_id: courseId } })
}

/**
 * 获取当前用户的课程笔记汇总（资源库「课程笔记」课程列表）。
 * GET /notes/summary → { items: [{ course_id, course_title, note_count, last_updated_at }] }
 */
export function listNoteSummaries() {
  return request.get('/notes/summary')
}

/**
 * 创建笔记。
 * POST /notes
 */
export function createNote(data) {
  return request.post('/notes', data)
}

/**
 * 更新笔记。
 * PUT /notes/{noteId}
 */
export function updateNote(noteId, data) {
  return request.put(`/notes/${noteId}`, data)
}

/**
 * 删除笔记。
 * DELETE /notes/{noteId}
 */
export function deleteNote(noteId) {
  return request.delete(`/notes/${noteId}`)
}
