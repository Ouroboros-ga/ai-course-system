import request from '@/utils/request.js'

export const listResources = (params = {}) => request.get('/resources/files', { params })
export const createResource = (payload) => request.post('/resources/files', payload)
export const updateResource = (resourceId, payload) => request.patch(`/resources/files/${encodeURIComponent(resourceId)}`, payload)
export const deleteResource = (resourceId) => request.delete(`/resources/files/${encodeURIComponent(resourceId)}`)
export const restoreResource = (resourceId) => request.post(`/resources/files/${encodeURIComponent(resourceId)}/restore`)
export const purgeResource = (resourceId) => request.delete(`/resources/files/${encodeURIComponent(resourceId)}/purge`)
export const listResourceReferences = (resourceId) => request.get(`/resources/files/${encodeURIComponent(resourceId)}/references`)
export const addResourceReference = (resourceId, payload) => request.post(`/resources/files/${encodeURIComponent(resourceId)}/references`, payload)
