import request from '@/utils/request.js'

const base = (courseId) => `/media/course/${encodeURIComponent(courseId)}`

export const listMediaGenerationJobs = (courseId) => request.get(`${base(courseId)}/generation-jobs`)
export const createMediaGenerationJob = (courseId, payload) => request.post(`${base(courseId)}/generation-jobs`, payload)
export const retryMediaGenerationJob = (courseId, jobId) => request.post(`${base(courseId)}/generation-jobs/${encodeURIComponent(jobId)}/retry`)
export const executeMediaTtsJob = (courseId, jobId, payload) => request.post(`${base(courseId)}/generation-jobs/${encodeURIComponent(jobId)}/execute-tts`, payload)
export const listMediaReleases = (courseId) => request.get(`${base(courseId)}/releases`)
export const createMediaRelease = (courseId, payload) => request.post(`${base(courseId)}/releases`, payload)
export const activateMediaRelease = (courseId, releaseId) => request.post(`${base(courseId)}/releases/${encodeURIComponent(releaseId)}/activate`)
export const withdrawMediaRelease = (courseId, releaseId) => request.post(`${base(courseId)}/releases/${encodeURIComponent(releaseId)}/withdraw`)
