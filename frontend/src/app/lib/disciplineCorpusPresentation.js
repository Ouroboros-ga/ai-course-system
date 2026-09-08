/**
 * CR5 学科语料覆盖率呈现（纯函数，无网络、无 DOM）。
 *
 * 约束：
 * - 只描述“文档 / 文本块 / 已向量化 / 语料范围”，旧 112/106 只称精编概念/关系；
 * - 部分覆盖与向量失败如实提示；绝不输出“全部完成”（partial_success 语义）。
 */
/**
 * 语料出处链接：仅放行 http/https，其余（含 javascript:/data:）一律返回空串。
 * 空出处不渲染链接（§5.3"可打开的出处"，但不给未知协议开洞）。
 */
export function safeSourceUrl(url) {
  const text = String(url || '').trim()
  return /^https?:\/\//i.test(text) ? text : ''
}

export function formatCorpusCoverage(stats) {
  const data = stats && typeof stats === 'object' ? stats : {}
  if (data.available === false
    || (data.release_id == null && data.eligible_chunks == null)) {
    return '语料检索暂不可用'
  }
  const eligible = Number(data.eligible_chunks ?? 0)
  const embedded = Number(data.embedded_chunks ?? 0)
  const documents = Number(data.documents ?? 0)
  if (!eligible) {
    return '语料范围为空'
  }
  const parts = []
  if (documents > 0) parts.push(`文档 ${documents}`)
  parts.push(`文本块 ${eligible}`)
  parts.push(`已向量化 ${embedded} / ${eligible}`)
  if (embedded < eligible) {
    parts.push('部分范围')
  }
  if (Array.isArray(data.degraded_reasons) && data.degraded_reasons.length) {
    parts.push(`降级：${data.degraded_reasons.join('、')}`)
  }
  return parts.join(' · ')
}
