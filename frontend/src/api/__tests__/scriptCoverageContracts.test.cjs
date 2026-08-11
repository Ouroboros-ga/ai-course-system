const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const root = path.resolve(__dirname, '..', '..', '..', '..')
const read = (relative) => fs.readFileSync(path.join(root, relative), 'utf8')

test('script coverage recovery uses the formal teacher-authored script API', () => {
  const client = read('frontend/src/api/course_editor.js')
  const page = read('frontend/src/app/pages/course/build/BuildScriptsPage.vue')
  const backend = read('backend/app/api/v1/endpoints/course_build_editor.py')

  assert.match(client, /createTeachingScript/)
  assert.match(client, /const base = \(courseId\) => `\/course-editor\/course\/\$\{encodeURIComponent\(courseId\)\}`/)
  assert.match(client, /createTeachingScript = \(courseId, payload\) => request\.post\(`\$\{base\(courseId\)\}\/scripts`, payload\)/)
  assert.match(page, /EVIDENCE_VERIFICATION_FAILED/)
  assert.match(page, /SCRIPT_OUTPUT_MISSING/)
  assert.match(page, /createMissingScript/)
  assert.match(page, /v-if="selected\.has_script"/)
  assert.match(backend, /CourseScriptCoverageIssue/)
  assert.match(backend, /async def create_missing_script/)
})
