import request from '@/utils/request.js'
import { labProjectionPaths } from './labProjectionContract.js'

export const listLabCatalog = (courseId) => request.get(labProjectionPaths(courseId).catalog)
export const listLabCourseTasks = (courseId) => request.get(labProjectionPaths(courseId).courseTasks)
export const listMyLabs = (courseId) => request.get(labProjectionPaths(courseId).myExperiments)
export const listLabRecords = (courseId) => request.get(labProjectionPaths(courseId).records)
