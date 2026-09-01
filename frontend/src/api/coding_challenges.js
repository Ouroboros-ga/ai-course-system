import request from '@/utils/request.js'

const base = '/teaching-agent/coding-challenges'
const scoped = (courseId, options = {}) => ({
  params: { course_id: courseId, ...(options.params || {}) },
  skipErrorToast: options.skipErrorToast ?? true,
})

export function getActiveCodingChallenge(courseId, conversationSessionId) {
  return request.get(`${base}/active`, scoped(courseId, {
    params: { session_id: conversationSessionId },
  }))
}

export function getCodingChallengeOffer(courseId, offerId) {
  return request.get(
    `${base}/offers/${encodeURIComponent(offerId)}`,
    scoped(courseId),
  )
}

export function startCodingChallenge(courseId, offerId, returnAnchor) {
  return request.post(
    `${base}/offers/${encodeURIComponent(offerId)}/start`,
    { return_anchor: returnAnchor || {} },
    scoped(courseId),
  )
}

export function dismissCodingChallenge(courseId, offerId) {
  return request.post(
    `${base}/offers/${encodeURIComponent(offerId)}/dismiss`,
    null,
    scoped(courseId),
  )
}

export function replaceCodingChallenge(courseId, offerId) {
  return request.post(
    `${base}/offers/${encodeURIComponent(offerId)}/replace`,
    null,
    scoped(courseId),
  )
}

export function createCodingChallengeRun(courseId, sessionId, payload, idempotencyKey) {
  return request.post(
    `${base}/sessions/${encodeURIComponent(sessionId)}/runs`,
    payload,
    {
      ...scoped(courseId),
      headers: { 'Idempotency-Key': idempotencyKey },
    },
  )
}

export function getCodingChallengeRun(courseId, runId) {
  return request.get(
    `${base}/runs/${encodeURIComponent(runId)}`,
    scoped(courseId),
  )
}

export function revealCodingChallengeHint(courseId, runId) {
  return request.post(
    `${base}/runs/${encodeURIComponent(runId)}/hint`,
    null,
    scoped(courseId),
  )
}

export function closeCodingChallenge(courseId, sessionId, reason = 'returned_to_course') {
  return request.post(
    `${base}/sessions/${encodeURIComponent(sessionId)}/close`,
    { reason },
    scoped(courseId),
  )
}
