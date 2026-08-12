import request from '@/utils/request.js'

export const listLabCatalog = (params = {}) => request.get('/lab/catalog', { params })
export const listLabCourseTasks = (courseId) => request.get('/lab/course-tasks', { params: { course_id: courseId } })
export const listMyLabs = (params = {}) => request.get('/lab/my-experiments', { params })
export const listLabRecords = (params = {}) => request.get('/lab/records', { params })
