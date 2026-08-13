export const FORMAL_RUN_TERMINAL_TASK_STATUSES = new Set([
  'succeeded',
  'failed',
  'cancelled',
  'partial_success',
  'interrupted',
])

export function buildFormalRunRequest(attemptId, courseId, payload, idempotencyKey) {
  return {
    url: `/experiments/attempts/${encodeURIComponent(attemptId)}/runs?course_id=${encodeURIComponent(courseId)}`,
    body: {
      language: payload.language,
      source_code: payload.source_code,
    },
    config: {
      headers: { 'Idempotency-Key': idempotencyKey },
      skipErrorToast: true,
    },
  }
}

export function runResourcePaths(courseId, runId) {
  const scope = `?course_id=${encodeURIComponent(courseId)}`
  const route = `/experiments/runs/${encodeURIComponent(runId)}`
  return {
    run: `${route}${scope}`,
    cancel: `${route}/cancel${scope}`,
    explanation: `${route}/explanation${scope}`,
  }
}

export function isTerminalTaskStatus(status) {
  return FORMAL_RUN_TERMINAL_TASK_STATUSES.has(status)
}

export function shouldOfferFormalRunRetry(task, run) {
  return task?.status === 'failed'
    && task?.retryable === true
    && run?.outcome === 'sandbox_unavailable'
}
