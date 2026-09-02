/**
 * 学习页可见状态映射。
 *
 * 学习曝光和认知掌握是两条独立语义：先展示学生是否学过，完成后再展示
 * 认知结论。这样不会把“已看过”误当成“已掌握”，也不会把认知服务失败
 * 隐藏成普通的学习状态。
 */
export function getLearningDisplayState(learning = {}) {
  switch (learning.status) {
    case 'not_started':
      return { key: 'not-started', label: '未学习', tone: 'amber', iconName: 'not-started' }
    case 'in_progress':
      return { key: 'in-progress', label: '学习中', tone: 'ink', iconName: 'in-progress' }
    case 'completed':
      return { key: 'completed', label: '已完成', tone: 'green', iconName: 'completed' }
    default:
      return { key: 'unknown', label: '学习状态未知', tone: 'neutral', iconName: 'unknown' }
  }
}

// 页面契约中的可见词典（供无运行时 Vue 的契约检查和无障碍文案审计使用）。
export const LEARNING_STATUS_LABELS = Object.freeze(['未学习', '学习中', '已完成'])
export const COGNITION_STATUS_LABELS = Object.freeze(['已掌握', '待掌握', '需要更多证据', '暂不可分析', '认知暂不可用'])

export function getCognitionDisplayState(cognition = {}) {
  if (cognition.status === 'degraded') {
    return { key: 'cognition-degraded', label: '认知暂不可用', tone: 'neutral', iconName: 'degraded' }
  }
  if (cognition.status === 'not_available') {
    return { key: 'not-available', label: '暂不可分析', tone: 'neutral', iconName: 'not-available' }
  }
  if (cognition.mastery_level === 'advanced' || cognition.mastery_level === 'proficient') {
    return { key: 'mastered', label: '已掌握', tone: 'green', iconName: 'mastered' }
  }
  if (cognition.mastery_level === 'developing' || cognition.mastery_level === 'beginner') {
    return { key: 'needs-mastery', label: '待掌握', tone: 'amber', iconName: 'needs-mastery' }
  }
  return { key: 'more-evidence', label: '需要更多证据', tone: 'neutral', iconName: 'more-evidence' }
}

export function getNodeDisplayState(item = {}) {
  const learning = item.learning || {}
  const cognition = item.cognition || {}
  const learningState = getLearningDisplayState(learning)
  if (learning.status !== 'completed') return learningState
  // 有正式认知结论（已掌握/待掌握）时优先展示认知结论；
  // 其余情况（暂不可分析/认知暂不可用/无证据/待验证）主状态保持“已完成”，
  // 把认知状态挂到 cognitionHint 上，避免灰色认知状态把“已学完”的事实吞掉。
  const cognitionState = getCognitionDisplayState(cognition)
  if (cognitionState.key === 'mastered' || cognitionState.key === 'needs-mastery') {
    return cognitionState
  }
  return { ...learningState, cognitionHint: cognitionState }
}

export function summarizeLearningItems(items = []) {
  const total = items.length
  const completed = items.filter(item => item?.learning?.status === 'completed').length
  const mastered = items.filter(item => ['advanced', 'proficient'].includes(item?.cognition?.mastery_level)).length
  const needsMastery = items.filter(item => ['developing', 'beginner'].includes(item?.cognition?.mastery_level)).length
  const pending = items.filter(item => item?.learning?.status === 'completed' && !['advanced', 'proficient', 'developing', 'beginner'].includes(item?.cognition?.mastery_level)).length
  return { total, completed, mastered, needsMastery, pending, rate: total ? Math.round((completed / total) * 100) : 0 }
}
