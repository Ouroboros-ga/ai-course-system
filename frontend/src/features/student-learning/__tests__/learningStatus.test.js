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
  assert.equal(getNodeDisplayState({ learning: { status: 'completed' }, cognition: { status: 'unknown' } }).label, '已完成，待验证')
})

test('完成后认知状态显示掌握、待掌握、暂不可分析和降级', () => {
  assert.equal(getNodeDisplayState({ learning: { status: 'completed' }, cognition: { mastery_level: 'proficient' } }).label, '已掌握')
  assert.equal(getNodeDisplayState({ learning: { status: 'completed' }, cognition: { mastery_level: 'beginner' } }).label, '待掌握')
  assert.equal(getNodeDisplayState({ learning: { status: 'completed' }, cognition: { status: 'not_available' } }).label, '暂不可分析')
  assert.equal(getNodeDisplayState({ learning: { status: 'completed' }, cognition: { status: 'degraded' } }).label, '认知暂不可用')
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
