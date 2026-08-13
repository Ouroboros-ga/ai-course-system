import request from '@/utils/request.js'

const course = (courseId) => encodeURIComponent(courseId)

export const getTeachingConstraints = (courseId) => request.get(`/agent-governance/course/${course(courseId)}/teaching-constraints`)
export const updateTeachingConstraints = (courseId, payload) => request.put(`/agent-governance/course/${course(courseId)}/teaching-constraints`, payload)
export const listTeachingConstraintVersions = (courseId) => request.get(`/agent-governance/course/${course(courseId)}/teaching-constraints/versions`)
export const rollbackTeachingConstraints = (courseId, payload) => request.post(`/agent-governance/course/${course(courseId)}/teaching-constraints/rollback`, payload)
export const previewTeachingConstraints = (courseId, payload) => request.post(`/agent-governance/course/${course(courseId)}/teaching-constraints/preview`, payload)
export const listTeachingConstraintEvaluations = (courseId, limit = 20) => request.get(`/agent-governance/course/${course(courseId)}/teaching-constraints/evaluations`, { params: { limit } })

export const getTeachingToolPolicies = (courseId) => request.get(`/agent-governance/course/${course(courseId)}/tools`)
export const updateTeachingToolPolicies = (courseId, payload) => request.put(`/agent-governance/course/${course(courseId)}/tools`, payload)
export const listBuiltinTeachingTools = () => request.get('/agent-governance/builtin-tools')
