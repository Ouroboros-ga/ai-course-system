import request from '@/utils/request.js'

export const getAdminUsers = (params) => request({ url: '/admin/users', method: 'get', params })
export const updateAdminUser = (userId, data) => request({ url: `/admin/users/${userId}`, method: 'patch', data })
export const resetAdminPassword = (userId, password) => request({ url: `/admin/users/${userId}/reset-password`, method: 'post', data: { password } })

export const getIntegrations = () => request({ url: '/admin/integrations', method: 'get' })
export const updateIntegration = (key, data) => request({ url: `/admin/integrations/${key}`, method: 'put', data })
export const testIntegration = (key) => request({ url: `/admin/integrations/${key}/test`, method: 'post' })
export const getTaskConcurrency = () => request({ url: '/admin/task-concurrency', method: 'get' })
export const updateTaskConcurrency = (data) => request({ url: '/admin/task-concurrency', method: 'put', data })

export const getAdminCourseCapabilities = () => request({ url: '/admin/courses/capabilities', method: 'get' })
export const updateAdminCourseCapabilities = (courseId, payload) => request({ url: `/admin/courses/${courseId}/capabilities`, method: 'put', data: payload })

// ---- 平台级安全屏蔽词配置（G6 安全围栏，2026-08-17 新增）----
export const getSafetyKeywords = (params) => request({ url: '/admin/safety-keywords', method: 'get', params })
export const createSafetyKeyword = (data) => request({ url: '/admin/safety-keywords', method: 'post', data })
export const updateSafetyKeyword = (keywordId, data) => request({ url: `/admin/safety-keywords/${keywordId}`, method: 'patch', data })
export const deleteSafetyKeyword = (keywordId) => request({ url: `/admin/safety-keywords/${keywordId}`, method: 'delete' })
