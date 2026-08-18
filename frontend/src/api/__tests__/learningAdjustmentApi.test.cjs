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

test('strict TeachingAgent and learning-adjustment DTOs keep signer fields out of JSON bodies', () => {
    const teachingSource = read('frontend/src/api/teaching_agent.js')
    const adjustmentSource = read('frontend/src/api/learning_adjustments.js')

    assert.match(teachingSource, /url:\s*['"]\/teaching-agent\/respond['"][\s\S]*?signatureInQuery:\s*true/)
    assert.match(teachingSource, /url:\s*['"]\/teaching-agent\/respond-for-learner['"][\s\S]*?signatureInQuery:\s*true/)
    assert.equal((adjustmentSource.match(/signatureInQuery:\s*true/g) || []).length, 3)
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
    // 展示层拆分后，回顾/返回动作收敛到 AgentAssistantBubble（SfxButton 由它渲染）
    const bubble = read('frontend/src/app/components/learn/AgentAssistantBubble.vue')

    assert.match(bubble, /import SfxButton/)
    assert.match(bubble, /emit\(['"]accept-adjustment['"]/)
    assert.match(bubble, /emit\(['"]dismiss-adjustment['"]/)
    assert.match(bubble, /emit\(['"]return-adjustment['"]/)
    assert.match(bubble, /<SfxButton/)
})

test('learning adjustment keeps an accepted review recoverable when browser navigation fails', () => {
    const page = read('frontend/src/app/pages/learn/LearnPage.vue')
    const stage = read('frontend/src/app/components/learn/LectureStage.vue')
    // 拆分后回顾重试/可见性判定逻辑收敛到 AgentAssistantBubble
    const bubble = read('frontend/src/app/components/learn/AgentAssistantBubble.vue')

    assert.match(stage, /emit\('media-error'/)
    assert.match(stage, /@error="handleAudioError"/)
    assert.match(stage, /@error="handleLegacyVideoError"/)
    assert.match(page, /pendingMediaSeek\.value\?\.complete === complete/)
    assert.match(page, /proposal\?\.status === 'applied'/)
    assert.match(page, /retry-opening-review/)
    assert.match(page, /sessionStorage\.setItem\(LEARNING_ADJUSTMENT_STORAGE_KEY/)
    assert.match(page, /sessionStorage\.getItem\(LEARNING_ADJUSTMENT_STORAGE_KEY/)
    assert.match(bubble, /retry-opening-review/)
    assert.match(bubble, /adjustment\?\.status === 'proposed'/)
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
    // hasMessageForActiveAdjustment 为列表级判定，拆分后位于 AgentMessageList
    const messageList = read('frontend/src/app/components/learn/AgentMessageList.vue')

    assert.match(page, /listRecentLearningAdjustments/)
    assert.match(page, /recoverAcceptedLearningAdjustment/)
    assert.match(page, /restoreActiveLearningAdjustment\(\)/)
    assert.match(messageList, /hasMessageForActiveAdjustment/)
    // 2026-08-18 对账：旧行为"无来源消息也常驻显示已确认回顾框"已被有意移除
    // （AgentMessageList 注释：仅显示错误/提示，不再把已确认回顾作为无来源的持久化框常驻）。
    // 全局提示区现在只承载一次性 notice 文本，不渲染持久回顾框。
    assert.doesNotMatch(messageList, /v-if="activeAdjustment && !hasMessageForActiveAdjustment\(\)"/)
    assert.match(messageList, /v-if="adjustmentNotice"/)
})

test('stale accepted adjustment is validated against the server on restore and can be abandoned', () => {
    const page = read('frontend/src/app/pages/learn/LearnPage.vue')
    const bubble = read('frontend/src/app/components/learn/AgentAssistantBubble.vue')
    const panel = read('frontend/src/app/components/learn/CourseAgentPanel.vue')
    const messageList = read('frontend/src/app/components/learn/AgentMessageList.vue')

    // 恢复时先向后端校验该 applied 提案仍存在；不存在则清除残留状态（2026-08-18）
    assert.match(page, /async function restoreActiveLearningAdjustment\(\)/)
    assert.match(page, /await listRecentLearningAdjustments\(courseId, \{ limit: 20 \}\)/)
    assert.match(page, /item\?\.status === 'applied'/)
    assert.match(page, /stillApplied/)
    assert.match(page, /clearActiveLearningAdjustment\(\)/)

    // 激活态卡死时提供"放弃回顾"出口，事件链路 Bubble → MessageList → Panel → LearnPage
    assert.match(page, /function abandonActiveLearningAdjustment\(\)/)
    assert.match(page, /clearActiveLearningAdjustment\(\)\n\s*learningAdjustmentNotice\.value = ''/)
    assert.match(page, /@abandon-adjustment="abandonActiveLearningAdjustment"/)
    assert.match(bubble, /emit\(['"]abandon-adjustment['"]/)
    assert.match(bubble, />放弃回顾<\/SfxButton>/)
    assert.match(panel, /emit\(['"]abandon-adjustment['"]\)/)
    assert.match(messageList, /@abandon-adjustment="\(\) => emit\('abandon-adjustment'\)"/)
})
