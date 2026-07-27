import request from '@/utils/request.js'

const base = (courseId) => `/course-build/course/${encodeURIComponent(courseId)}`

export const listBuildMaterials = (courseId) => request.get(`${base(courseId)}/materials`)
export const createBuildMaterial = (courseId, payload) => request.post(`${base(courseId)}/materials`, payload)
export const listBuildMaterialVersions = (courseId, materialId) => request.get(`${base(courseId)}/materials/${encodeURIComponent(materialId)}/versions`)
export const markBuildMaterialParse = (courseId, materialId, payload) => request.post(`${base(courseId)}/materials/${encodeURIComponent(materialId)}/parse`, payload)
export const getBuildStep = (courseId, stepName) => request.get(`${base(courseId)}/steps/${encodeURIComponent(stepName)}`)
export const updateBuildStep = (courseId, stepName, payload) => request.put(`${base(courseId)}/steps/${encodeURIComponent(stepName)}`, payload)
export const lockBuildStep = (courseId, stepName, payload = {}) => request.post(`${base(courseId)}/steps/${encodeURIComponent(stepName)}/lock`, payload)
export const unlockBuildStep = (courseId, stepName) => request.post(`${base(courseId)}/steps/${encodeURIComponent(stepName)}/unlock`)
export const runBuildValidation = (courseId) => request.post(`${base(courseId)}/validate`)
export const getBuildValidation = (courseId, gateRunId) => request.get(`${base(courseId)}/validate/${encodeURIComponent(gateRunId)}`)
export const listBuildReleases = (courseId) => request.get(`${base(courseId)}/releases`)
export const createBuildRelease = (courseId, payload) => request.post(`${base(courseId)}/releases`, payload)
export const publishBuildRelease = (courseId, releaseId, payload = {}) => request.post(`${base(courseId)}/releases/${encodeURIComponent(releaseId)}/publish`, payload)
export const rollbackBuildRelease = (courseId, targetReleaseId) => request.post(`${base(courseId)}/releases/rollback`, { target_release_id: targetReleaseId })
