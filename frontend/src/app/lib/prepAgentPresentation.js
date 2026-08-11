/**
 * Teacher-facing presentation helpers for Prep Agent change summaries.
 *
 * `operation.target` is an audit address.  UI callers intentionally never
 * parse or display it; they use the backend-provided `display` fields instead.
 */
function summaryItems(summary) {
  return Array.isArray(summary?.items) ? summary.items : []
}

function summaryCount(summary) {
  const count = Number(summary?.count)
  return Number.isFinite(count) && count >= 0 ? count : summaryItems(summary).length
}

function itemLabel(item) {
  return typeof item?.label === 'string' && item.label.trim() ? item.label.trim() : '课程草稿修改'
}

/** Return a safe display label for a proposal operation. */
export function operationDisplayLabel(operation) {
  return itemLabel(operation?.display)
}

/** Return the concise status sentence shown in the assistant conversation. */
export function changeSummaryMessage(summary) {
  const state = summary?.state
  const items = summaryItems(summary)
  const count = summaryCount(summary)

  if (state === 'pending_review') {
    const labels = items.slice(0, 3).map(itemLabel)
    return labels.length
      ? `已生成待审核提案：${labels.join('、')}${count > labels.length ? '等' : ''}。`
      : '已生成待审核提案。'
  }
  if (state === 'applied') {
    const resources = new Set(items.map((item) => item?.resource))
    if (resources.size === 1 && resources.has('script')) return `已应用：已优化 ${count} 个讲解脚本。`
    if (resources.size === 1 && resources.has('outline')) return `已应用：已优化 ${count} 个课程节点。`
    return `已应用：已优化 ${count} 项课程草稿内容。`
  }
  if (state === 'rejected') return '提案已拒绝，课程草稿未改动。'
  if (state === 'no_change') return '未生成可安全应用的修改，课程草稿未改动。'
  return ''
}
