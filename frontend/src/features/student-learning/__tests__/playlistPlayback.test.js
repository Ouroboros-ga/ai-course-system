import test from 'node:test'
import assert from 'node:assert/strict'

import { findPlaylistItemIndexById } from '../composables/usePlaylistPlayback.js'

test('finds a frozen playlist item by its immutable item id', () => {
  const items = [
    { itemId: 'mrit_intro', outlineNodeId: 'outline_intro' },
    { itemId: 'mrit_engine', outlineNodeId: 'outline_engine' },
  ]

  assert.equal(findPlaylistItemIndexById(items, 'mrit_engine'), 1)
  assert.equal(findPlaylistItemIndexById(items, 'mrit_missing'), -1)
})
