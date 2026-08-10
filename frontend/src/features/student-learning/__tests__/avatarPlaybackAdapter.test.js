import test from 'node:test'
import assert from 'node:assert/strict'

import {
  normalizeAvatarCueManifest,
  resolveAvatarFrame,
  selectAvatarPlaybackMode,
} from '../adapters/avatarPlaybackAdapter.js'
import { normalizeSprite2dManifest } from '../adapters/platformSprite2dAssets.js'

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

test('portrait patch preset resolves only release-signed object textures', () => {
  const objectKey = key => `platform/avatar-presets/platform-female-instructor-v1/1.0.0/assets/${key}.png`
  const sprite = key => ({ object_key: objectKey(key) })
  const manifest = {
    schema: 'sprite2d-manifest/v1',
    render_mode: 'portrait_patch_v1',
    stage: { width: 480, height: 480 },
    layout: {
      body: { x: 240, y: 240, width: 480, height: 480 },
      eyes: { x: 240, y: 151, width: 151, height: 41 },
      mouth: { x: 240, y: 218, width: 96, height: 45 },
    },
    sprites: {
      body: sprite('body'),
      head: sprite('transparent'),
      eyes: sprite('eyes-closed'),
      mouths: Object.fromEntries(['sil', 'a', 'e', 'i', 'o', 'u', 'fv', 'mbp'].map(key => [key, sprite(`mouth-${key}`)])),
    },
  }
  const signedUrls = Object.fromEntries([
    'body', 'transparent', 'eyes-closed',
    'mouth-sil', 'mouth-a', 'mouth-e', 'mouth-i', 'mouth-o', 'mouth-u', 'mouth-fv', 'mouth-mbp',
  ].map(key => [objectKey(key), `/api/v1/media/assets/${key}?sig=signed`]))

  assert.equal(normalizeSprite2dManifest(manifest), null)
  const result = normalizeSprite2dManifest(manifest, signedUrls)
  assert.equal(result.renderMode, 'portrait_patch_v1')
  assert.equal(result.sprites.body, '/api/v1/media/assets/body?sig=signed')
  assert.equal(result.sprites.mouths.o, '/api/v1/media/assets/mouth-o?sig=signed')
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

test('a malformed platform manifest is rejected rather than replaced with another role', () => {
  assert.equal(normalizeSprite2dManifest({ schema: 'sprite2d-manifest/v1', sprites: {} }), null)
})
