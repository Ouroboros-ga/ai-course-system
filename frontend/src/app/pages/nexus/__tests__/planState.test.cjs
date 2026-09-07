/**
 * NX-H1 计划状态机测试（node 直接执行真实 planState.js 模块，非源码正则）。
 * 运行：node src/app/pages/nexus/__tests__/planState.test.cjs
 */
const assert = require('node:assert')
const { pathToFileURL } = require('node:url')
const { join } = require('node:path')

async function main() {
  const { createPlanState, applyPlanEvent, applyRestoredPlan } = await import(
    pathToFileURL(join(__dirname, '..', 'planState.js')).href
  )

  const snap = (revision, statuses = ['pending', 'in_progress']) => ({
    session_id: 's1',
    plan_id: 'plan-abc',
    revision,
    items: statuses.map((status, i) => ({ id: `t${i + 1}`, content: `步骤${i + 1}`, status })),
    source: 'agent_plan',
  })

  // ── 流事件：严格更大 revision 才接受 ──
  const state = createPlanState()
  assert.strictEqual(state.plan, null)
  assert.strictEqual(applyPlanEvent(state, snap(2)), true)
  assert.strictEqual(state.plan.revision, 2)
  assert.strictEqual(state.plan.items[1].status, 'in_progress')

  // revision=2 已显示后收到 revision=1（乱序/旧事件）：保持 revision=2。
  assert.strictEqual(applyPlanEvent(state, snap(1, ['completed'])), false)
  assert.strictEqual(state.plan.revision, 2)
  assert.strictEqual(state.plan.items[0].status, 'pending')

  // 重复事件（同 revision）：忽略。
  assert.strictEqual(applyPlanEvent(state, snap(2)), false)

  // 更大 revision 正常替换。
  assert.strictEqual(applyPlanEvent(state, snap(3, ['completed', 'completed'])), true)
  assert.strictEqual(state.plan.items[0].status, 'completed')

  // 非法快照：不改变状态。
  assert.strictEqual(applyPlanEvent(state, null), false)
  assert.strictEqual(applyPlanEvent(state, { revision: 9 }), false)
  assert.strictEqual(applyPlanEvent(state, { plan_id: 'p', revision: 9, items: 'nope' }), false)
  assert.strictEqual(state.plan.revision, 3)

  // 状态机从不改写条目状态（取消/中断后原 pending 条目保持 pending 的结构保证）。
  const before = JSON.stringify(state.plan.items)
  applyPlanEvent(state, snap(4))
  assert.notStrictEqual(JSON.stringify(state.plan.items), before) // 新快照整体替换
  assert.strictEqual(applyPlanEvent(state, snap(2, ['completed'])), false) // 旧事件绝不回写

  // ── 恢复读取：checkpoint 真值无条件替换 + 基线重置 ──
  const s2 = createPlanState()
  applyPlanEvent(s2, snap(5))
  // Runtime 重启后远端计数器从 1 重新计数：低 revision 也必须被采纳为基线。
  assert.strictEqual(applyRestoredPlan(s2, { plan: snap(1, ['completed']) }), true)
  assert.strictEqual(s2.plan.revision, 1)
  assert.strictEqual(s2.revision, 1)
  // 基线重置后，重启进程的后续流事件（revision 2,3…）可被正常接受。
  assert.strictEqual(applyPlanEvent(s2, snap(2)), true)

  // 服务端无计划（plan=null）：清空本地缓存（本地缓存不是事实唯一来源）。
  const s3 = createPlanState()
  applyPlanEvent(s3, snap(7))
  assert.strictEqual(applyRestoredPlan(s3, { plan: null }), true)
  assert.strictEqual(s3.plan, null)
  assert.strictEqual(s3.revision, 0)

  // 非法载荷：状态不变（读取失败可重试，不破坏现状）。
  const s4 = createPlanState()
  applyPlanEvent(s4, snap(3))
  assert.strictEqual(applyRestoredPlan(s4, null), false)
  assert.strictEqual(applyRestoredPlan(s4, { plan: { revision: 9 } }), false)
  assert.strictEqual(s4.plan.revision, 3)

  console.log('planState tests: all passed')
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
