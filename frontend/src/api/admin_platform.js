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
