import request from '@/utils/request.js'

function idempotencyKey() {
  return globalThis.crypto?.randomUUID?.() || `run-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

/** Formal submissions are always asynchronous and require a stable key. */
export function createExperimentRun(attemptId, courseId, payload, key = idempotencyKey()) {
  return request.post(
    `/experiments/attempts/${encodeURIComponent(attemptId)}/runs?course_id=${encodeURIComponent(courseId)}`,
    { language: payload.language, source_code: payload.source_code },
    { skipErrorToast: true, headers: { 'Idempotency-Key': key } },
  )
}

export function getExperimentRun(courseId, runId) {
  return request.get(`/experiments/runs/${encodeURIComponent(runId)}?course_id=${encodeURIComponent(courseId)}`, { skipErrorToast: true })
}

export function getExperimentAttempt(courseId, attemptId) {
  return request.get(`/experiments/attempts/${encodeURIComponent(attemptId)}?course_id=${encodeURIComponent(courseId)}`, { skipErrorToast: true })
}

export function getTask(taskId) {
  return request.get(`/tasks/${encodeURIComponent(taskId)}`, { skipErrorToast: true })
}

export function cancelTask(taskId) {
  return request.post(`/tasks/${encodeURIComponent(taskId)}/cancel`, { reason: 'student_cancelled_experiment_run' }, { skipErrorToast: true })
}

export function listPublishedExperiments(courseId) {
  return request.get(`/experiments/course/${encodeURIComponent(courseId)}/definitions`, {
    params: { publish_status: 'published' }, skipErrorToast: true,
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

export function createExperimentVersion(courseId, experimentId, payload) {
  return request.post(`/experiments/${encodeURIComponent(experimentId)}/versions?course_id=${encodeURIComponent(courseId)}`, payload)
}

export function previewExperimentReference(courseId, versionId, payload) {
  return request.post(`/experiments/versions/${encodeURIComponent(versionId)}/reference-preview?course_id=${encodeURIComponent(courseId)}`, payload, { skipErrorToast: true })
}

export function lockExperimentVersion(courseId, versionId) {
  return request.post(`/experiments/versions/${encodeURIComponent(versionId)}/lock?course_id=${encodeURIComponent(courseId)}&locked=true`)
}

export function createExperimentAttempt(experimentId, courseId, returnAnchor = {}) {
  return request.post(
    `/experiments/${encodeURIComponent(experimentId)}/attempts?course_id=${encodeURIComponent(courseId)}`,
    { return_anchor: returnAnchor },
    { skipErrorToast: true },
  )
}

export function getCodingFeedback(courseId, runId) {
  return request.get(`/experiments/runs/${encodeURIComponent(runId)}/feedback?course_id=${encodeURIComponent(courseId)}`, { skipErrorToast: true })
}

export function getCodingDiagnosis(courseId, runId) {
  return request.get(`/experiments/runs/${encodeURIComponent(runId)}/diagnosis?course_id=${encodeURIComponent(courseId)}`, { skipErrorToast: true })
}
