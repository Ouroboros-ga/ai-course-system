import test from 'node:test'
import assert from 'node:assert/strict'
import {
  isCodeSandboxExperimentPlatformEnabled,
  withCodeSandboxExperimentPlatform,
} from '../courseExperimentPlatform.js'

test('disabled code sandbox hides the current experiment platform', () => {
  assert.equal(
    isCodeSandboxExperimentPlatformEnabled({ experiment: true, coding_sandbox: false }),
    false,
  )
})

test('switching the current code-sandbox platform changes both coupled flags', () => {
  assert.deepEqual(
    withCodeSandboxExperimentPlatform(
      { learning: true, experiment: true, coding_sandbox: true },
      false,
    ),
    { learning: true, experiment: false, coding_sandbox: false },
  )
})

test('platform switch preserves unrelated course capabilities', () => {
  assert.deepEqual(
    withCodeSandboxExperimentPlatform(
      { learning: true, knowledge_graph: true, experiment: false, coding_sandbox: false },
      true,
    ),
    { learning: true, knowledge_graph: true, experiment: true, coding_sandbox: true },
  )
})
