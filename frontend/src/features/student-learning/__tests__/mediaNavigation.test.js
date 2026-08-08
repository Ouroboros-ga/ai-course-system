import test from 'node:test'
import assert from 'node:assert/strict'

import {
  findPlaylistItemIndex,
  findPlaylistItemIndexAtTime,
  resolvePlaylistSelection,
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
