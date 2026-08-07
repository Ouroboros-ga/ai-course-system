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
      ...(segment?.ppt_page != null || segment?.pptPage != null ? { pptPage: segment?.ppt_page ?? segment?.pptPage } : {}),
      ...(segment?.material_version_id != null || segment?.materialVersionId != null ? { materialVersionId: segment?.material_version_id ?? segment?.materialVersionId } : {}),
    }))
    .filter(segment => segment.text && segment.endMs >= segment.startMs)
    .sort((left, right) => left.startMs - right.startMs || left.endMs - right.endMs)
}

function normalizePptTimeline(value) {
  if (!Array.isArray(value)) return []
  return value
    .map((cue, index) => {
      const rawPage = cue?.ppt_page ?? cue?.pptPage
      const parsedPage = Number(rawPage)
      return {
        index,
        nodeId: cue?.node_id ?? cue?.nodeId ?? null,
        outlineNodeId: cue?.outline_node_id ?? cue?.outlineNodeId ?? null,
        // An unmapped cue must not silently become page 1. Keep the null so
        // the player can retain its normal fallback surface.
        page: Number.isFinite(parsedPage) && parsedPage >= 1 ? Math.round(parsedPage) : null,
        materialVersionId: cue?.material_version_id ?? cue?.materialVersionId ?? null,
        startMs: nonNegativeInteger(cue?.start_ms ?? cue?.startMs),
        endMs: nonNegativeInteger(cue?.end_ms ?? cue?.endMs),
      }
    })
    .sort((left, right) => left.startMs - right.startMs || left.index - right.index)
}

function normalizePptManifest(value) {
  if (!value || value.schema !== 'ppt-manifest/v1' || !Array.isArray(value.pages)) {
    return null
  }
  const normalizePages = pages => pages
    .map((page, index) => ({
      index,
      page: Math.max(1, Math.round(numberOr(page?.page, index + 1))),
      imageUrl: String(page?.image_url ?? page?.imageUrl ?? ''),
      width: nonNegativeInteger(page?.width),
      height: nonNegativeInteger(page?.height),
    }))
    .filter(page => page.imageUrl)
    .sort((left, right) => left.page - right.page || left.index - right.index)
  const pages = normalizePages(value.pages)
  const decks = Array.isArray(value.decks)
    ? value.decks
      .map(deck => ({
        materialVersionId: String(deck?.material_version_id ?? deck?.materialVersionId ?? ''),
        materialName: String(deck?.material_name ?? deck?.materialName ?? 'PPT'),
        sourceSha256: String(deck?.source_sha256 ?? deck?.sourceSha256 ?? ''),
        pages: normalizePages(Array.isArray(deck?.pages) ? deck.pages : []),
      }))
      .filter(deck => deck.materialVersionId && deck.pages.length)
    : []
  return {
    schema: 'ppt-manifest/v1',
    manifestUrl: String(value.manifest_url ?? value.manifestUrl ?? ''),
    sourceSha256: String(value.source_sha256 ?? value.sourceSha256 ?? ''),
    primaryMaterialVersionId: String(value.primary_material_version_id ?? value.primaryMaterialVersionId ?? ''),
    pages,
    decks,
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
    avatarPresetId: String(value.avatar_preset_id ?? value.avatarPresetId ?? ''),
    avatarPresetVersion: String(value.avatar_preset_version ?? value.avatarPresetVersion ?? ''),
    renderMode: String(value.render_mode ?? value.renderMode ?? ''),
    recommendedQuality: String(value.recommended_quality ?? value.recommendedQuality ?? 'auto'),
    fallbackSupported: Boolean(value.fallback_supported ?? value.fallbackSupported),
  }
}

