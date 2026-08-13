const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const ROOT = path.resolve(__dirname, '..', '..', '..', '..')
const read = rel => fs.readFileSync(path.join(ROOT, rel), 'utf8')

test('TeachingAgent request forwards only the browser QuestionObservation contract', () => {
  const source = read('frontend/src/api/teaching_agent.js')

  assert.match(source, /question_observation:\s*payload\.questionObservation\s*\?\?\s*null/)
  assert.doesNotMatch(source, /review_target:\s*payload\./)
  assert.doesNotMatch(source, /recommended_playback_rate:\s*payload\./)
})

test('learning-adjustment transition client uses the registered learner-owned routes', () => {
  const source = read('frontend/src/api/learning_adjustments.js')

  assert.match(source, /\/learning-adjustments\/course\/\$\{encodeURIComponent\(courseId\)\}\/recent/)
  assert.match(source, /\/learning-adjustments\/\$\{encodeURIComponent\(adjustmentId\)\}\/\$\{action\}/)
  assert.match(source, /adjustmentPath\(adjustmentId, ['"]apply['"]\)/)
  assert.match(source, /adjustmentPath\(adjustmentId, ['"]return['"]\)/)
  assert.match(source, /adjustmentPath\(adjustmentId, ['"]dismiss['"]\)/)
  assert.match(source, /return_anchor:\s*returnAnchor/)
  assert.match(source, /idempotency_key:\s*idempotencyKey/)
  assert.doesNotMatch(source, /review_target:\s*/)
  assert.doesNotMatch(source, /recommended_playback_rate:\s*/)
})

test('transition idempotency has a browser compatibility fallback when randomUUID is unavailable', () => {
  const source = read('frontend/src/api/learning_adjustments.js')

  assert.match(source, /cryptoApi\?\.randomUUID\?\.\(\)/)
  assert.match(source, /Date\.now\(\)/)
})

test('learning page supplies only a frozen QuestionObservation and waits for a media seek confirmation', () => {
  const source = read('frontend/src/app/pages/learn/LearnPage.vue')

  assert.match(source, /createPlaybackCoordinate/)
  assert.match(source, /getQuestionObservation:\s*\(\)\s*=>\s*getQuestionObservation\(\)/)
  assert.match(source, /@media-seeked="handleMediaSeeked"/)
  assert.match(source, /waitForMediaSeek\(target\)/)
  assert.match(source, /await seeked/)
  assert.match(source, /returnFromLearningAdjustment/)
  assert.match(source, /dismissLearningAdjustment/)
})

test('learning workspace captures the QuestionObservation at send time and preserves the server proposal', () => {
  const source = read('frontend/src/features/student-learning/composables/useLearningWorkspace.js')

  assert.match(source, /const getQuestionObservation\s*=\s*options\?\.getQuestionObservation/)
  assert.match(source, /questionObservation:\s*questionObservation\s*\?\?\s*null/)
  assert.match(source, /const questionObservation\s*=\s*getQuestionObservation\(\)/)
  assert.match(source, /learningAdjustment:\s*result\?\.learningAdjustment\s*\?\?\s*null/)
})

test('course agent panel makes review and return learner-controlled SfxButton actions', () => {
  const source = read('frontend/src/app/components/learn/CourseAgentPanel.vue')

  assert.match(source, /import SfxButton/)
  assert.match(source, /emit\(['"]accept-adjustment['"]/)
  assert.match(source, /emit\(['"]dismiss-adjustment['"]/)
  assert.match(source, /emit\(['"]return-adjustment['"]/)
  assert.match(source, /<SfxButton/)
})

test('learning adjustment keeps an accepted review recoverable when browser navigation fails', () => {
  const page = read('frontend/src/app/pages/learn/LearnPage.vue')
  const stage = read('frontend/src/app/components/learn/LectureStage.vue')
  const panel = read('frontend/src/app/components/learn/CourseAgentPanel.vue')

  assert.match(stage, /emit\('media-error'/)
  assert.match(stage, /@error="handleAudioError"/)
  assert.match(stage, /@error="handleLegacyVideoError"/)
  assert.match(page, /pendingMediaSeek\.value\?\.complete === complete/)
  assert.match(page, /proposal\?\.status === 'applied'/)
  assert.match(page, /retry-opening-review/)
  assert.match(page, /sessionStorage\.setItem\(LEARNING_ADJUSTMENT_STORAGE_KEY/)
  assert.match(page, /sessionStorage\.getItem\(LEARNING_ADJUSTMENT_STORAGE_KEY/)
  assert.match(panel, /retry-opening-review/)
  assert.match(panel, /adjustment\?\.status === 'proposed'/)
})

test('media metadata is not treated as a completed cross-item review seek', () => {
  const stage = read('frontend/src/app/components/learn/LectureStage.vue')
  const metadataStart = stage.indexOf('async function handleLoadedMetadata')
  const metadataEnd = stage.indexOf('function handleTimeUpdate', metadataStart)
  const metadataHandler = stage.slice(metadataStart, metadataEnd)

  assert.ok(metadataStart >= 0 && metadataEnd > metadataStart)
  assert.doesNotMatch(metadataHandler, /emitMediaSeeked\(element\)/)
  assert.match(stage, /function handleSeeked\([\s\S]*?emitMediaSeeked/)
})

test('a media error only fails the pending review for its frozen media item', () => {
  const page = read('frontend/src/app/pages/learn/LearnPage.vue')

  assert.match(page, /function handleMediaError\(payload\)/)
  assert.match(page, /sameIdentifier\(payload\?\.mediaReleaseItemId, pending\.target\?\.media_release_item_id\)/)
})

test('learning adjustment recovery never repeats apply after an ambiguous response or page reload', () => {
  const page = read('frontend/src/app/pages/learn/LearnPage.vue')
  const panel = read('frontend/src/app/components/learn/CourseAgentPanel.vue')

  assert.match(page, /listRecentLearningAdjustments/)
  assert.match(page, /recoverAcceptedLearningAdjustment/)
  assert.match(page, /restoreActiveLearningAdjustment\(\)/)
  assert.match(panel, /hasMessageForActiveAdjustment/)
  assert.match(panel, /v-if="activeAdjustment && !hasMessageForActiveAdjustment\(\)"/)
})
