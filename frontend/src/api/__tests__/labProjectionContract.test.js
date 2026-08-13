import assert from 'node:assert/strict'
import test from 'node:test'

import { labProjectionPaths, courseExperimentPath } from '../labProjectionContract.js'

test('lab projection reads require a course boundary', () => {
  assert.deepEqual(labProjectionPaths(12), {
    catalog: '/lab/catalog?course_id=12',
    courseTasks: '/lab/course-tasks?course_id=12',
    myExperiments: '/lab/my-experiments?course_id=12',
    records: '/lab/records?course_id=12',
  })
})

test('lab cards enter the matching course experiment workspace', () => {
  assert.equal(courseExperimentPath(12), '/app/course/12/experiments')
})
