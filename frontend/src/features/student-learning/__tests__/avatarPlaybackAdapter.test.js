import test from 'node:test'
import assert from 'node:assert/strict'

import {
  normalizeAvatarCueManifest,
  resolveAvatarFrame,
  selectAvatarPlaybackMode,
} from '../adapters/avatarPlaybackAdapter.js'
import { normalizeSprite2dManifest, PLATFORM_SPRITE2D_MANIFEST } from '../adapters/platformSprite2dAssets.js'

const rawCues = {
  schema: 'avatar-cues/v1',
  audio: { object_key: 'audio/course1/demo.mp3', sha256: 'audio-sha', duration_ms: 4_000 },
  timing: { source: 'words', precision: 'word' },
  mouth_activity: [
    { start_ms: 0, end_ms: 500, state: 'silence' },
    { start_ms: 500, end_ms: 1_500, state: 'speaking' },
  ],
  visemes: [
    { start_ms: 600, end_ms: 800, viseme: 'o' },
    { start_ms: 800, end_ms: 1_000, viseme: 'not-a-viseme' },
  ],
}

test('P3 only accepts immutable avatar-cues/v1 and preserves its audio binding', () => {
  const result = normalizeAvatarCueManifest(rawCues)
  assert.equal(result.schema, 'avatar-cues/v1')
  assert.equal(result.audio.objectKey, 'audio/course1/demo.mp3')
  assert.equal(result.audio.sha256, 'audio-sha')
  assert.equal(result.visemes.length, 1)
  assert.equal(normalizeAvatarCueManifest({ schema: 'provider-frame/v1' }), null)
})

test('avatar pose is always resolved from audio time and degrades word timing honestly', () => {
  const cues = normalizeAvatarCueManifest(rawCues)
  assert.deepEqual(resolveAvatarFrame(cues, 200), { viseme: 'sil', speaking: false, precision: 'word' })
  assert.deepEqual(resolveAvatarFrame(cues, 700), { viseme: 'o', speaking: true, precision: 'word' })
  assert.deepEqual(resolveAvatarFrame(cues, 1_200), { viseme: 'a', speaking: true, precision: 'word' })
})

test('compatibility is terminal and low-resource is selected before Pixi initialises', () => {
  assert.equal(selectAvatarPlaybackMode('auto', { reducedMotion: true, webglAvailable: true }), 'compatibility')
  assert.equal(selectAvatarPlaybackMode('auto', { deviceMemoryGb: 2, webglAvailable: true }), 'low_resource')
  assert.equal(selectAvatarPlaybackMode('compatibility', { webglAvailable: true }), 'compatibility')
  assert.equal(selectAvatarPlaybackMode('auto', { deviceMemoryGb: 8, webglAvailable: true }), 'auto')
})

test('the approved platform role has a complete sprite2d manifest', () => {
  const result = normalizeSprite2dManifest(PLATFORM_SPRITE2D_MANIFEST)
  assert.equal(result.schema, 'sprite2d-manifest/v1')
  assert.equal(result.label, '知性讲师')
  assert.equal(result.sprites.mouths.mbp.startsWith('data:image/svg+xml'), true)
  assert.equal(normalizeSprite2dManifest({ schema: 'sprite2d-manifest/v1', sprites: {} }), null)
})
