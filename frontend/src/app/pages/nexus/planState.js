/**
 * NX-H1 计划快照状态机（纯逻辑，无依赖，可独立测试）。
 *
 * 协议（Runtime nexus/planning.py 投影）：
 *   { session_id, plan_id, revision, items: [{id, content, status}], source: "agent_plan" }
 * 条目 status 保持 middleware 原生枚举：pending / in_progress / completed。
 *
 * 两条进入路径语义不同（任务书 T2）：
 * - 流事件 applyPlanEvent：只接受**严格更大**的 revision——乱序/重复/旧事件
 *   一律忽略（revision=3 已显示后收到 revision=2，保持 revision=3）。
 * - 恢复读取 applyRestoredPlan：刷新后的 checkpoint 真值，**无条件替换**，
 *   并把本地 revision 基线重置为远端值——Runtime 进程重启后计数器从 1
 *   重新计数，若沿用本地高基线，重启后的真实流事件会被永久忽略。
 *   快照读取失败不改变状态（可重试，不永久置 restored）。
 */

export function createPlanState() {
  return { plan: null, revision: 0 }
}

function validSnapshot(snapshot) {
  return (
    !!snapshot &&
    typeof snapshot === 'object' &&
    typeof snapshot.plan_id === 'string' &&
    snapshot.plan_id.length > 0 &&
    Array.isArray(snapshot.items)
  )
}

/**
 * 消费流式 plan 事件。返回 true 表示状态已变化（调用方按需持久化）。
 */
export function applyPlanEvent(state, snapshot) {
  if (!validSnapshot(snapshot)) return false
  const revision = Number(snapshot.revision) || 0
  if (revision <= state.revision) return false
  state.plan = snapshot
  state.revision = revision
  return true
}

/**
 * 消费恢复读取结果（GET /nexus/plan/{session_id} 的 { plan }）。
 * 载荷缺失（null/非对象，如读取失败）→ 不改变状态（可重试）；
 * 服务端显式 plan: null → 清空本地计划（本地缓存不是事实唯一来源）。
 */
export function applyRestoredPlan(state, payload) {
  if (!payload || typeof payload !== 'object') return false
  const snapshot = payload.plan
  if (snapshot !== null && !validSnapshot(snapshot)) return false
  state.plan = snapshot
  state.revision = snapshot ? Number(snapshot.revision) || 0 : 0
  return true
}
