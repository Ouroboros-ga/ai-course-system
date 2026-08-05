import request from '@/utils/request.js'

const base = (courseId) => `/media/course/${encodeURIComponent(courseId)}`

export const listMediaGenerationJobs = (courseId) => request.get(`${base(courseId)}/generation-jobs`)
export const createMediaGenerationJob = (courseId, payload) => request.post(`${base(courseId)}/generation-jobs`, payload)
export const retryMediaGenerationJob = (courseId, jobId, payload) => request.post(`${base(courseId)}/generation-jobs/${encodeURIComponent(jobId)}/retry`, payload)
export const executeMediaTtsJob = (courseId, jobId, payload) => request.post(`${base(courseId)}/generation-jobs/${encodeURIComponent(jobId)}/execute-tts`, payload)
export const listMediaReleases = (courseId) => request.get(`${base(courseId)}/releases`)
export const createMediaRelease = (courseId, payload) => request.post(`${base(courseId)}/releases`, payload)
export const getMediaRelease = (courseId, releaseId) => request.get(`${base(courseId)}/releases/${encodeURIComponent(releaseId)}`)
export const buildAvatarCues = (courseId, releaseId, payload) => request.post(`${base(courseId)}/releases/${encodeURIComponent(releaseId)}/avatar-cues`, payload)
export const buildPptManifest = (courseId, releaseId, payload = {}) => request.post(`${base(courseId)}/releases/${encodeURIComponent(releaseId)}/ppt-manifest`, payload)
export const activateMediaRelease = (courseId, releaseId) => request.post(`${base(courseId)}/releases/${encodeURIComponent(releaseId)}/activate`)
export const withdrawMediaRelease = (courseId, releaseId) => request.post(`${base(courseId)}/releases/${encodeURIComponent(releaseId)}/withdraw`)
export const getMediaProviderHealth = () => request.get('/media/providers/health')
// Learner-facing immutable media release.  This is intentionally separate
// from the authoring release APIs above so the player consumes its own contract.
export const getCoursePlayback = (courseId, config = {}) => request.get(`${base(courseId)}/playback`, config)
