import request from '@/utils/request.js'

export const listLabCatalog = (params = {}) => request.get('/lab/catalog', { params })
export const listLabCourseTasks = (courseId) => request.get('/lab/course-tasks', { params: { course_id: courseId } })
export const listMyLabs = (params = {}) => request.get('/lab/my-experiments', { params })
export const listLabRecords = (params = {}) => request.get('/lab/records', { params })
export const createLab = (payload) => request.post('/lab', payload)
export const publishLab = (labId) => request.post(`/lab/${encodeURIComponent(labId)}/publish`)
export const enrollLab = (labId) => request.post(`/lab/${encodeURIComponent(labId)}/enroll`)
