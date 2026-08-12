import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildProgressPayload,
  findNodeIndexAtTime,
  normalizePlayerData,
  resolvePageAtTime,
} from '../adapters/playerWorkspaceAdapter.js'

const rawPlayer = {
  course_id: 12,
  course_title: '数据结构',
  total_duration: 120,
  nodes: [
    {
      id: 1,
      node_index: 1,
      title: '顺序表',
      timestamp_start: 0,
      timestamp_end: 60,
      page_start: 2,
      page_end: 3,
      video_url: '/api/v1/video/stream/1.mp4',
    },
    {
      id: 2,
      node_index: 2,
      title: '链表',
      timestamp_start: 60,
      timestamp_end: 120,
      page_start: 4,
      page_end: 4,
    },
  ],
  slide_images: [{ page: 2, url: '/slide/2' }],
  saved_progress: {
    current_timestamp: 75,
    current_node_index: 1,
    current_page: 4,
    completion_rate: 0.5,
  },
}

test('normalizes the existing player contract without inventing data', () => {
  const result = normalizePlayerData(rawPlayer)
  assert.equal(result.courseId, 12)
  assert.equal(result.nodes[0].videoUrl, '/api/v1/video/stream/1.mp4')
  assert.equal(result.nodes[1].mediaStatus, 'unavailable')
  assert.equal(result.savedProgress.currentNodeIndex, 1)
  assert.equal(result.savedProgress.completionRate, 50)
})

test('keeps global playback time aligned with nodes and pages', () => {
  const { nodes } = normalizePlayerData(rawPlayer)
  assert.equal(findNodeIndexAtTime(nodes, 61), 1)
  assert.equal(resolvePageAtTime(nodes[0], 30), 3)
})

test('does not treat an all-zero legacy timeline as the final knowledge point', () => {
  const releaseNodes = [
    { timestampStart: 0, timestampEnd: 0 },
    { timestampStart: 0, timestampEnd: 0 },
    { timestampStart: 0, timestampEnd: 0 },
  ]

  assert.equal(findNodeIndexAtTime(releaseNodes, 3), 0)
})

test('adapts workspace state to the backend snake-case progress contract', () => {
  assert.deepEqual(
    buildProgressPayload({
      courseId: 12,
      currentNodeId: 2,
      currentTime: 75,
      currentPage: 4,
      completedNodes: [1],
    }),
    {
      course_id: 12,
      current_node_id: 2,
      current_timestamp: 75,
      current_page: 4,
      completed_nodes: [1],
    }
  )
})
