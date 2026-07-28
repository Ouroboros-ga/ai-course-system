import request from '@/utils/request.js'

export function listMyAvatarProfiles() {
  return request.get('/avatar-profiles/me')
}

export function createAvatarProfile(payload) {
  return request.post('/avatar-profiles', payload)
}

export function listAvatarSourceMedia(avatarId) {
  return request.get(`/avatar-profiles/${encodeURIComponent(avatarId)}/source-media`)
}

export function requestAvatarSourceUploadIntent(avatarId, payload) {
  return request.post(`/avatar-profiles/${encodeURIComponent(avatarId)}/source-media/upload-intent`, payload)
}

export function uploadAvatarSourceMedia(uploadUrl, file, headers = {}, options = {}) {
  // Local storage's signed upload URL includes /api/v1, while request.js has
  // that prefix as its base URL.  Strip it once to avoid /api/v1/api/v1/...
  // and preserve the raw File body for the controlled upload endpoint.
  const relativeUrl = uploadUrl.startsWith('/api/v1/') ? uploadUrl.slice('/api/v1'.length) : uploadUrl
  return request.put(relativeUrl, file, {
    headers,
    timeout: options.timeout ?? 300000,
    onUploadProgress: options.onUploadProgress,
    skipRequestSigning: true,
  })
}

export function confirmAvatarSourceMedia(avatarId, sourceMediaId) {
  return request.post(`/avatar-profiles/${encodeURIComponent(avatarId)}/source-media/${encodeURIComponent(sourceMediaId)}/confirm`)
}

export function createAvatarPreparationJob(avatarId, payload = {}) {
  return request.post(`/avatar-profiles/${encodeURIComponent(avatarId)}/prepare`, payload)
}

export function listAvatarPreparationJobs(avatarId) {
  return request.get(`/avatar-profiles/${encodeURIComponent(avatarId)}/preparation-jobs`)
}

export function listCourseAvatarProfiles(courseId) {
  return request.get(`/courses/${encodeURIComponent(courseId)}/available-avatar-profiles`)
}

export function getCourseAvatarBinding(courseId) {
  return request.get(`/courses/${encodeURIComponent(courseId)}/media/avatar-binding`)
}

export function setCourseAvatarBinding(courseId, payload) {
  return request.put(`/courses/${encodeURIComponent(courseId)}/media/avatar-binding`, payload)
}

export function publishCourseAvatarBinding(courseId, bindingId) {
  return request.post(`/courses/${encodeURIComponent(courseId)}/media/avatar-binding/${encodeURIComponent(bindingId)}/publish`)
}
