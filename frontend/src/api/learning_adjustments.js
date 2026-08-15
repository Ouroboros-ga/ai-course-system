import request from '@/utils/request.js'

const flat = { allowFlatResponse: true, skipErrorToast: true }

function adjustmentPath(adjustmentId, action) {
  return `/learning-adjustments/${encodeURIComponent(adjustmentId)}/${action}`
}

/** Generates a bounded idempotency key without requiring HTTPS randomUUID. */
export function createLearningAdjustmentIdempotencyKey(action, adjustmentId) {
  const cryptoApi = typeof globalThis !== 'undefined' ? globalThis.crypto : null
  const nonce = cryptoApi?.randomUUID?.()
    || `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
  return `lad:${action}:${String(adjustmentId)}:${nonce}`.slice(0, 200)
}

export function listRecentLearningAdjustments(courseId, options = {}) {
  return request({
    url: `/learning-adjustments/course/${encodeURIComponent(courseId)}/recent`,
    method: 'get',
    params: { limit: options.limit ?? 20 },
    ...flat,
  })
}

/** `applied` means learner acceptance; it does not claim the browser navigated. */
export function applyLearningAdjustment(adjustmentId, returnAnchor, idempotencyKey) {
  return request({
    url: adjustmentPath(adjustmentId, 'apply'),
    method: 'post',
    data: { return_anchor: returnAnchor, idempotency_key: idempotencyKey },
    signatureInQuery: true,
    ...flat,
  })
}

/** Call only after the browser has successfully restored the saved anchor. */
export function returnFromLearningAdjustment(adjustmentId, idempotencyKey) {
  return request({
    url: adjustmentPath(adjustmentId, 'return'),
    method: 'post',
    data: { idempotency_key: idempotencyKey },
    signatureInQuery: true,
    ...flat,
  })
}

export function dismissLearningAdjustment(adjustmentId, idempotencyKey) {
  return request({
    url: adjustmentPath(adjustmentId, 'dismiss'),
    method: 'post',
    data: { idempotency_key: idempotencyKey },
    signatureInQuery: true,
    ...flat,
  })
}
