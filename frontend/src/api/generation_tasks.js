import request from '@/utils/request.js'

/** Existing task endpoints; no new backend status is introduced here. */
export function getCourseTtsStatus(courseId) {
  return request.get(`/document/course/${courseId}/tts-status`)
}

export function getCourseVideoTasks(courseId) {
  return request.get(`/video-gen/course/${courseId}/tasks`)
}

export function generateCourseVideos(courseId, payload) {
  return request.post(`/video-gen/course/${courseId}/generate`, payload)
}
