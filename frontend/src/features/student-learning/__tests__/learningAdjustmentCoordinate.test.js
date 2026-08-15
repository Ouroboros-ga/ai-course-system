import test from 'node:test'
import assert from 'node:assert/strict'

import {
  createPlaybackCoordinate,
  resolveFrozenCoordinateGlobalSeconds,
} from '../adapters/learningAdjustmentCoordinate.js'

const item = {
  itemId: 'mrit_engine',
  nodeId: 71,
  outlineNodeId: 'outline_engine',
  offsetMs: 120_000,
  durationMs: 90_000,
}

const cue = {
  nodeId: 71,
  outlineNodeId: 'outline_engine',
  page: 17,
  startMs: 130_000,
}

test('creates an item-local QuestionObservation from the frozen playback coordinate', () => {
  assert.deepEqual(createPlaybackCoordinate({
    courseReleaseId: 'cr_20260813',
    mediaReleaseId: 'mrel_20260813',
    item,
    cue,
    globalTimeSeconds: 193.42,
  }), {
    course_release_id: 'cr_20260813',
    media_release_id: 'mrel_20260813',
    media_release_item_id: 'mrit_engine',
    outline_node_id: 'outline_engine',
    local_time_ms: 73_420,
    page: 17,
    global_time_ms: 193_420,
  })
})

test('refuses a coordinate when any immutable release, item, cue, or page evidence is absent', () => {
  const valid = {
    courseReleaseId: 'cr_20260813',
    mediaReleaseId: 'mrel_20260813',
    item,
    cue,
    globalTimeSeconds: 193.42,
  }

  for (const patch of [
    { courseReleaseId: null },
    { mediaReleaseId: null },
    { item: { ...item, itemId: null } },
    { cue: null },
    { cue: { ...cue, page: null } },
    { globalTimeSeconds: 220.001 },
  ]) {
    assert.equal(createPlaybackCoordinate({ ...valid, ...patch }), null)
  }
})

test('refuses a cue that does not belong to the active immutable playlist item', () => {
  assert.equal(createPlaybackCoordinate({
    courseReleaseId: 'cr_20260813',
    mediaReleaseId: 'mrel_20260813',
    item,
    cue: { ...cue, outlineNodeId: 'outline_other', nodeId: 72 },
    globalTimeSeconds: 193.42,
  }), null)
})

test('uses the item offset when a valid frozen coordinate has no global clock', () => {
  assert.equal(resolveFrozenCoordinateGlobalSeconds({
    media_release_item_id: 'mrit_engine',
    local_time_ms: 73_420,
    global_time_ms: null,
  }, item), 193.42)
})
