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

export function createExperimentAttempt(experimentId, courseId, returnAnchor = {}) {
  return request.post(
    `/experiments/${encodeURIComponent(experimentId)}/attempts?course_id=${encodeURIComponent(courseId)}`,
    { return_anchor: returnAnchor },
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
