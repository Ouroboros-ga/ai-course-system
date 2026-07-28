import request from '@/utils/request.js'

const base = (courseId) => `/course-editor/course/${encodeURIComponent(courseId)}`

export const getOutline = (courseId) => request.get(`${base(courseId)}/outline`)
export const createOutlineNode = (courseId, payload) => request.post(`${base(courseId)}/outline/nodes`, payload)
export const updateOutlineNode = (courseId, nodeId, payload) => request.patch(`${base(courseId)}/outline/nodes/${encodeURIComponent(nodeId)}`, payload)
export const reorderOutline = (courseId, nodeIds) => request.post(`${base(courseId)}/outline/reorder`, { node_ids: nodeIds })
export const lockOutlineNode = (courseId, nodeId) => request.post(`${base(courseId)}/outline/nodes/${encodeURIComponent(nodeId)}/lock`)

export const getTeachingScripts = (courseId) => request.get(`${base(courseId)}/scripts`)
export const updateTeachingScript = (courseId, scriptNodeId, payload) => request.patch(`${base(courseId)}/scripts/${encodeURIComponent(scriptNodeId)}`, payload)
export const lockTeachingScript = (courseId, scriptNodeId) => request.post(`${base(courseId)}/scripts/${encodeURIComponent(scriptNodeId)}/lock`)

export const listBuildProposals = (courseId) => request.get(`${base(courseId)}/proposals`)
export const createBuildProposal = (courseId, payload) => request.post(`${base(courseId)}/proposals`, payload)
export const decideBuildProposal = (courseId, proposalId, accepted) => request.post(`${base(courseId)}/proposals/${encodeURIComponent(proposalId)}/decide`, { accepted })

// Teacher-facing controlled preparation Agent.  It only returns/persists a
// PatchProposal; accepting a proposal remains a separate explicit action.
export const runPrepAgentCommand = (courseId, instruction) => request.post(`${base(courseId)}/prep-agent/commands`, { instruction })
export const getPrepAgentNodeEvidence = (courseId, nodeId) => request.get(`${base(courseId)}/prep-agent/evidence/${encodeURIComponent(nodeId)}`)

export const getPptMappingState = (courseId) => request.get(`${base(courseId)}/ppt-mapping`)
export const updatePptMapping = (courseId, outlineNodeId, payload) => request.patch(`${base(courseId)}/ppt-mapping/${encodeURIComponent(outlineNodeId)}`, payload)
export const generateCoursePpt = (courseId, payload = {}) => request.post(`${base(courseId)}/ppt/generate`, payload, { timeout: 300000 })
export const uploadExistingPpt = (courseId, file, options = {}) => {
  const formData = new FormData()
  formData.append('file', file)
  return request.post(`${base(courseId)}/ppt/upload`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: options.timeout ?? 300000,
    onUploadProgress: options.onUploadProgress,
  })
}
export const publishCourseBuild = (courseId) => request.post(`${base(courseId)}/publish`)
export const getPublishedCourseContent = (courseId) => request.get(`${base(courseId)}/published-content`)
export const getPublishedLearningUnits = (courseId) => request.get(`${base(courseId)}/published-learning-units`)
