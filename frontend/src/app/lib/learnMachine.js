/**
 * 学习状态机（page-design §12.3）— 纯 JS、无框架依赖，可单测。
 *
 * 状态：LEARN / UNDERSTAND / PRACTICE / VISUALIZE / NOTE / CITATION / VERIFY
 * 规则：
 *  - 每次只能有一个主状态；
 *  - 切片 0.1 只启用 LEARN / UNDERSTAND / CITATION，其余注册但禁用
 *    （禁用状态 enter 返回 { ok:false, reason:'disabled' }，绝不偷渡）；
 *  - 从 LEARN 进入分支必须携带分支上下文（§12.11），否则拒绝迁移；
 *  - 分支间跳转保留最初的分支上下文（返回点始终是最初离开课程的位置）；
 *  - exit() 回到 LEARN 并交出保存的返回上下文，由调用方恢复课程位置。
 */

export const LEARN_STATES = Object.freeze({
  LEARN: 'LEARN',
  UNDERSTAND: 'UNDERSTAND',
  PRACTICE: 'PRACTICE',
  VISUALIZE: 'VISUALIZE',
  NOTE: 'NOTE',
  CITATION: 'CITATION',
  VERIFY: 'VERIFY',
})

const ALL_STATES = new Set(Object.values(LEARN_STATES))

/** 切片 0.1 启用的状态（其余状态后续切片逐个解锁） */
export const SLICE_ENABLED_STATES = Object.freeze([
  LEARN_STATES.LEARN,
  LEARN_STATES.UNDERSTAND,
  LEARN_STATES.CITATION,
])

/** 底部工具坞固定顺序（§6.10）：提问｜试一试｜看可视化｜做笔记｜原文引用 */
export const DOCK_ACTIONS = Object.freeze([
  { id: 'ask', label: '提问', target: LEARN_STATES.UNDERSTAND },
  { id: 'practice', label: '试一试', target: LEARN_STATES.PRACTICE },
  { id: 'visualize', label: '看可视化', target: LEARN_STATES.VISUALIZE },
  { id: 'note', label: '做笔记', target: LEARN_STATES.NOTE },
  { id: 'citation', label: '原文引用', target: LEARN_STATES.CITATION },
])

function normalizeBranchContext(raw) {
  if (!raw || typeof raw !== 'object') return null
  const ctx = {
    sourceCourseId: raw.sourceCourseId ?? null,
    sourceNodeId: raw.sourceNodeId ?? null,
    sourceNodeIndex: Number.isFinite(raw.sourceNodeIndex) ? raw.sourceNodeIndex : null,
    sourceNodeTitle: String(raw.sourceNodeTitle ?? ''),
    sourceSectionId: raw.sourceSectionId ?? null,
    learningGoal: String(raw.learningGoal ?? ''),
    completionCondition: String(raw.completionCondition ?? ''),
    sourcePage: Number.isFinite(raw.sourcePage) ? raw.sourcePage : null,
    sourceTime: Number.isFinite(raw.sourceTime) ? raw.sourceTime : null,
    triggerAction: String(raw.triggerAction ?? ''),
    returnTarget: raw.returnTarget && typeof raw.returnTarget === 'object'
      ? {
          nodeIndex: Number.isFinite(raw.returnTarget.nodeIndex) ? raw.returnTarget.nodeIndex : null,
          page: Number.isFinite(raw.returnTarget.page) ? raw.returnTarget.page : null,
          time: Number.isFinite(raw.returnTarget.time) ? raw.returnTarget.time : null,
        }
      : null,
  }
  // §12.11：进入分支必须能定位返回位置，缺失关键字段的上下文不合法
  if (ctx.sourceCourseId == null || ctx.sourceNodeIndex == null || !ctx.returnTarget) {
    return null
  }
  return ctx
}

export function createLearnMachine(options = {}) {
  const enabled = new Set(options.enabledStates ?? SLICE_ENABLED_STATES)
  const initial = options.initialState && enabled.has(options.initialState)
    ? options.initialState
    : LEARN_STATES.LEARN

  let state = initial
  let branchContext = null

  function isEnabled(target) {
    return ALL_STATES.has(target) && enabled.has(target)
  }

  function canEnter(target) {
    return isEnabled(target) && target !== state
  }

  function enter(target, context) {
    if (!ALL_STATES.has(target)) {
      return { ok: false, reason: 'unknown-state', state }
    }
    if (!enabled.has(target)) {
      return { ok: false, reason: 'disabled', state }
    }
    if (target === state) {
      return { ok: false, reason: 'noop', state }
    }
    if (target === LEARN_STATES.LEARN) {
      return exit()
    }
    if (state === LEARN_STATES.LEARN) {
      const ctx = normalizeBranchContext(context)
      if (!ctx) {
        return { ok: false, reason: 'missing-context', state }
      }
      branchContext = ctx
    }
    // 分支 → 分支：保留最初分支上下文（§12.11 返回点不变）
    state = target
    return { ok: true, state, branchContext }
  }

  function exit() {
    const restored = branchContext
    state = LEARN_STATES.LEARN
    branchContext = null
    return { ok: true, state, restored }
  }

  return {
    get state() { return state },
    get branchContext() { return branchContext },
    isEnabled,
    canEnter,
    enter,
    exit,
  }
}
