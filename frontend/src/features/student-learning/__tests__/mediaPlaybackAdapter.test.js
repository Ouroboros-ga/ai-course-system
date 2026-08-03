import test from 'node:test'
import assert from 'node:assert/strict'

import {
  findActiveSubtitleIndex,
  normalizeMediaPlayback,
  resolvePptCueAtTime,
  resolvePptPageAtTime,
} from '../adapters/mediaPlaybackAdapter.js'

const playbackManifest = {
  available: true,
  release_id: 'mrel_demo',
  audio_url: 'https://example.invalid/lecture.mp3',
  duration_ms: 46_320,
  subtitle_segments: [
    { node_id: 12, start_ms: 0, end_ms: 1_000, text: '第一段讲解' },
    { node_id: 12, start_ms: 1_001, end_ms: 2_000, text: '第二段讲解' },
  ],
  ppt_timeline: [
    { node_id: 12, ppt_page: 3, material_version_id: 'smv_primary', start_ms: 0 },
    { node_id: 13, ppt_page: 4, material_version_id: 'smv_appendix', start_ms: 1_500 },
  ],
  ppt: {
    schema: 'ppt-manifest/v1',
    manifest_url: '/api/v1/media/assets/ppt-manifest/manifest.json/content?exp=1&sig=x',
    source_sha256: 'abc',
    primary_material_version_id: 'smv_primary',
    pages: [
      { page: 1, image_url: '/api/v1/media/assets/ppt-manifest/page-1.png/content?exp=1&sig=y', width: 1920, height: 1080 },
    ],
    decks: [
      {
        material_version_id: 'smv_primary',
        material_name: 'Primary deck',
        pages: [
          { page: 3, image_url: '/api/v1/media/assets/ppt-manifest/primary-3.png/content?exp=1&sig=y', width: 1920, height: 1080 },
        ],
      },
      {
        material_version_id: 'smv_appendix',
        material_name: 'Appendix',
        pages: [
          { page: 4, image_url: '/api/v1/media/assets/ppt-manifest/appendix-4.png/content?exp=1&sig=y', width: 1920, height: 1080 },
        ],
      },
    ],
  },
  avatar_cues: {
    schema: 'avatar-cues/v1',
    manifest_url: '/api/v1/media/assets/avatar-cues/manifest.json/content?exp=1&sig=z',
    timing_source: 'words',
    precision: 'word',
    content_sha256: 'cue-sha',
  },
}

test('normalizes the frozen learner playback manifest without provider fields', () => {
  const result = normalizeMediaPlayback(playbackManifest)
  assert.equal(result.available, true)
  assert.equal(result.audioUrl, playbackManifest.audio_url)
  assert.equal(result.durationMs, 46_320)
  assert.deepEqual(result.subtitleSegments[0], {
    index: 0,
    nodeId: 12,
    startMs: 0,
    endMs: 1_000,
    text: '第一段讲解',
    scriptReference: null,
  })
  assert.equal(result.digitalHumanManifest, null)
  assert.equal(result.avatarCues.schema, 'avatar-cues/v1')
  assert.equal(result.avatarCues.precision, 'word')
  assert.equal(result.ppt.schema, 'ppt-manifest/v1')
  assert.equal(result.ppt.primaryMaterialVersionId, 'smv_primary')
  assert.equal(result.ppt.pages[0].imageUrl.includes('page-1.png'), true)
  assert.equal(result.ppt.decks[1].pages[0].imageUrl.includes('appendix-4.png'), true)
})

test('resolves PPT and subtitle state from the single audio clock', () => {
  const result = normalizeMediaPlayback(playbackManifest)
  assert.equal(resolvePptPageAtTime(result.pptTimeline, 500), 3)
  assert.equal(resolvePptPageAtTime(result.pptTimeline, 1_500), 4)
  assert.equal(resolvePptCueAtTime(result.pptTimeline, 1_500).materialVersionId, 'smv_appendix')
  assert.equal(result.pptTimeline[0].outlineNodeId, null)
  assert.equal(result.pptTimeline[0].endMs, 0)
  assert.equal(findActiveSubtitleIndex(result.subtitleSegments, 1_250), 1)
  assert.equal(findActiveSubtitleIndex(result.subtitleSegments, 2_500), -1)
})

test('resolves one knowledge point across multiple PPT decks in sequence', () => {
  const result = normalizeMediaPlayback({
    ...playbackManifest,
    ppt_timeline: [
      { node_id: 12, ppt_page: 3, material_version_id: 'smv_primary', start_ms: 0 },
      { node_id: 12, ppt_page: 4, material_version_id: 'smv_primary', start_ms: 1_000 },
      { node_id: 12, ppt_page: 8, material_version_id: 'smv_appendix', start_ms: 2_000 },
    ],
  })
  assert.equal(resolvePptCueAtTime(result.pptTimeline, 1_500).nodeId, 12)
  assert.equal(resolvePptCueAtTime(result.pptTimeline, 1_500).page, 4)
  assert.equal(resolvePptCueAtTime(result.pptTimeline, 2_500).materialVersionId, 'smv_appendix')
  assert.equal(resolvePptPageAtTime(result.pptTimeline, 2_500), 8)
})

test('keeps an unmapped PPT cue unmapped instead of defaulting to page one', () => {
  const result = normalizeMediaPlayback({
    available: true,
    ppt_timeline: [{ node_id: 3, ppt_page: null, start_ms: 0, end_ms: 1_000 }],
  })
  assert.equal(result.pptTimeline[0].page, null)
  assert.equal(resolvePptPageAtTime(result.pptTimeline, 500), null)
})
