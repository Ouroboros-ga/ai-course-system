import request from '@/utils/request.js'

const base = (courseId) => `/course-editor/course/${encodeURIComponent(courseId)}`

export const getOutline = (courseId) => request.get(`${base(courseId)}/outline`)
export const createOutlineNode = (courseId, payload) => request.post(`${base(courseId)}/outline/nodes`, payload)
export const updateOutlineNode = (courseId, nodeId, payload) => request.patch(`${base(courseId)}/outline/nodes/${encodeURIComponent(nodeId)}`, payload)
export const reorderOutline = (courseId, nodeIds) => request.post(`${base(courseId)}/outline/reorder`, { node_ids: nodeIds })
export const lockOutlineNode = (courseId, nodeId) => request.post(`${base(courseId)}/outline/nodes/${encodeURIComponent(nodeId)}/lock`)
export const unlockOutlineNode = (courseId, nodeId) => request.post(`${base(courseId)}/outline/nodes/${encodeURIComponent(nodeId)}/unlock`)
export const deleteOutlineNode = (courseId, nodeId) => request.delete(`${base(courseId)}/outline/nodes/${encodeURIComponent(nodeId)}`)

export const getTeachingScripts = (courseId) => request.get(`${base(courseId)}/scripts`)
export const updateTeachingScript = (courseId, scriptNodeId, payload) => request.patch(`${base(courseId)}/scripts/${encodeURIComponent(scriptNodeId)}`, payload)
export const lockTeachingScript = (courseId, scriptNodeId) => request.post(`${base(courseId)}/scripts/${encodeURIComponent(scriptNodeId)}/lock`)

export const listBuildProposals = (courseId, status = null) => request.get(
  `${base(courseId)}/proposals`,
  status ? { params: { status } } : undefined,
)
export const createBuildProposal = (courseId, payload) => request.post(`${base(courseId)}/proposals`, payload)
export const decideBuildProposal = (courseId, proposalId, accepted) => request.post(`${base(courseId)}/proposals/${encodeURIComponent(proposalId)}/decide`, { accepted })

// Teacher-facing controlled preparation Agent.  It only returns/persists a
// PatchProposal; accepting a proposal remains a separate explicit action.
export const runPrepAgentCommand = (courseId, instruction, outlineNodeId = null, action = null) => request.post(
  `${base(courseId)}/prep-agent/commands`,
  {
    instruction,
    ...(outlineNodeId ? { outline_node_id: outlineNodeId } : {}),
    ...(action ? { action } : {}),
  },
  { skipErrorToast: true },
)
export const runPrepAgentBatchAction = (courseId, action) => request.post(
  `${base(courseId)}/prep-agent/batch-actions`,
  { action },
  { timeout: 300000, skipErrorToast: true },
)
export const getPrepAgentNodeEvidence = (courseId, nodeId) => request.get(`${base(courseId)}/prep-agent/evidence/${encodeURIComponent(nodeId)}`)

export const getPptMappingState = (courseId) => request.get(`${base(courseId)}/ppt-mapping`)
export const updatePptMapping = (courseId, outlineNodeId, payload) => request.patch(`${base(courseId)}/ppt-mapping/${encodeURIComponent(outlineNodeId)}`, payload)
export const getPptMappingWorkspace = (courseId, materialVersionId, params = {}) => request.get(
  `${base(courseId)}/ppt-mapping/workspace`,
  { params: { material_version_id: materialVersionId, ...params } },
)
export const savePptMappings = (courseId, mappings) => request.put(`${base(courseId)}/ppt-mapping`, { mappings })
export const matchPptMapping = (courseId, payload) => request.post(
  `${base(courseId)}/ppt-mapping/match`,
  payload,
  { timeout: 300000, skipErrorToast: true },
)
export const optimizePptMapping = (courseId) => request.post(`${base(courseId)}/ppt-mapping/optimize`, {}, { timeout: 300000, skipErrorToast: true })
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
export const publishCourseBuild = (courseId, payload = {}) => request.post(`${base(courseId)}/publish`, payload)
export const getPublishedCourseContent = (courseId) => request.get(`${base(courseId)}/published-content`)
export const getPublishedLearningUnits = (courseId) => request.get(`${base(courseId)}/published-learning-units`)
