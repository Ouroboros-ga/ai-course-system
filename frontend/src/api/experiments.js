import request from '@/utils/request.js'

/**
 * Server-owned coding run APIs.
 *
 * The returned run_id is the only identifier that may be passed to
 * TeachingAgent. Judge0 tokens and source code never cross this boundary.
 */
export function createExperimentRun(attemptId, courseId, payload, options = {}) {
  return request.post(
    `/experiments/attempts/${attemptId}/runs?course_id=${encodeURIComponent(courseId)}${options.asyncRun ? '&async_run=true' : ''}`,
    {
      language: payload.language,
      source_code: payload.source_code,
    },
    { skipErrorToast: true },
  )
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

export function publishExperimentDefinition(courseId, experimentId) {
  return request.post(`/experiments/course/${encodeURIComponent(courseId)}/definitions/${encodeURIComponent(experimentId)}/publish`)
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
