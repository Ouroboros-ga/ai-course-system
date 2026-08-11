import test from 'node:test'
import assert from 'node:assert/strict'

import { changeSummaryMessage, operationDisplayLabel } from '../prepAgentPresentation.js'

const scriptItem = {
  resource: 'script',
  label: '讲解脚本《汽车的定义与分类》的讲稿内容',
}

test('待审核的单节点提案展示节点标题，不展示内部 target', () => {
  assert.equal(changeSummaryMessage({ state: 'pending_review', count: 1, items: [scriptItem] }), '已生成待审核提案：讲解脚本《汽车的定义与分类》的讲稿内容。')
})

test('已应用的批量讲稿和课程节点分别生成教师可读统计', () => {
  assert.equal(changeSummaryMessage({ state: 'applied', count: 4, items: [scriptItem, scriptItem] }), '已应用：已优化 4 个讲解脚本。')
  assert.equal(changeSummaryMessage({ state: 'applied', count: 2, items: [
    { resource: 'outline', label: '课程节点《发动机基础》的标题' },
  ] }), '已应用：已优化 2 个课程节点。')
})

test('拒绝和无改动状态不暗示写入草稿', () => {
  assert.equal(changeSummaryMessage({ state: 'rejected', count: 1, items: [scriptItem] }), '提案已拒绝，课程草稿未改动。')
  assert.equal(changeSummaryMessage({ state: 'no_change', count: 0, items: [] }), '未生成可安全应用的修改，课程草稿未改动。')
})

test('审核卡只接受后端 display，绝不回退渲染内部 target', () => {
  assert.equal(operationDisplayLabel({ target: 'script:tsn_internal:content' }), '课程草稿修改')
  assert.equal(operationDisplayLabel({ target: 'script:tsn_internal:content', display: scriptItem }), scriptItem.label)
})
