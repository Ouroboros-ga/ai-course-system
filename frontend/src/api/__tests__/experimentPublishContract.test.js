import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildVersionRequest,
  experimentPublishPaths,
} from '../experimentPublishContract.js'

test('teacher publishing stays course-scoped through version preview lock and publish', () => {
  assert.deepEqual(experimentPublishPaths(42, 'exp-1', 'expv-1'), {
    definitions: '/experiments/course/42/definitions',
    definition: '/experiments/course/42/definitions/exp-1',
    versions: '/experiments/exp-1/versions?course_id=42',
    preview: '/experiments/versions/expv-1/reference-preview?course_id=42',
    lock: '/experiments/versions/expv-1/lock?course_id=42',
    publish: '/experiments/course/42/definitions/exp-1/publish',
  })
})

test('teacher version request enforces ACM payload fields and preserves hidden test metadata', () => {
  assert.deepEqual(buildVersionRequest({
    label: '  first release  ',
    cpuTimeLimit: '5',
    memoryLimit: '128000',
    wallTimeLimit: '10',
    maxProcesses: '30',
    maxFileSize: '1024',
    testCases: [
      { case_name: 'visible', stdin: '1\n', expected_stdout: '1\n', is_hidden: false, weight: '0.4' },
      { case_name: 'edge', stdin: '0\n', expected_stdout: '0\n', is_hidden: true, weight: '0.6' },
    ],
  }), {
    label: 'first release',
    cpu_time_limit: 5,
    memory_limit: 128000,
    wall_time_limit: 10,
    max_processes: 30,
    max_file_size: 1024,
    passing_score: 1,
    writes_formal_evidence: true,
    activate: true,
    test_cases: [
      { case_name: 'visible', stdin: '1\n', expected_stdout: '1\n', is_hidden: false, weight: 0.4 },
      { case_name: 'edge', stdin: '0\n', expected_stdout: '0\n', is_hidden: true, weight: 0.6 },
    ],
  })
})
