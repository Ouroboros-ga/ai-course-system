import test from 'node:test'
import assert from 'node:assert/strict'

import { readBooleanFlag } from '../featureFlags.js'

test('feature flags require an explicit true value', () => {
  assert.equal(readBooleanFlag(undefined), false)
  assert.equal(readBooleanFlag('false'), false)
  assert.equal(readBooleanFlag('1'), false)
  assert.equal(readBooleanFlag('true'), true)
  assert.equal(readBooleanFlag(' TRUE '), true)
})
