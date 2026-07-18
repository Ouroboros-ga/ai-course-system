import request from '@/utils/request.js'

/**
 * Course-level APIs reused by the teacher production workspace.
 * These calls deliberately mirror the existing course endpoints; they do not
 * add or reinterpret backend workflow states.
 */
export function getCourseWorkspaceContext(courseId) {
  return request.get(`/document/course/${courseId}`)
}

export function publishCourse(courseId) {
  return request.post(`/document/course/${courseId}/publish`)
}

export function unpublishCourse(courseId) {
  return request.post(`/document/course/${courseId}/unpublish`)
}
