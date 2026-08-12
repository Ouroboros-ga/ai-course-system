import request from '@/utils/request.js'

/** Course-bound ResearchAgent API. All paper hits remain supplementary metadata. */
export function getResearchAgentCapabilities(courseId) {
  return request.get(`/research-agent/courses/${courseId}/capabilities`)
}

export function searchResearchPapers(courseId, payload) {
  return request.post(`/research-agent/courses/${courseId}/search`, payload)
}

export function getResearchWorkspace(courseId, workspaceId = null) {
  return request.get(`/research-agent/courses/${courseId}/workspace`, {
    params: workspaceId ? { workspace_id: workspaceId } : undefined,
  })
}

export function runResearchHarness(courseId, payload) {
  return request.post(`/research-agent/courses/${courseId}/workspace/runs`, payload)
}
