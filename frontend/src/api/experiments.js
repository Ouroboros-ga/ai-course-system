import request from '@/utils/request.js'
import { buildFormalRunRequest, runResourcePaths } from './experimentRunContract.js'
import { buildVersionRequest, experimentPublishPaths } from './experimentPublishContract.js'

/**
 * Server-owned coding run APIs.
 *
 * The returned run_id is the only identifier that may be passed to
 * TeachingAgent. Judge0 tokens and source code never cross this boundary.
 */
export function createExperimentRun(attemptId, courseId, payload, idempotencyKey) {
  const requestData = buildFormalRunRequest(attemptId, courseId, payload, idempotencyKey)
  return request.post(requestData.url, requestData.body, requestData.config)
}

export function listPublishedExperiments(courseId) {
  return request.get(`/experiments/course/${encodeURIComponent(courseId)}/definitions`, {
    params: { publish_status: 'published' },
    skipErrorToast: true,
  })
}

export function listExperimentDefinitions(courseId, params = {}) {
  return request.get(`/experiments/course/${encodeURIComponent(courseId)}/definitions`, { params, skipErrorToast: true })
}

export function createExperimentDefinition(courseId, payload) {
  return request.post(`/experiments/course/${encodeURIComponent(courseId)}/definitions`, payload)
}

export function updateExperimentDefinition(courseId, experimentId, payload) {
  return request.put(experimentPublishPaths(courseId, experimentId, '').definition, payload)
}

export function publishExperimentDefinition(courseId, experimentId) {
  return request.post(experimentPublishPaths(courseId, experimentId, '').publish)
}

export function createExperimentVersion(courseId, experimentId, form) {
  return request.post(
    experimentPublishPaths(courseId, experimentId, '').versions,
    buildVersionRequest(form),
  )
}

/**
 * 列出实验的全部版本（教师视图含未激活版本）。
 * 注：列表项只含版本元数据，不含 test_cases；取测试用例请用 getExperimentVersion。
 */
export function listExperimentVersions(courseId, experimentId) {
  return request.get(
    `/experiments/${encodeURIComponent(experimentId)}/versions?course_id=${encodeURIComponent(courseId)}`,
    { skipErrorToast: true },
  )
}

/**
 * 读取单个版本详情（教师视图完整暴露隐藏用例的 stdin / expected_stdout）。
 * 用于「继续配置」时恢复既有测试集，避免用默认空用例覆盖已保存内容。
 */
export function getExperimentVersion(courseId, versionId) {
  return request.get(
    `/experiments/versions/${encodeURIComponent(versionId)}?course_id=${encodeURIComponent(courseId)}`,
    { skipErrorToast: true },
  )
}

/**
 * 归档实验定义（软状态：置为 archived，不删除版本与尝试记录）。
 * 仅用于清理草稿，使教师工作台的任务列表不再堆积废弃条目。
 */
export function archiveExperimentDefinition(courseId, experimentId) {
  return request.post(
    `/experiments/course/${encodeURIComponent(courseId)}/definitions/${encodeURIComponent(experimentId)}/archive`,
  )
}

export function previewExperimentReferenceSolution(courseId, versionId, payload) {
  return request.post(
    experimentPublishPaths(courseId, '', versionId).preview,
    { language: payload.language, source_code: payload.source_code },
    { skipErrorToast: true },
  )
}

export function lockExperimentVersion(courseId, versionId) {
  return request.post(experimentPublishPaths(courseId, '', versionId).lock)
}

export function createExperimentAttempt(experimentId, courseId, returnAnchor = {}, activityId = null) {
  const body = { return_anchor: returnAnchor }
  // 活动归属：有值才带（自由练习不带，后端按 None 走原语义）。
  if (activityId) body.activity_id = activityId
  return request.post(
    `/experiments/${encodeURIComponent(experimentId)}/attempts?course_id=${encodeURIComponent(courseId)}`,
    body,
    { skipErrorToast: true },
  )
}

export function createCodingDiagnosis(courseId, runId) {
  return request.post(
    `/experiments/runs/${encodeURIComponent(runId)}/diagnosis?course_id=${encodeURIComponent(courseId)}`,
    null,
    { skipErrorToast: true },
  )
}

export function getCodingDiagnosis(courseId, runId) {
  return request.get(
    `/experiments/runs/${encodeURIComponent(runId)}/diagnosis?course_id=${encodeURIComponent(courseId)}`,
    { skipErrorToast: true },
  )
}

export function getExperimentRun(courseId, runId) {
  return request.get(runResourcePaths(courseId, runId).run, { skipErrorToast: true })
}

export function cancelExperimentRun(courseId, runId) {
  return request.post(runResourcePaths(courseId, runId).cancel, null, { skipErrorToast: true })
}

export function getCodingRunExplanation(courseId, runId) {
  return request.post(runResourcePaths(courseId, runId).explanation, null, { skipErrorToast: true })
}
