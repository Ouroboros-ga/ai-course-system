/**
 * The visualization API still indexes plans by the legacy integer knowledge
 * node. Learning playback can instead expose release-scoped outline IDs, so
 * never serialize those IDs as the integer-only `node_id` query parameter.
 */
export function sanitizePlanListParams(params = {}) {
  const sanitized = { ...params }
  if (!Object.hasOwn(sanitized, 'node_id')) return sanitized

  const nodeId = Number(sanitized.node_id)
  if (!Number.isSafeInteger(nodeId) || nodeId <= 0) {
    delete sanitized.node_id
  } else {
    sanitized.node_id = nodeId
  }
  return sanitized
}
