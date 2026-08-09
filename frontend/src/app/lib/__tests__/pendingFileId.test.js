import assert from 'node:assert/strict'
import test from 'node:test'

import { createPendingFileId } from '../pendingFileId.js'


const file = { name: '课程材料.pdf', size: 42, lastModified: 123 }

test('uses randomUUID when the browser exposes it', () => {
  const id = createPendingFileId(file, {
    crypto: { randomUUID: () => 'uuid-value' },
  })
  assert.equal(id, '课程材料.pdf:42:123:uuid-value')
})

test('falls back without throwing in an HTTP-style context', () => {
  const id = createPendingFileId(file, {
    crypto: {},
    now: () => 1_700_000_000_000,
    random: () => 0.5,
  })
  assert.match(id, /^课程材料\.pdf:42:123:[a-z0-9]+-[a-z0-9]+$/)
})
