/**
 * Maps provider-specific task payloads to UI-only state.  Derived states are
 * intentionally not persisted: current backends only accept canonical status.
 */
const TERMINAL = new Set(['succeeded', 'failed', 'cancelled', 'timeout', 'partial_success'])

const STATUS_ALIASES = {
  completed: 'succeeded', done: 'succeeded', success: 'succeeded',
  processing: 'running', generating: 'running', tts_synthesizing: 'running',
  tts_completed: 'running', dh_generating: 'running', queued: 'pending',
  not_started: 'pending', no_script: 'pending', partial: 'partial_success',
  error: 'failed',
}

export function normalizeLongTask(payload = {}) {
  const incomingStatus = String(payload.status || payload.state || 'pending').toLowerCase()
  const rawStatus = STATUS_ALIASES[incomingStatus] || incomingStatus
  const status = ['pending', 'running', 'succeeded', 'failed', 'cancelled', 'timeout', 'partial_success'].includes(rawStatus)
    ? rawStatus
    : 'pending'
  const total = Number(payload.total ?? payload.total_count ?? 0)
  const completed = Number(payload.completed ?? payload.completed_count ?? 0)
  const progress = Number.isFinite(Number(payload.progress))
    ? Math.max(0, Math.min(100, Number(payload.progress)))
    : total > 0 ? Math.round((completed / total) * 100) : null

  return {
    id: payload.sid || payload.task_id || payload.id || '',
    title: payload.title || payload.task_name || '后台任务',
    status,
    progress,
    completed,
    total,
    message: payload.message || payload.error || payload.error_message || '',
    canRetry: ['failed', 'timeout', 'partial_success'].includes(status),
    isTerminal: TERMINAL.has(status),
    requiresReview: status === 'succeeded' && payload.requires_confirmation === true,
    source: payload,
  }
}

export const taskStatusMeta = {
  pending: { label: '等待执行', tone: 'neutral' },
  running: { label: '处理中', tone: 'info' },
  succeeded: { label: '已生成', tone: 'success' },
  failed: { label: '执行失败', tone: 'danger' },
  cancelled: { label: '已取消', tone: 'neutral' },
  timeout: { label: '超时', tone: 'warning' },
  partial_success: { label: '部分完成', tone: 'warning' },
}
