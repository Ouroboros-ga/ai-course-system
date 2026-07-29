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
  // Legacy production workspace now delegates to the release-gated facade.
  // It can no longer flip Course.status without freezing a CourseRelease.
  return request.post(`/course-editor/course/${courseId}/publish`)
}

export function unpublishCourse(courseId) {
  return request.post(`/document/course/${courseId}/unpublish`)
}
