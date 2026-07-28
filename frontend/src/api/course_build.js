import request from '@/utils/request.js'

const base = (courseId) => `/course-build/course/${encodeURIComponent(courseId)}`

export const listBuildMaterials = (courseId) => request.get(`${base(courseId)}/materials`)
/** Upload bytes through the single SourceMaterialVersion -> TaskRecord path. */
export const uploadCourseSourceMaterial = (courseId, file, onUploadProgress) => {
  const body = new FormData()
  body.append('file', file)
  return request.post(`/document/course/${encodeURIComponent(courseId)}/source-materials`, body, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress,
  })
}
export const listBuildMaterialVersions = (courseId, materialId) => request.get(`${base(courseId)}/materials/${encodeURIComponent(materialId)}/versions`)
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

export const listCourseOutlines = (courseId, params = {}) => request.get(`${base(courseId)}/outlines`, { params })
export const createOutlineDraft = (courseId, sourceOutlineVersionId = null) => request.post(`${base(courseId)}/outlines/drafts`, sourceOutlineVersionId ? { source_outline_version_id: sourceOutlineVersionId } : null)
export const createOutlineNode = (courseId, outlineVersionId, payload) => request.post(`${base(courseId)}/outlines/${encodeURIComponent(outlineVersionId)}/nodes`, payload)
export const updateOutlineNode = (courseId, outlineVersionId, nodeId, payload) => request.put(`${base(courseId)}/outlines/${encodeURIComponent(outlineVersionId)}/nodes/${encodeURIComponent(nodeId)}`, payload)
export const publishOutline = (courseId, outlineVersionId) => request.post(`${base(courseId)}/outlines/${encodeURIComponent(outlineVersionId)}/publish`)

export const listTeachingScripts = (courseId, params = {}) => request.get(`${base(courseId)}/scripts`, { params })
export const createTeachingScriptNode = (courseId, scriptVersionId, payload) => request.post(`${base(courseId)}/scripts/${encodeURIComponent(scriptVersionId)}/nodes`, payload)
export const updateTeachingScriptNode = (courseId, scriptVersionId, nodeId, payload) => request.put(`${base(courseId)}/scripts/${encodeURIComponent(scriptVersionId)}/nodes/${encodeURIComponent(nodeId)}`, payload)
export const publishTeachingScript = (courseId, scriptVersionId) => request.post(`${base(courseId)}/scripts/${encodeURIComponent(scriptVersionId)}/publish`)

export const listPatchProposals = (courseId, params = {}) => request.get(`${base(courseId)}/patch-proposals`, { params })
export const createPatchProposal = (courseId, payload) => request.post(`${base(courseId)}/patch-proposals`, payload)
export const decidePatchProposal = (courseId, proposalId, payload) => request.post(`${base(courseId)}/patch-proposals/${encodeURIComponent(proposalId)}/decide`, payload)
