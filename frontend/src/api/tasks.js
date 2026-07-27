import request from '@/utils/request.js'

export const listTasks = (params = {}) => request.get('/tasks', { params })
export const getTask = (taskId) => request.get(`/tasks/${encodeURIComponent(taskId)}`)
export const cancelTask = (taskId, reason = '') => request.post(`/tasks/${encodeURIComponent(taskId)}/cancel`, { reason })
export const retryTask = (taskId) => request.post(`/tasks/${encodeURIComponent(taskId)}/retry`)
export const acknowledgeTask = (taskId) => request.post(`/tasks/${encodeURIComponent(taskId)}/acknowledge`)
export const listTaskEvents = (taskId) => request.get(`/tasks/${encodeURIComponent(taskId)}/events`)