function normalizePlaylist(value) {
  if (!value || value.schema !== 'audio-playlist/v1' || !Array.isArray(value.items)) return null
  return {
    schema: 'audio-playlist/v1',
    durationMs: nonNegativeInteger(value.duration_ms ?? value.durationMs),
    contentSha256: String(value.content_sha256 ?? value.contentSha256 ?? ''),
    items: value.items.map((item, index) => ({
      index,
      nodeId: item?.node_id ?? item?.nodeId ?? null,
      outlineNodeId: item?.outline_node_id ?? item?.outlineNodeId ?? null,
      offsetMs: nonNegativeInteger(item?.offset_ms ?? item?.offsetMs),
      durationMs: nonNegativeInteger(item?.duration_ms ?? item?.durationMs),
      audioUrl: String(item?.audio_url ?? item?.audioUrl ?? ''),
      subtitleManifestUrl: String(item?.subtitle_manifest_url ?? item?.subtitleManifestUrl ?? ''),
      avatarCuesUrl: String(item?.avatar_cues_url ?? item?.avatarCuesUrl ?? ''),
      pptMappingSnapshot: item?.ppt_mapping_snapshot ?? item?.pptMappingSnapshot ?? {},
      pptTimeline: normalizePptTimeline(item?.ppt_timeline ?? item?.pptTimeline).map(cue => ({
        ...cue,
        // The server playlist already serializes PPT timing in the global
        // course clock.  Older fixtures may still send item-local timing, so
        // add the offset only when the cue clearly precedes its item.
        startMs: cue.startMs < nonNegativeInteger(item?.offset_ms ?? item?.offsetMs)
          ? cue.startMs + nonNegativeInteger(item?.offset_ms ?? item?.offsetMs)
          : cue.startMs,
        endMs: cue.endMs < nonNegativeInteger(item?.offset_ms ?? item?.offsetMs)
          ? cue.endMs + nonNegativeInteger(item?.offset_ms ?? item?.offsetMs)
          : cue.endMs,
      })),
      subtitleSegments: normalizeSubtitles(item?.subtitle_segments ?? item?.subtitleSegments).map(segment => ({
        ...segment,
        startMs: nonNegativeInteger(segment.startMs + nonNegativeInteger(item?.offset_ms ?? item?.offsetMs)),
        endMs: nonNegativeInteger(segment.endMs + nonNegativeInteger(item?.offset_ms ?? item?.offsetMs)),
      })),
      avatarPresetId: String(item?.avatar_preset_id ?? item?.avatarPresetId ?? ''),
      avatarPresetVersion: String(item?.avatar_preset_version ?? item?.avatarPresetVersion ?? ''),
      avatarManifestUrl: String(item?.avatar_manifest_url ?? item?.avatarManifestUrl ?? ''),
      avatarCues: (item?.avatar_cues_url ?? item?.avatarCuesUrl)
        ? { schema: 'avatar-cues/v1', manifestUrl: String(item?.avatar_cues_url ?? item?.avatarCuesUrl) }
        : null,
    })).filter(item => item.audioUrl && item.durationMs > 0),
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
  const playlist = normalizePlaylist(raw.playlist)
  const durationMs = nonNegativeInteger(raw.duration_ms ?? raw.durationMs)

  return {
    available: Boolean(raw.available),
    reason: String(raw.reason ?? ''),
    message: String(raw.message ?? ''),
    releaseId: raw.release_id ?? raw.releaseId ?? null,
    label: String(raw.label ?? ''),
    audioUrl: String(raw.audio_url ?? raw.audioUrl ?? ''),
    durationMs: playlist?.durationMs || durationMs,
    subtitleSegments: playlist
      ? playlist.items.flatMap(item => item.subtitleSegments)
      : subtitleSegments,
    pptTimeline: playlist
      ? playlist.items.flatMap(item => item.pptTimeline)
      : pptTimeline,
    ppt,
    defaultPlaybackMode: String(raw.default_playback_mode ?? raw.defaultPlaybackMode ?? 'compatibility'),
    fallbackMode: String(raw.fallback_mode ?? raw.fallbackMode ?? 'compatibility'),
    avatarCues,
    avatarPresetId: String(raw.avatar_preset_id ?? raw.avatarPresetId ?? digitalHumanManifest?.avatarPresetId ?? ''),
    avatarPresetVersion: String(raw.avatar_preset_version ?? raw.avatarPresetVersion ?? digitalHumanManifest?.avatarPresetVersion ?? ''),
    avatarManifestUrl: String(raw.avatar_manifest_url ?? raw.avatarManifestUrl ?? digitalHumanManifest?.manifestUrl ?? ''),
    digitalHumanManifest,
    playlist,
  }
}

export function resolvePptCueAtTime(timeline, timeMs) {
  if (!Array.isArray(timeline) || !timeline.length) return null
  const target = Math.max(0, numberOr(timeMs))
  let activeCue = null
  for (const candidate of timeline) {
    if (candidate.startMs > target) break
    activeCue = candidate
  }
  return activeCue
}

export function resolvePptPageAtTime(timeline, timeMs) {
  return resolvePptCueAtTime(timeline, timeMs)?.page ?? null
}

export function findActiveSubtitleIndex(segments, timeMs) {
  if (!Array.isArray(segments) || !segments.length) return -1
  const target = Math.max(0, numberOr(timeMs))
  return segments.findIndex(segment => target >= segment.startMs && target <= segment.endMs)
}
