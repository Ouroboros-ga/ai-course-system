const VISEMES = new Set(['sil', 'a', 'e', 'i', 'o', 'u', 'fv', 'mbp'])

const numberOr = (value, fallback = 0) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

const nonNegativeInteger = (value, fallback = 0) => Math.max(0, Math.round(numberOr(value, fallback)))

function normaliseTimedEntries(value, field) {
  if (!Array.isArray(value)) return []
  return value
    .map((entry, index) => ({
      index,
      startMs: nonNegativeInteger(entry?.start_ms ?? entry?.startMs),
      endMs: nonNegativeInteger(entry?.end_ms ?? entry?.endMs),
      [field]: String(entry?.[field] ?? ''),
      state: String(entry?.state ?? ''),
    }))
    .filter(entry => entry.endMs > entry.startMs)
    .sort((left, right) => left.startMs - right.startMs || left.endMs - right.endMs || left.index - right.index)
}

function smoothVisemes(entries) {
  if (entries.length === 0) return entries
  const MIN_FLAP_MS = 45
  const smoothed = []
  let i = 0
  while (i < entries.length) {
    const current = entries[i]
    const duration = current.endMs - current.startMs
    if (
      duration >= MIN_FLAP_MS
      || current.viseme === 'sil'
      || i === 0
      || i === entries.length - 1
    ) {
      smoothed.push(current)
      i++
      continue
    }
    const prev = smoothed[smoothed.length - 1]
    const next = entries[i + 1]
    if (prev.viseme === next.viseme) {
      prev.endMs = next.endMs
      i += 2
      continue
    }
    if (prev.viseme === current.viseme) {
      prev.endMs = current.endMs
      i++
      continue
    }
    smoothed.push(current)
    i++
  }
  return smoothed
}

export function normalizeAvatarCueManifest(rawValue) {
  const raw = rawValue?.data ?? rawValue ?? {}
  if (raw.schema !== 'avatar-cues/v1' || !raw.audio?.object_key || !raw.audio?.sha256) return null

  const visemes = smoothVisemes(
    normaliseTimedEntries(raw.visemes, 'viseme')
      .filter(entry => VISEMES.has(entry.viseme))
  )
  const mouthActivity = normaliseTimedEntries(raw.mouth_activity ?? raw.mouthActivity, 'state')
    .filter(entry => entry.state === 'speaking' || entry.state === 'silence')

  return {
    schema: 'avatar-cues/v1',
    audio: {
      objectKey: String(raw.audio.object_key),
      sha256: String(raw.audio.sha256),
      durationMs: nonNegativeInteger(raw.audio.duration_ms ?? raw.audio.durationMs),
    },
    timing: {
      source: String(raw.timing?.source ?? ''),
      precision: String(raw.timing?.precision ?? 'subtitle'),
    },
    visemes,
    mouthActivity,
    warnings: Array.isArray(raw.warnings) ? raw.warnings.map(item => String(item)) : [],
  }
}

function activeEntry(entries, timeMs) {
  const target = Math.max(0, numberOr(timeMs))
  let low = 0
  let high = entries.length - 1
  while (low <= high) {
    const middle = Math.floor((low + high) / 2)
    const entry = entries[middle]
    if (target < entry.startMs) high = middle - 1
    else if (target >= entry.endMs) low = middle + 1
    else return entry
  }
  return null
}

export function resolveAvatarFrame(cues, timeMs) {
  if (!cues) return { viseme: 'sil', speaking: false, precision: 'none' }
  const viseme = activeEntry(cues.visemes, timeMs)?.viseme
  const speaking = activeEntry(cues.mouthActivity, timeMs)?.state === 'speaking'
  return {
    viseme: viseme || (speaking ? 'a' : 'sil'),
    speaking,
    precision: cues.timing.precision,
  }
}

export function selectAvatarPlaybackMode(requestedMode, capability = {}) {
  const requested = ['auto', 'low_resource', 'compatibility'].includes(requestedMode)
    ? requestedMode
    : 'auto'
  if (requested === 'compatibility') return 'compatibility'
  if (capability.reducedMotion || capability.webglAvailable === false) return 'compatibility'
  if (requested === 'low_resource' || numberOr(capability.deviceMemoryGb) > 0 && numberOr(capability.deviceMemoryGb) < 4) {
    return 'low_resource'
  }
  return 'auto'
}

export function browserAvatarCapability() {
  const nav = typeof navigator === 'undefined' ? {} : navigator
  const win = typeof window === 'undefined' ? null : window
  const prefersReducedMotion = Boolean(win?.matchMedia?.('(prefers-reduced-motion: reduce)').matches)
  let webglAvailable = false
  try {
    const canvas = document.createElement('canvas')
    webglAvailable = Boolean(canvas.getContext('webgl2') || canvas.getContext('webgl'))
  } catch {
    // Context creation is optional; callers enter compatibility mode.
  }
  return {
    webglAvailable,
    reducedMotion: prefersReducedMotion,
    deviceMemoryGb: numberOr(nav.deviceMemory),
  }
}
