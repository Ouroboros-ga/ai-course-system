import request from '@/utils/request.js'

const course = (courseId) => encodeURIComponent(courseId)

export const getTeachingConstraints = (courseId) => request.get(`/agent-governance/course/${course(courseId)}/teaching-constraints`)
// 教学约束相关请求体对应后端 extra="forbid" 的严格 schema，签名参数必须放
// query（signatureInQuery），否则 time/enc 会混入 body 触发 422。
export const updateTeachingConstraints = (courseId, payload) => request.put(`/agent-governance/course/${course(courseId)}/teaching-constraints`, payload, { signatureInQuery: true })
export const listTeachingConstraintVersions = (courseId) => request.get(`/agent-governance/course/${course(courseId)}/teaching-constraints/versions`)
export const rollbackTeachingConstraints = (courseId, payload) => request.post(`/agent-governance/course/${course(courseId)}/teaching-constraints/rollback`, payload, { signatureInQuery: true })
export const previewTeachingConstraints = (courseId, payload) => request.post(`/agent-governance/course/${course(courseId)}/teaching-constraints/preview`, payload, { signatureInQuery: true })
export const listTeachingConstraintEvaluations = (courseId, limit = 20) => request.get(`/agent-governance/course/${course(courseId)}/teaching-constraints/evaluations`, { params: { limit } })

export const getTeachingToolPolicies = (courseId) => request.get(`/agent-governance/course/${course(courseId)}/tools`)
export const updateTeachingToolPolicies = (courseId, payload) => request.put(`/agent-governance/course/${course(courseId)}/tools`, payload)
export const listBuiltinTeachingTools = () => request.get('/agent-governance/builtin-tools')
