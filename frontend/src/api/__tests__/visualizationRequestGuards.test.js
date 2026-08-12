import assert from 'node:assert/strict'
import test from 'node:test'

import { sanitizePlanListParams } from '../visualizationRequestGuards.js'

test('omits an outline-node ID from the legacy integer visualization filter', () => {
  assert.deepEqual(
    sanitizePlanListParams({
      node_id: 'on_0b0ab2ff6f344c9ca0aa48f44d45cdcc',
      status: 'published',
    }),
    { status: 'published' },
  )
})

test('retains a positive numeric visualization node filter', () => {
  assert.deepEqual(
    sanitizePlanListParams({ node_id: '12', status: 'published' }),
    { node_id: 12, status: 'published' },
  )
})
