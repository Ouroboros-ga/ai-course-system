import request from '@/utils/request.js'
import { listFacadeCourses } from './facade.js'
import { labProjectionPaths } from './labProjectionContract.js'
import { isCodeSandboxExperimentPlatformEnabled } from '@/app/lib/courseExperimentPlatform.js'

export const listLabCatalog = (courseId) => request.get(labProjectionPaths(courseId).catalog)
export const listLabCourseTasks = (courseId) => request.get(labProjectionPaths(courseId).courseTasks)
export const listMyLabs = (courseId) => request.get(labProjectionPaths(courseId).myExperiments)
export const listLabRecords = (courseId) => request.get(labProjectionPaths(courseId).records)

/**
 * 实验室页面的可选项课程：只返回已启用代码沙箱实验平台的课程。
 * Course Access v1 将 experiment.view 绑定到课程能力开关；未启用能力的课程
 * 调用 /lab/* 接口会得到 403（课程权限不足）而不是空目录，因此页面必须先过滤。
 * 闸门与 CourseLayout 的「实验任务」导航保持一致（experiment + coding_sandbox）。
 */
export async function listExperimentCourses() {
  const [learning, building] = await Promise.all([listFacadeCourses('learning'), listFacadeCourses('building')])
  const unique = new Map()
  for (const course of [...(learning?.items || []), ...(building?.items || [])]) {
    if (isCodeSandboxExperimentPlatformEnabled(course?.capabilities)) unique.set(String(course.course_id), course)
  }
  return [...unique.values()]
}
