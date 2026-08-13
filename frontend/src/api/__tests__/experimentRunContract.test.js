import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildFormalRunRequest,
  isTerminalTaskStatus,
  runResourcePaths,
  shouldOfferFormalRunRetry,
} from '../experimentRunContract.js'

test('formal experiment submission uses the durable 202 route and idempotency header', () => {
  assert.deepEqual(
    buildFormalRunRequest('attempt-1', 42, {
      language: 'python',
      source_code: 'print(1)',
    }, 'submission-1'),
    {
      url: '/experiments/attempts/attempt-1/runs?course_id=42',
      body: { language: 'python', source_code: 'print(1)' },
      config: {
        headers: { 'Idempotency-Key': 'submission-1' },
        skipErrorToast: true,
      },
    },
  )
})

test('run resource paths stay course-scoped and omit legacy synchronous flags', () => {
  const paths = runResourcePaths(42, 'run-9')

  assert.deepEqual(paths, {
    run: '/experiments/runs/run-9?course_id=42',
    cancel: '/experiments/runs/run-9/cancel?course_id=42',
    explanation: '/experiments/runs/run-9/explanation?course_id=42',
  })
  assert.equal(Object.values(paths).some((path) => path.includes('async_run')), false)
})

test('only terminal task states permit a formal run result read', () => {
  assert.equal(isTerminalTaskStatus('pending'), false)
  assert.equal(isTerminalTaskStatus('running'), false)
  assert.equal(isTerminalTaskStatus('succeeded'), true)
  assert.equal(isTerminalTaskStatus('failed'), true)
  assert.equal(isTerminalTaskStatus('cancelled'), true)
  assert.equal(isTerminalTaskStatus('interrupted'), true)
})

test('only a retryable sandbox outage exposes the formal assessment retry action', () => {
  assert.equal(
    shouldOfferFormalRunRetry(
      { status: 'failed', retryable: true },
      { outcome: 'sandbox_unavailable' },
    ),
    true,
  )
  assert.equal(
    shouldOfferFormalRunRetry(
      { status: 'failed', retryable: false },
      { outcome: 'sandbox_unavailable' },
    ),
    false,
  )
  assert.equal(
    shouldOfferFormalRunRetry(
      { status: 'succeeded', retryable: true },
      { outcome: 'accepted' },
    ),
    false,
  )
})
