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

test('course release gate freezes one corpus lineage with an aligned draft outline and script', () => {
  const source = read('backend/app/services/course_build_service.py')
  assert.match(source, /没有可冻结的课程材料快照/)
  assert.match(source, /freeze_release_retrieval_snapshot/)
  assert.match(source, /发布必须指定同一草稿版本的课程结构与讲稿/)
  assert.match(source, /outline\.corpus_snapshot_id != corpus\.corpus_snapshot_id/)
  assert.match(source, /release\.retrieval_snapshot_id = retrieval\.retrieval_snapshot_id/)
})

test('course builder agent uses the natural-language proposal and evidence APIs, never the DSL creation path', () => {
  const panel = read('frontend/src/app/pages/course/build/CourseBuildAgentPanel.vue')
  const editor = read('frontend/src/api/course_editor.js')
  assert.match(panel, /向备课 Agent 说明你想调整什么/)
  assert.match(panel, /runPrepAgentCommand/)
  assert.match(panel, /getPrepAgentNodeEvidence/)
  assert.match(panel, /接受提案/)
  assert.doesNotMatch(panel, /outline:on_x:title/)
  assert.match(editor, /prep-agent\/commands/)
  assert.match(editor, /prep-agent\/evidence/)
})
