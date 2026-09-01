import test from 'node:test'
import assert from 'node:assert/strict'

import {
  createLearnMachine,
  DOCK_ACTIONS,
  LEARN_STATES,
} from '../learnMachine.js'

const validContext = {
  sourceCourseId: 7,
  sourceNodeId: 42,
  sourceNodeIndex: 3,
  sourceNodeTitle: '二分查找',
  sourcePage: 5,
  sourceTime: 128,
  triggerAction: 'ask',
  returnTarget: { nodeIndex: 3, page: 5, time: 128 },
}

test('初始状态为 LEARN，且切片默认只启用 LEARN/UNDERSTAND/CITATION', () => {
  const machine = createLearnMachine()
  assert.equal(machine.state, LEARN_STATES.LEARN)
  assert.equal(machine.isEnabled(LEARN_STATES.UNDERSTAND), true)
  assert.equal(machine.isEnabled(LEARN_STATES.CITATION), true)
  assert.equal(machine.isEnabled(LEARN_STATES.PRACTICE), false)
  assert.equal(machine.isEnabled(LEARN_STATES.NOTE), false)
  assert.equal(machine.isEnabled(LEARN_STATES.VERIFY), false)
  assert.equal(machine.isEnabled(LEARN_STATES.CODING), false)
})

test('CODING 是可显式启用的独立分支，并保留课程返回锚点', () => {
  const machine = createLearnMachine({
    enabledStates: [LEARN_STATES.LEARN, LEARN_STATES.CODING],
  })

  const entered = machine.enter(LEARN_STATES.CODING, {
    ...validContext,
    triggerAction: 'coding_challenge',
  })
  assert.equal(entered.ok, true)
  assert.equal(machine.state, LEARN_STATES.CODING)
  assert.deepEqual(machine.branchContext.returnTarget, validContext.returnTarget)

  const exited = machine.exit()
  assert.equal(exited.state, LEARN_STATES.LEARN)
  assert.deepEqual(exited.restored.returnTarget, validContext.returnTarget)
})

test('从 LEARN 进入分支必须携带合法分支上下文（§12.11）', () => {
  const machine = createLearnMachine()

  const noCtx = machine.enter(LEARN_STATES.UNDERSTAND)
  assert.equal(noCtx.ok, false)
  assert.equal(noCtx.reason, 'missing-context')
  assert.equal(machine.state, LEARN_STATES.LEARN)

  const incomplete = machine.enter(LEARN_STATES.UNDERSTAND, { sourceCourseId: 7 })
  assert.equal(incomplete.ok, false)
  assert.equal(incomplete.reason, 'missing-context')

  const ok = machine.enter(LEARN_STATES.UNDERSTAND, validContext)
  assert.equal(ok.ok, true)
  assert.equal(machine.state, LEARN_STATES.UNDERSTAND)
  assert.equal(machine.branchContext.sourceNodeIndex, 3)
  assert.deepEqual(machine.branchContext.returnTarget, { nodeIndex: 3, page: 5, time: 128 })
})

test('禁用状态拒绝迁移，绝不偷渡', () => {
  const machine = createLearnMachine()
  const res = machine.enter(LEARN_STATES.PRACTICE, validContext)
  assert.equal(res.ok, false)
  assert.equal(res.reason, 'disabled')
  assert.equal(machine.state, LEARN_STATES.LEARN)
})

test('未知状态与原地迁移被拒绝', () => {
  const machine = createLearnMachine()
  assert.equal(machine.enter('NOT_A_STATE', validContext).reason, 'unknown-state')
  assert.equal(machine.enter(LEARN_STATES.LEARN).reason !== undefined, true)
})

test('分支间跳转保留最初返回上下文', () => {
  const machine = createLearnMachine()
  machine.enter(LEARN_STATES.UNDERSTAND, validContext)

  const again = machine.enter(LEARN_STATES.CITATION, {
    sourceCourseId: 999,
    sourceNodeIndex: 99,
    returnTarget: { nodeIndex: 99, page: 1, time: 0 },
  })
  assert.equal(again.ok, true)
  assert.equal(machine.state, LEARN_STATES.CITATION)
  // 返回点仍然是最初离开课程的位置，不被分支间跳转覆盖
  assert.equal(machine.branchContext.sourceCourseId, 7)
  assert.deepEqual(machine.branchContext.returnTarget, { nodeIndex: 3, page: 5, time: 128 })
})

test('exit 回到 LEARN 并交出返回上下文，重复 exit 安全', () => {
  const machine = createLearnMachine()
  machine.enter(LEARN_STATES.UNDERSTAND, validContext)

  const out = machine.exit()
  assert.equal(out.ok, true)
  assert.equal(out.state, LEARN_STATES.LEARN)
  assert.equal(out.restored.sourceNodeIndex, 3)
  assert.equal(machine.branchContext, null)

  const again = machine.exit()
  assert.equal(again.ok, true)
  assert.equal(again.restored, null)
})

test('enter(LEARN) 等价于 exit', () => {
  const machine = createLearnMachine()
  machine.enter(LEARN_STATES.CITATION, validContext)
  const back = machine.enter(LEARN_STATES.LEARN)
  assert.equal(back.ok, true)
  assert.equal(machine.state, LEARN_STATES.LEARN)
  assert.equal(back.restored.sourceNodeIndex, 3)
})

test('工具坞动作顺序固定且目标状态已注册（§6.10）', () => {
  assert.deepEqual(
    DOCK_ACTIONS.map((a) => a.label),
    ['提问', '试一试', '看可视化', '做笔记', '原文引用']
  )
  for (const action of DOCK_ACTIONS) {
    assert.ok(Object.values(LEARN_STATES).includes(action.target))
  }
})

test('学习页启用的全部工具坞分支都能从课程位置锚点进入', () => {
  const machine = createLearnMachine({
    enabledStates: Object.values(LEARN_STATES),
  })

  for (const action of DOCK_ACTIONS) {
    const result = machine.enter(action.target, validContext)
    assert.equal(result.ok, true, `${action.id} 应能进入分支`)
    machine.exit()
  }
})
