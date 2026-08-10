import { computed, ref } from 'vue'

import { normalizeAvatarCueManifest } from '../adapters/avatarPlaybackAdapter.js'
import { normalizeSprite2dManifest, PLATFORM_SPRITE2D_MANIFEST } from '../adapters/platformSprite2dAssets.js'

async function readManifest(url) {
  const response = await fetch(url, {
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
  })
  if (!response.ok) throw new Error(`MANIFEST_HTTP_${response.status}`)
  return response.json()
}

/**
 * Loads only signed, release-scoped P2 assets.  An unavailable avatar must
 * never change the primary playback status; the caller can keep audio/PPT and
 * captions running while this composable selects a safe static fallback.
 */
export function useAvatarPlayback() {
  const status = ref('idle')
  const error = ref('')
  const cues = ref(null)
  const spriteManifest = ref(null)
  const assetSource = ref('none')

  const available = computed(() => status.value === 'ready' && Boolean(cues.value))
  const usesPlatformAsset = computed(() => assetSource.value === 'platform')

  async function load({ avatarCues, digitalHumanManifest, avatarManifestUrl, avatarAssetUrls } = {}) {
    status.value = 'loading'
    error.value = ''
    if (!avatarCues?.manifestUrl) {
      cues.value = null
      spriteManifest.value = null
      assetSource.value = 'none'
      status.value = 'unavailable'
      return null
    }

    try {
      const parsedCues = normalizeAvatarCueManifest(await readManifest(avatarCues.manifestUrl))
      if (!parsedCues) throw new Error('AVATAR_CUES_SCHEMA_INVALID')
      cues.value = parsedCues

      const releaseManifestUrl = avatarManifestUrl || digitalHumanManifest?.manifestUrl
      if (releaseManifestUrl) {
        try {
          const remoteManifest = normalizeSprite2dManifest(
            await readManifest(releaseManifestUrl),
            avatarAssetUrls || digitalHumanManifest?.assetUrls || {},
          )
          if (remoteManifest) {
            spriteManifest.value = remoteManifest
            assetSource.value = 'release'
          }
        } catch {
          // The P3 platform asset is an explicit, approved fallback for an
          // unavailable or pre-P3 provider package.  The signed Cue remains
          // the only source of speaking timing.
        }
      }

      if (!spriteManifest.value) {
        spriteManifest.value = PLATFORM_SPRITE2D_MANIFEST
        assetSource.value = 'platform'
      }
      status.value = 'ready'
      return cues.value
    } catch (loadError) {
      status.value = 'unavailable'
      error.value = '数字人时间轴暂不可用，已保持讲解媒体正常播放。'
      return null
    }
  }

  return {
    status,
    error,
    cues,
    spriteManifest,
    assetSource,
    available,
    usesPlatformAsset,
    load,
  }
}
