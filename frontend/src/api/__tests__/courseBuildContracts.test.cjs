const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const root = path.resolve(__dirname, '..', '..', '..', '..')
const read = (relative) => fs.readFileSync(path.join(root, relative), 'utf8')

test('new course-build client uses the formal outline, script, proposal and unified upload APIs', () => {
  const source = read('frontend/src/api/course_build.js')
  assert.match(source, /outlines\/drafts/)
  assert.match(source, /\/scripts\//)
  assert.match(source, /\/patch-proposals/)
  assert.match(source, /\/courses\/\$\{encodeURIComponent\(courseId\)\}\/materials/)
  assert.match(source, /createCourseWorkspace/)
  assert.doesNotMatch(source, /createBuildMaterial|markBuildMaterialParse/)
})

test('new construction backend guards all teacher mutations with Course Access v1', () => {
  const source = read('backend/app/api/v1/endpoints/course_outline.py')
  assert.match(source, /@course_outline_router\.post\(["']\/course\/\{course_id\}\/outlines\/drafts["']\)/)
  assert.match(source, /@course_outline_router\.post\(["']\/course\/\{course_id\}\/patch-proposals\/\{proposal_id\}\/decide["']\)/)
  assert.match(source, /"course\.structure\.edit"/)
  assert.match(source, /"course\.script\.edit"/)
  assert.match(source, /"course\.publish"/)
  assert.match(source, /_require_draft_outline/)
  assert.match(source, /_require_draft_script/)
})

test('course release gate requires published CourseOutline and an aligned TeachingScript', () => {
  const source = read('backend/app/services/course_build_service.py')
  assert.match(source, /"outline\.published"/)
  assert.match(source, /"script\.published_for_outline"/)
  assert.match(source, /published_script\.outline_version_id == published_outline\.outline_version_id/)
})
