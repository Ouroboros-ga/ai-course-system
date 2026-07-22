import assert from 'node:assert/strict'
import test from 'node:test'

import { citationToPptLocator, snapshotToCanvasGraph } from '../contracts.js'

test('citation click locator retains the exact PPT page, block, and citation key', () => {
  const locator = citationToPptLocator(
    { course_id: 'EE101', page_or_slide: 3, block_id: 'blk-hit' },
    { research_evidence_id: 'ev-3', citation_key: 'cite-3', page_or_slide: 7, block_id: 'blk-7' },
  )
  assert.deepEqual(locator, {
    courseId: 'EE101', pageOrSlide: 7, blockId: 'blk-7', citationKey: 'cite-3', evidenceId: 'ev-3',
  })
})

test('graph adapter keeps only accepted deterministic edges and known node types', () => {
  const graph = snapshotToCanvasGraph({
    nodes: [
      { node_id: 'course', node_type: 'Course', course_id: 'EE101', source_id: 'EE101', properties: {} },
      { node_id: 'slide', node_type: 'PPTSlide', course_id: 'EE101', source_id: 's1', properties: { slide_number: 7 } },
      { node_id: 'bad', node_type: 'SemanticGuess', course_id: 'EE101', source_id: 'bad', properties: {} },
    ],
    edges: [
      { subject_node_id: 'course', object_node_id: 'slide', predicate: 'CONTAINS', status: 'accepted', research_evidence_ids: [] },
      { subject_node_id: 'course', object_node_id: 'slide', predicate: 'RELATED_TO', status: 'accepted', research_evidence_ids: [] },
      { subject_node_id: 'course', object_node_id: 'slide', predicate: 'CONTAINS', status: 'candidate', research_evidence_ids: [] },
    ],
  })
  assert.equal(graph.nodes.length, 2)
  assert.equal(graph.nodes[1].kind, 'ppt_slide')
  assert.deepEqual(graph.edges, [{ source: 'course', target: 'slide', kind: 'contains', predicate: 'CONTAINS', evidenceIds: [] }])
})
