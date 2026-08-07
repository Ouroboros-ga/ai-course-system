import { computed, ref } from 'vue'

import { getCoursePlayback } from '@/api/media_release.js'
import { withAccessToken } from '../adapters/playerWorkspaceAdapter.js'
import {
  findActiveSubtitleIndex,
  normalizeMediaPlayback,
  resolvePptCueAtTime,
  resolvePptPageAtTime,
} from '../adapters/mediaPlaybackAdapter.js'

/**
 * Fetches the frozen learner media release. The calling workspace keeps its
 * legacy player data so a course without a release remains readable.
 */
export function useMediaPlayback(courseId) {
  const status = ref('idle')
  const error = ref('')
  const manifest = ref(normalizeMediaPlayback(null))

  // A course-level `audio-playlist/v1` intentionally keeps audio URLs on its
  // immutable items instead of duplicating one at the release root.  Treat a
  // playable first item as media-ready so playlist releases do not report an
  // inaccurate unavailable status while LectureStage is already playing it.
  const isAudioReady = computed(() => manifest.value.available && Boolean(
    manifest.value.audioUrl
    || manifest.value.playlist?.items?.some(item => item.audioUrl),
  ))
  const audioUrl = computed(() => manifest.value.audioUrl)
  const playlist = computed(() => manifest.value.playlist)
  const subtitleSegments = computed(() => manifest.value.subtitleSegments)
  const pptTimeline = computed(() => manifest.value.pptTimeline)
  const ppt = computed(() => manifest.value.ppt)
  const avatarCues = computed(() => manifest.value.avatarCues)
  const avatarManifestUrl = computed(() => manifest.value.avatarManifestUrl)
  const digitalHumanManifest = computed(() => manifest.value.digitalHumanManifest)

  function addMediaAccessToken(value) {
    const token = typeof window !== 'undefined' ? window.localStorage.getItem('token') : ''
    if (!token || !value) return value
    const withLocalAccessToken = url => String(url || '').startsWith('/')
      ? withAccessToken(url, token)
      : String(url || '')
    return {
      ...value,
      audioUrl: withLocalAccessToken(value.audioUrl),
      playlist: value.playlist
        ? {
            ...value.playlist,
            items: value.playlist.items.map(item => ({
              ...item,
              audioUrl: withLocalAccessToken(item.audioUrl),
              subtitleManifestUrl: withLocalAccessToken(item.subtitleManifestUrl),
              avatarCuesUrl: withLocalAccessToken(item.avatarCuesUrl),
              avatarManifestUrl: withLocalAccessToken(item.avatarManifestUrl),
              // `useAvatarPlayback` consumes the normalized nested object,
              // rather than the compatibility `avatarCuesUrl` field.  Keep
              // its signed local route authenticated too; otherwise audio
              // plays but Cue loading receives a 401 and silently falls back
              // to no avatar.
              avatarCues: item.avatarCues
                ? {
                    ...item.avatarCues,
                    manifestUrl: withLocalAccessToken(item.avatarCues.manifestUrl),
                  }
                : null,
            })),
          }
        : null,
      ppt: value.ppt
        ? {
            ...value.ppt,
            manifestUrl: withLocalAccessToken(value.ppt.manifestUrl),
            pages: value.ppt.pages.map(page => ({
              ...page,
              imageUrl: withLocalAccessToken(page.imageUrl),
            })),
            decks: (value.ppt.decks || []).map(deck => ({
              ...deck,
              pages: (deck.pages || []).map(page => ({
                ...page,
                imageUrl: withLocalAccessToken(page.imageUrl),
              })),
            })),
          }
        : null,
      avatarCues: value.avatarCues
        ? {
            ...value.avatarCues,
            manifestUrl: withLocalAccessToken(value.avatarCues.manifestUrl),
          }
        : null,
      digitalHumanManifest: value.digitalHumanManifest
        ? {
            ...value.digitalHumanManifest,
            manifestUrl: withLocalAccessToken(value.digitalHumanManifest.manifestUrl),
          }
        : null,
      avatarManifestUrl: withLocalAccessToken(value.avatarManifestUrl),
    }
  }

  async function load() {
    status.value = 'loading'
    error.value = ''
    try {
      const response = await getCoursePlayback(courseId, { skipErrorToast: true })
      manifest.value = addMediaAccessToken(normalizeMediaPlayback(response))
      status.value = isAudioReady.value ? 'ready' : 'unavailable'
    } catch (loadError) {
      // Playback media is an optional upgrade over the legacy learning content.
      error.value = loadError?.message || '讲解媒体暂时不可用'
      manifest.value = normalizeMediaPlayback(null)
      status.value = 'error'
    }
    return manifest.value
  }

  function resolvePptPage(timeSeconds) {
    return resolvePptPageAtTime(pptTimeline.value, Number(timeSeconds) * 1000)
  }

  function resolvePptCue(timeSeconds) {
    return resolvePptCueAtTime(pptTimeline.value, Number(timeSeconds) * 1000)
  }

  function activeSubtitleIndex(timeSeconds) {
    return findActiveSubtitleIndex(subtitleSegments.value, Number(timeSeconds) * 1000)
  }

  return {
    status,
    error,
    manifest,
    isAudioReady,
    audioUrl,
    playlist,
    subtitleSegments,
    pptTimeline,
    ppt,
    avatarCues,
    avatarManifestUrl,
    digitalHumanManifest,
    load,
    resolvePptPage,
    resolvePptCue,
    activeSubtitleIndex,
  }
}
