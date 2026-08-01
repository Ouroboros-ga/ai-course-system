const numberOr = (value, fallback = 0) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

const nonNegativeInteger = (value, fallback = 0) => Math.max(0, Math.round(numberOr(value, fallback)))

function normalizeSubtitles(value) {
  if (!Array.isArray(value)) return []
  return value
    .map((segment, index) => ({
      index,
      nodeId: segment?.node_id ?? segment?.nodeId ?? null,
      startMs: nonNegativeInteger(segment?.start_ms ?? segment?.startMs),
      endMs: nonNegativeInteger(segment?.end_ms ?? segment?.endMs),
      text: String(segment?.text ?? ''),
      scriptReference: segment?.script_reference ?? segment?.scriptReference ?? null,
    }))
    .filter(segment => segment.text && segment.endMs >= segment.startMs)
    .sort((left, right) => left.startMs - right.startMs || left.endMs - right.endMs)
}

function normalizePptTimeline(value) {
  if (!Array.isArray(value)) return []
  return value
    .map((cue, index) => ({
      index,
      nodeId: cue?.node_id ?? cue?.nodeId ?? null,
      page: Math.max(1, Math.round(numberOr(cue?.ppt_page ?? cue?.pptPage, 1))),
      startMs: nonNegativeInteger(cue?.start_ms ?? cue?.startMs),
    }))
    .sort((left, right) => left.startMs - right.startMs || left.index - right.index)
}

function normalizePptManifest(value) {
  if (!value || value.schema !== 'ppt-manifest/v1' || !Array.isArray(value.pages)) {
    return null
  }
  const pages = value.pages
    .map((page, index) => ({
      index,
      page: Math.max(1, Math.round(numberOr(page?.page, index + 1))),
      imageUrl: String(page?.image_url ?? page?.imageUrl ?? ''),
      width: nonNegativeInteger(page?.width),
      height: nonNegativeInteger(page?.height),
    }))
    .filter(page => page.imageUrl)
    .sort((left, right) => left.page - right.page || left.index - right.index)
  return {
    schema: 'ppt-manifest/v1',
    manifestUrl: String(value.manifest_url ?? value.manifestUrl ?? ''),
    sourceSha256: String(value.source_sha256 ?? value.sourceSha256 ?? ''),
    pages,
  }
}

function normalizeAvatarCues(value) {
  if (!value || value.schema !== 'avatar-cues/v1' || !(value.manifest_url ?? value.manifestUrl)) return null
  return {
    schema: 'avatar-cues/v1',
    manifestUrl: String(value.manifest_url ?? value.manifestUrl),
    timingSource: String(value.timing_source ?? value.timingSource ?? ''),
    precision: String(value.precision ?? 'subtitle'),
    contentSha256: String(value.content_sha256 ?? value.contentSha256 ?? ''),
  }
}

function normalizeDigitalHumanManifest(value) {
  if (!value || !(value.manifest_url ?? value.manifestUrl)) return null
  return {
    manifestUrl: String(value.manifest_url ?? value.manifestUrl),
    renderMode: String(value.render_mode ?? value.renderMode ?? ''),
    recommendedQuality: String(value.recommended_quality ?? value.recommendedQuality ?? 'auto'),
    fallbackSupported: Boolean(value.fallback_supported ?? value.fallbackSupported),
  }
}

/**
 * Normalize only the public playback manifest. Provider-specific source data
 * never crosses this boundary into the browser player.
 */
export function normalizeMediaPlayback(rawResponse) {
  const raw = rawResponse?.data ?? rawResponse ?? {}
  const subtitleSegments = normalizeSubtitles(raw.subtitle_segments ?? raw.subtitleSegments)
  const pptTimeline = normalizePptTimeline(raw.ppt_timeline ?? raw.pptTimeline)
  const ppt = normalizePptManifest(raw.ppt)
  const avatarCues = normalizeAvatarCues(raw.avatar_cues ?? raw.avatarCues)
  const digitalHumanManifest = normalizeDigitalHumanManifest(raw.digital_human_manifest ?? raw.digitalHumanManifest)
  const durationMs = nonNegativeInteger(raw.duration_ms ?? raw.durationMs)

  return {
    available: Boolean(raw.available),
    reason: String(raw.reason ?? ''),
    message: String(raw.message ?? ''),
    releaseId: raw.release_id ?? raw.releaseId ?? null,
    label: String(raw.label ?? ''),
    audioUrl: String(raw.audio_url ?? raw.audioUrl ?? ''),
    durationMs,
    subtitleSegments,
    pptTimeline,
    ppt,
    defaultPlaybackMode: String(raw.default_playback_mode ?? raw.defaultPlaybackMode ?? 'compatibility'),
    fallbackMode: String(raw.fallback_mode ?? raw.fallbackMode ?? 'compatibility'),
    avatarCues,
    digitalHumanManifest,
  }
}

export function resolvePptPageAtTime(timeline, timeMs) {
  if (!Array.isArray(timeline) || !timeline.length) return null
  const target = Math.max(0, numberOr(timeMs))
  let page = null
  for (const cue of timeline) {
    if (cue.startMs > target) break
    page = cue.page
  }
  return page
}

export function findActiveSubtitleIndex(segments, timeMs) {
  if (!Array.isArray(segments) || !segments.length) return -1
  const target = Math.max(0, numberOr(timeMs))
  return segments.findIndex(segment => target >= segment.startMs && target <= segment.endMs)
}
