import request from '@/utils/request.js'

const course = (courseId) => encodeURIComponent(courseId)

export const listJoinRequests = (courseId) => request.get(`/course-access/courses/${course(courseId)}/join-requests`)
export const approveJoinRequest = (courseId, requestId, reviewComment = '') => request.post(`/course-access/courses/${course(courseId)}/join-requests/${encodeURIComponent(requestId)}/approve`, { review_comment: reviewComment })
export const rejectJoinRequest = (courseId, requestId, reviewComment = '') => request.post(`/course-access/courses/${course(courseId)}/join-requests/${encodeURIComponent(requestId)}/reject`, { review_comment: reviewComment })
export const requestJoinInfo = (courseId, requestId, reviewComment = '') => request.post(`/course-access/courses/${course(courseId)}/join-requests/${encodeURIComponent(requestId)}/request-info`, { review_comment: reviewComment })

export const getCourseSettings = (courseId) => request.get(`/course-settings/course/${course(courseId)}/settings`)
export const listCourseSettingVersions = (courseId) => request.get(`/course-settings/course/${course(courseId)}/settings/versions`)
const sectionPayload = (patch, expectedVersion) => ({ patch, ...(expectedVersion == null ? {} : { expected_version: expectedVersion }) })
export const updateCourseProfile = (courseId, patch, expectedVersion) => request.put(`/course-settings/course/${course(courseId)}/profile`, sectionPayload(patch, expectedVersion))
export const updateCoursePublishSettings = (courseId, patch, expectedVersion) => request.put(`/course-settings/course/${course(courseId)}/publish`, sectionPayload(patch, expectedVersion))
export const updateCourseAgentPolicy = (courseId, patch, expectedVersion) => request.put(`/course-settings/course/${course(courseId)}/agent-policy`, sectionPayload(patch, expectedVersion))
export const updateCourseSafetySettings = (courseId, patch, expectedVersion) => request.put(`/course-settings/course/${course(courseId)}/safety`, sectionPayload(patch, expectedVersion))
export const updateCourseSandboxSettings = (courseId, patch, expectedVersion) => request.put(`/course-settings/course/${course(courseId)}/sandbox`, sectionPayload(patch, expectedVersion))
export const updateCourseIntegrationSettings = (courseId, patch, expectedVersion) => request.put(`/course-settings/course/${course(courseId)}/integration`, sectionPayload(patch, expectedVersion))
export const rollbackCourseSettings = (courseId, version) => request.post(`/course-settings/course/${course(courseId)}/settings/rollback`, { target_version: version })
