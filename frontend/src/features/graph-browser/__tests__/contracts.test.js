import test from 'node:test'
import assert from 'node:assert/strict'

import { assertGraphBrowserSchema } from '../contracts.js'

test('accepts the exact frozen graph browser schema version', () => {
  assert.equal(assertGraphBrowserSchema('graph-browser/1.0'), true)
})

test('fails closed for a different graph browser schema version', () => {
  assert.throws(
    () => assertGraphBrowserSchema('graph-browser/1.1'),
    /Unknown graph browser schema version/,
  )
})
