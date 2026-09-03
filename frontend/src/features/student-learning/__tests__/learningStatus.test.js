import test from 'node:test'
import assert from 'node:assert/strict'
import {
  getCognitionDisplayState,
  getNodeDisplayState,
  summarizeLearningItems,
} from '../learningStatus.js'

test('知识点学习状态独立映射未学习、学习中、已完成', () => {
  assert.equal(getNodeDisplayState({ learning: { status: 'not_started' }, cognition: { status: 'unknown' } }).label, '未学习')
  assert.equal(getNodeDisplayState({ learning: { status: 'in_progress' }, cognition: { mastery_level: 'proficient' } }).label, '学习中')
  const pending = getNodeDisplayState({ learning: { status: 'completed' }, cognition: { status: 'unknown' } })
  assert.deepEqual(
    { key: pending.key, label: pending.label, tone: pending.tone, iconName: pending.iconName },
    { key: 'completed', label: '已完成', tone: 'green', iconName: 'completed' },
  )
  assert.equal(pending.cognitionHint?.key, 'more-evidence')
})

test('完成后认知结论显示已掌握/待掌握；无结论时主状态保持已完成', () => {
  assert.equal(getNodeDisplayState({ learning: { status: 'completed' }, cognition: { mastery_level: 'proficient' } }).label, '已掌握')
  assert.equal(getNodeDisplayState({ learning: { status: 'completed' }, cognition: { mastery_level: 'beginner' } }).label, '待掌握')
  const notAvailable = getNodeDisplayState({ learning: { status: 'completed' }, cognition: { status: 'not_available' } })
  assert.deepEqual(
    { key: notAvailable.key, label: notAvailable.label, tone: notAvailable.tone, iconName: notAvailable.iconName },
    { key: 'completed', label: '已完成', tone: 'green', iconName: 'completed' },
  )
  assert.equal(notAvailable.cognitionHint?.label, '暂不可分析')
  const degraded = getNodeDisplayState({ learning: { status: 'completed' }, cognition: { status: 'degraded' } })
  assert.equal(degraded.label, '已完成')
  assert.equal(degraded.cognitionHint?.label, '认知暂不可用')
  assert.equal(getCognitionDisplayState({ status: 'unknown' }).label, '需要更多证据')
})

test('14 个知识点摘要使用正式学习状态作为完成率分母', () => {
  const items = Array.from({ length: 14 }, (_, index) => ({
    learning: { status: index < 5 ? 'completed' : index < 8 ? 'in_progress' : 'not_started' },
    cognition: index < 2 ? { mastery_level: 'proficient' } : index < 4 ? { mastery_level: 'developing' } : { status: 'unknown' },
  }))
  assert.deepEqual(summarizeLearningItems(items), {
    total: 14,
    completed: 5,
    mastered: 2,
    needsMastery: 2,
    pending: 1,
    rate: 36,
  })
})
