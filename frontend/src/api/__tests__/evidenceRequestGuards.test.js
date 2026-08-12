import assert from 'node:assert/strict'
import test from 'node:test'

import { resolveCitationPageImageSource } from '../evidenceRequestGuards.js'

test('does not fall back to evidence-v2 for a course citation without an authorized render URL', () => {
  assert.equal(
    resolveCitationPageImageSource({
      courseId: 2,
      documentId: null,
      pageNumber: 6,
      renderUrl: null,
    }),
    null,
  )
})

test('uses the authorized render URL for a course citation', () => {
  assert.deepEqual(
    resolveCitationPageImageSource({
      courseId: 2,
      documentId: null,
      pageNumber: 6,
      renderUrl: '/api/v1/graph/course/2/evidence-render/page-6',
    }),
    {
      kind: 'protected',
      url: '/api/v1/graph/course/2/evidence-render/page-6',
    },
  )
})

test('does not use evidence-v2 when a course citation has a document ID but no render URL', () => {
  assert.equal(
    resolveCitationPageImageSource({
      courseId: 2,
      documentId: 'doc_123',
      pageNumber: 6,
      renderUrl: null,
    }),
    null,
  )
})

test('uses a document page only for the standalone evidence viewer', () => {
  assert.deepEqual(
    resolveCitationPageImageSource({
      courseId: null,
      documentId: 'doc_123',
      pageNumber: 38,
      renderUrl: null,
    }),
    {
      kind: 'document',
      documentId: 'doc_123',
      pageNumber: 38,
    },
  )
})
