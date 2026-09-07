/**
 * 复现作业（Repro Run）只读投影辅助 —— 会话内 Console 与实验工作台共用同一真相源。
 *
 * 2026-09-07 从 NexusPage.vue 抽出。动机：v6 引入「实验工作台」作为独立视图后，
 * 同一个 run 会在两个视图里渲染（对话里降级为引用条、工作台里完整展开），
 * 阶段推导 / 耗时 / 判定标签必须在两处完全一致，不能各写一份。
 *
 * 约束与既有实现一致：
 * - fail-closed：未知状态一律如实显示「未知」，不回退到成功态；
 * - 只做投影，不做推测：阶段状态来自 Worker 真实 stage_events；
 * - 纯函数、无副作用、无 import 依赖（可独立单测）。
 */

// NX-E3/G2：作业状态文案。unknown 保留字面量，避免前端伪造成已完成。
export const REPRO_STATUS_LABELS = {
  queued: '排队中',
  running: '执行中',
  succeeded: '已完成',
  failed: '失败',
  rejected: '已拒绝',
  cancelling: '取消中',
  cancelled: '已取消',
  unknown: '状态未知',
}

export const REPRO_TERMINAL_STATUSES = ['succeeded', 'failed', 'rejected', 'cancelled']
export const REPRO_NONTERMINAL_STATUSES = ['queued', 'running', 'cancelling']

// Console 阶段条：Worker 真实 stage_events 投影到固定六段轨道。
export const REPRO_RAIL = [
  { stage: 'preparing', label: 'Preparing' },
  { stage: 'building', label: 'Building' },
  { stage: 'running', label: 'Running' },
  { stage: 'metric', label: 'Metric' },
  { stage: 'verifying', label: 'Verifying' },
  { stage: 'completed', label: 'Completed' },
]

export function reproStatusLabel(run) {
  return REPRO_STATUS_LABELS[run?.status] || run?.status || '未知'
}

export function reproCancellable(run) {
  return REPRO_NONTERMINAL_STATUSES.includes(run?.status)
}

export function reproIsTerminal(run) {
  return REPRO_TERMINAL_STATUSES.includes(run?.status)
}

/**
 * 阶段条轨道。同一 stage 取 seq 最大的事件；running 落地终态 Ui 时该段不得显示成功。
 */
export function reproStageRail(run) {
  const events = Array.isArray(run?.stageEvents) ? run.stageEvents : []
  const latest = {}
  for (const event of events) {
    const prev = latest[event.stage]
    if (!prev || (event.seq ?? 0) >= (prev.seq ?? 0)) latest[event.stage] = event
  }
  const badTerminal = ['failed', 'rejected', 'cancelled'].includes(run?.status)
  return REPRO_RAIL.map(({ stage, label }) => {
    const event = latest[stage]
    let state = 'pending'
    if (event) {
      if (event.status === 'done') state = 'done'
      else if (event.status === 'skipped' || event.status === 'not_applicable') state = 'skipped'
      else if (event.status === 'failed') state = 'failed'
      else if (event.status === 'started') state = badTerminal ? 'failed' : 'current'
    }
    return { stage, label, state, note: event?.note || '' }
  })
}

export function reproStageNotes(run) {
  const events = Array.isArray(run?.stageEvents) ? run.stageEvents : []
  return events
    .filter((e) => e.status === 'skipped' || e.status === 'not_applicable')
    .map((e) => `${e.stage}：${e.note || '本批不适用'}`)
    .join('；')
}

export function reproIsCurrentStep(run, index) {
  return run?.status === 'running' && run.currentStep === index
}

export function reproStepState(run, step) {
  if (reproIsCurrentStep(run, step?.index)) return 'run'
  if (step?.timed_out) return 'err'
  if (step?.exit_code === 0) return 'ok'
  if (step?.exit_code != null) return 'err'
  return 'pend'
}

export function reproStepLabel(run, step) {
  const state = reproStepState(run, step)
  return { ok: '完成', err: '失败', run: '运行中', pend: '待执行' }[state]
}

/**
 * 终态/未知态不得取 running 分支的增量日志（当时尚无"稳态输出"）。
 */
export function reproLogText(run) {
  if (['running', 'cancelling', 'queued'].includes(run?.status) && run.liveLog) {
    return run.liveLog
  }
  const withLog = (run?.stages || []).filter((s) => s.log_tail)
  return withLog.length ? withLog[withLog.length - 1].log_tail : ''
}

export function reproLogSource(run) {
  if (['running', 'cancelling'].includes(run?.status)) {
    return `运行中 · 第 ${run?.currentStep ?? '—'} 步（增量）`
  }
  return '终态日志尾'
}

/**
 * 会话内 Console 只需要末 20 行；工作台的大日志区用全量 reproLogText。
 */
export function reproLogLines(run, max = 20) {
  const text = reproLogText(run)
  return text ? text.replace(/\n+$/, '').split('\n').slice(-max).join('\n') : ''
}

export function reproElapsed(run) {
  if (!run?.startedAt) return ''
  const end = run.finishedAt || (run.status === 'running' ? Date.now() / 1000 : null)
  if (!end) return ''
  const total = Math.max(0, Math.round(end - run.startedAt))
  return total >= 60 ? `${Math.floor(total / 60)}m${String(total % 60).padStart(2, '0')}s` : `${total}s`
}

/**
 * 退出码显示：运行中为「—」而非 0；终态如实显示（含 -9 / 非零）。
 */
export function reproExitLabel(step) {
  if (step?.exit_code == null) return '—'
  return String(step.exit_code)
}

/**
 * 实验显示名（后端优先，2026-09-08 接线）。
 *
 * 后端 `nexus_runs` 自 NX-LB1 起提供命名：`display_title`（用户命名优先，
 * 否则「preset 展示名 + 会话内稳定序号」，跨设备一致）与 `title`。
 * 有后端投影时直接采用；本地/demo 运行（无后端行）回退到
 * 「preset + 同 preset 内序号」本地命名——回退分支如实表达已知事实，
 * 不是编造名。UI 只认本函数返回值，命名规则变化不碰调用方。
 */
export function experimentName(run, seq = 1) {
  const serverName = (run?.display_title || run?.title || '').trim()
  if (serverName) return serverName
  const base = run?.preset_id || '未命名实验'
  return `${base} 复现 · #${seq}`
}
