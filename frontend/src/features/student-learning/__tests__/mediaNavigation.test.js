import test from 'node:test'
import assert from 'node:assert/strict'

import {
  findPlaylistItemIndex,
  findPlaylistItemIndexAtTime,
  isActiveAudioClockEvent,
  resolveActiveAudioClock,
  resolveMediaPlaybackProjection,
  resolvePlaylistPlaybackTarget,
  resolvePlaylistSelection,
  resolveTimelinePlaybackTarget,
  shouldSeekMediaClock,
} from '../composables/usePlaylistPlayback.js'

const items = [
  { nodeId: 11, outlineNodeId: 'n-11', offsetMs: 0, durationMs: 2_000 },
  { nodeId: 12, outlineNodeId: 'n-12', offsetMs: 2_000, durationMs: 3_000 },
]

test('playlist node matching prefers node id and falls back to outline node id', () => {
  assert.equal(findPlaylistItemIndex(items, { id: 12, outlineNodeId: 'n-other' }), 1)
  assert.equal(findPlaylistItemIndex(items, { id: 999, outlineNodeId: 'n-11' }), 0)
  assert.equal(findPlaylistItemIndex(items, { id: 999, outlineNodeId: 'missing' }), -1)
})

test('playlist time mapping uses global item boundaries', () => {
  assert.equal(findPlaylistItemIndexAtTime(items, 0), 0)
  assert.equal(findPlaylistItemIndexAtTime(items, 1.999), 0)
  assert.equal(findPlaylistItemIndexAtTime(items, 2), 1)
  assert.equal(findPlaylistItemIndexAtTime(items, 5), -1)
})

test('directory selection uses playlist offset and legacy timestamp fallback', () => {
  assert.deepEqual(resolvePlaylistSelection(items, { id: 12, timestampStart: 99 }), {
    playlistIndex: 1,
    targetTime: 2,
  })
  assert.deepEqual(resolvePlaylistSelection([], { id: 99, timestampStart: 7.5 }), {
    playlistIndex: -1,
    targetTime: 7.5,
  })
})

test('shared course audio remains a global clock when playlist items lack audio URLs', () => {
  const clock = resolveActiveAudioClock(items, 1, '/content/course-audio.wav')

  assert.deepEqual(clock, {
    audioUrl: '/content/course-audio.wav',
    offsetSeconds: 0,
    segmented: false,
    generation: 'shared:/content/course-audio.wav',
  })
})

test('audio event generation rejects a stale segmented event when adjacent clips share a URL', () => {
  const clips = [
    { ...items[0], audioUrl: '/content/reused-clip.wav' },
    { ...items[1], audioUrl: '/content/reused-clip.wav' },
  ]
  const initial = resolveActiveAudioClock(clips, 0, '')
  const current = resolveActiveAudioClock(clips, 1, '')

  assert.equal(isActiveAudioClockEvent(initial.generation, current.generation), false)
  assert.equal(isActiveAudioClockEvent(current.generation, current.generation), true)
})

test('explicit seek applies a sub-second shared-clock move that normal clock updates debounce', () => {
  assert.equal(shouldSeekMediaClock(30, 30.5), false)
  assert.equal(shouldSeekMediaClock(30, 30.5, true), true)
})

test('legacy release navigation uses its frozen cue clock instead of zero node timestamps', () => {
  const releasedNodes = [
    { id: 'outline-1', outlineNodeId: 'outline-1', timestampStart: 0, timestampEnd: 0 },
    { id: 'outline-2', outlineNodeId: 'outline-2', timestampStart: 0, timestampEnd: 0 },
  ]
  const timeline = [
    { nodeId: 101, outlineNodeId: 'outline-1', startMs: 0, endMs: 12_000 },
    { nodeId: 102, outlineNodeId: 'outline-2', startMs: 12_000, endMs: 25_000 },
  ]

  assert.deepEqual(resolvePlaylistSelection([], releasedNodes[1], timeline), {
    playlistIndex: -1,
    targetTime: 12,
  })
  assert.deepEqual(resolveTimelinePlaybackTarget(timeline, releasedNodes, 14, 0), {
    nodeIndex: 1,
    nodeId: 102,
    outlineNodeId: 'outline-2',
  })
})

test('playlist playback resolves the directory node without legacy node timestamps', () => {
  // Published CourseRelease nodes intentionally retain no legacy media timing.
  // A regression here makes every positive audio time select the final node.
  const releasedNodes = [
    { id: 'n-11', outlineNodeId: 'n-11', timestampStart: 0, timestampEnd: 0 },
    { id: 'n-12', outlineNodeId: 'n-12', timestampStart: 0, timestampEnd: 0 },
  ]

  assert.deepEqual(resolvePlaylistPlaybackTarget(items, releasedNodes, 0.5, 1), {
    playlistIndex: 0,
    nodeIndex: 0,
  })
  assert.deepEqual(resolvePlaylistPlaybackTarget(items, releasedNodes, 2.5, 0), {
    playlistIndex: 1,
    nodeIndex: 1,
  })
  // A terminal/gap event belongs to the currently keyed audio item, not to
  // the legacy zero-duration timeline.
  assert.deepEqual(resolvePlaylistPlaybackTarget(items, releasedNodes, 5, 1), {
    playlistIndex: 1,
    nodeIndex: 1,
  })
})

test('frozen media time projects directory, playlist, and PPT state together', () => {
  const releasedNodes = [
    { id: 'n-11', outlineNodeId: 'n-11', timestampStart: 0, timestampEnd: 0 },
    { id: 'n-12', outlineNodeId: 'n-12', timestampStart: 0, timestampEnd: 0 },
  ]
  const timeline = [
    { nodeId: 11, outlineNodeId: 'n-11', page: 3, materialVersionId: 'primary', startMs: 0 },
    { nodeId: 12, outlineNodeId: 'n-12', page: 4, materialVersionId: 'primary', startMs: 2_000 },
  ]

  assert.deepEqual(resolveMediaPlaybackProjection(items, releasedNodes, timeline, 2.5, 0), {
    playlistIndex: 1,
    nodeIndex: 1,
    nodeId: 12,
    outlineNodeId: 'n-12',
    page: 4,
    materialVersionId: 'primary',
  })
})
