const nonEmptyString = value => {
  const normalized = String(value ?? '').trim()
  return normalized || null
}

const sameId = (left, right) => left != null && right != null && String(left) === String(right)

const finiteInteger = value => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? Math.round(parsed) : null
}

/**
 * Resolve a frozen coordinate to the playlist's global clock.  Older media
 * releases may have only an item-local cue, so absence of global_time_ms must
 * never be coerced to zero and switch playback to the first media item.
 */
export function resolveFrozenCoordinateGlobalSeconds(coordinate, item) {
  const rawGlobalTimeMs = coordinate?.global_time_ms
  const globalTimeMs = rawGlobalTimeMs == null ? null : finiteInteger(rawGlobalTimeMs)
  if (globalTimeMs != null && globalTimeMs >= 0) return globalTimeMs / 1_000

  const offsetMs = finiteInteger(item?.offsetMs)
  const localTimeMs = finiteInteger(coordinate?.local_time_ms)
  if (offsetMs == null || offsetMs < 0 || localTimeMs == null || localTimeMs < 0) {
    return null
  }
  return (offsetMs + localTimeMs) / 1_000
}

/**
 * Builds the only browser-supplied playback coordinate accepted by the
 * TeachingAgent. Review targets remain server-derived and are never accepted
 * here. Missing historical release metadata deliberately yields `null` so
 * normal Q&A can continue without a misleading review proposal.
 */
export function createPlaybackCoordinate({
  courseReleaseId,
  mediaReleaseId,
  item,
  cue,
  globalTimeSeconds,
}) {
  const courseRelease = nonEmptyString(courseReleaseId)
  const mediaRelease = nonEmptyString(mediaReleaseId)
  const itemId = nonEmptyString(item?.itemId)
  const outlineNodeId = nonEmptyString(item?.outlineNodeId)
  const offsetMs = finiteInteger(item?.offsetMs)
  const durationMs = finiteInteger(item?.durationMs)
  const globalTimeMs = finiteInteger(Number(globalTimeSeconds) * 1_000)
  const page = finiteInteger(cue?.page)

  if (
    !courseRelease || !mediaRelease || !itemId || !outlineNodeId
    || offsetMs == null || durationMs == null || globalTimeMs == null
    || page == null || page < 1 || offsetMs < 0 || durationMs <= 0
    || globalTimeMs < offsetMs || globalTimeMs >= offsetMs + durationMs
  ) return null

  const cueMatchesItem = sameId(cue?.outlineNodeId, item?.outlineNodeId)
    || sameId(cue?.nodeId, item?.nodeId)
  if (!cueMatchesItem) return null

  return {
    course_release_id: courseRelease,
    media_release_id: mediaRelease,
    media_release_item_id: itemId,
    outline_node_id: outlineNodeId,
    local_time_ms: globalTimeMs - offsetMs,
    page,
    global_time_ms: globalTimeMs,
  }
}
