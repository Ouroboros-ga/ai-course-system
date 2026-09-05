import request, { generateSignature } from '@/utils/request.js'

/**
 * Nexus AI 客户端。对应后端反代 backend/app/api/v1/endpoints/nexus_proxy.py，
 * 后端再透传到独立进程 Nexus Runtime（nexus/，deepagents + langgraph）。
 *
 * 与本仓库其他 API 模块的两点差异，都是 Nexus 的真实形态决定的：
 * 1. 响应无 {code,message,data} 信封（反代是纯透传），故需 allowFlatResponse。
 * 2. 流式对话必须用 fetch 而非 axios——axios 拿不到 ReadableStream。
 */

const NEXUS_BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1'

/** 运行时健康状态：llm/searxng/repro_worker 是否已配置。 */
export function getNexusHealth() {
  return request.get('/nexus/health', { allowFlatResponse: true, skipErrorToast: true })
}

/**
 * 会话列表（P1-C2）：当前登录用户的持久化会话（session_id + 标题 + 活跃时间）。
 * Runtime 未启用持久化时返回 { persistence: 'memory', sessions: [] }。
 */
export function listNexusSessions() {
  return request.get('/nexus/sessions', { allowFlatResponse: true, skipErrorToast: true })
}

/**
 * 单会话历史消息（P1-C2/C3）：[{ role: 'user' | 'assistant', content }]。
 */
export function getNexusSessionMessages(sessionId) {
  return request.get(`/nexus/sessions/${encodeURIComponent(sessionId)}/messages`, {
    allowFlatResponse: true,
    skipErrorToast: true,
  })
}

/**
 * 复现作业状态（M4-B1）：发起人鉴权，返回裁剪后的 Worker 记录
 * （status/steps_result 短日志/artifacts）。
 */
export function getNexusReproJob(jobId) {
  return request.get(`/nexus/repro/jobs/${encodeURIComponent(jobId)}`, {
    allowFlatResponse: true,
    skipErrorToast: true,
  })
}

/**
 * 复现报告生成（M4-B3）：确定性判定（PASS/FAIL 不经 LLM）+ 报告 Artifact 入库。
 */
export function requestReproReport(jobId) {
  return request.post(`/nexus/repro/jobs/${encodeURIComponent(jobId)}/report`, {}, {
    allowFlatResponse: true,
    skipErrorToast: true,
  })
}

/**
 * 审批状态查询（NX-G2）：本人查询，跨用户后端 404。
 */
export function getNexusApproval(approvalId) {
  return request.get(`/nexus/approvals/${encodeURIComponent(approvalId)}`, {
    allowFlatResponse: true,
    skipErrorToast: true,
  })
}

/**
 * 批准/拒绝（NX-G2 Hard Workflow）：决定动作本人发起，服务端原子转换。
 * UI 只负责展示提案与提交决定，不代替服务端做任何放行判断。
 */
export function decideNexusApproval(approvalId, decision = 'approved') {
  return request.post(`/nexus/approvals/${encodeURIComponent(approvalId)}/decide`, { decision }, {
    allowFlatResponse: true,
    skipErrorToast: true,
  })
}

/**
 * 手工执行（NX-G2）：凭已批准票据提交 Worker，与聊天工具共用服务端同一
 * 核销核心；同一票据重试返回原 job，不重复启动实验。
 */
export function executeApprovedRepro(approvalId, sessionId = 'default') {
  return request.post('/nexus/repro/execute', { approval_id: approvalId, session_id: sessionId }, {
    allowFlatResponse: true,
    skipErrorToast: true,
  })
}

/**
 * 上传附件（NX-A1，multipart）：校验→配额→解析→ready/partial/failed 同步返回。
 * 八格式：pdf/docx/jpg/jpeg/png/xlsx/pptx/ppt/doc。DOC/PPT 无 LibreOffice
 * 时如实 failed，不抛错；调用方凭 status 决定展示/删除/换格式。
 */
export function uploadNexusAttachment(file, sessionId = '', onProgress = null) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('session_id', sessionId || '')
  return request.post('/nexus/attachments', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300000,
    onUploadProgress: onProgress || null,
    allowFlatResponse: true,
    skipErrorToast: true,
  })
}

/**
 * 我的附件列表（NX-A1）：更新时间倒序；可按会话过滤（未绑定＋本会话）。
 */
export function listNexusAttachments(sessionId = '', limit = 50) {
  return request.get('/nexus/attachments', {
    params: { session_id: sessionId || '', limit },
    allowFlatResponse: true,
    skipErrorToast: true,
  })
}

/**
 * 附件元数据（NX-A1）；includeBlocks=1 附带预算内解析 blocks（文本预览）。
 */
export function getNexusAttachment(attachmentId, includeBlocks = false) {
  return request.get(`/nexus/attachments/${encodeURIComponent(attachmentId)}`, {
    params: includeBlocks ? { include_blocks: true } : {},
    allowFlatResponse: true,
    skipErrorToast: true,
  })
}

/**
 * 删除附件（NX-A1）：立即撤销读取；幂等。
 */
export function deleteNexusAttachment(attachmentId) {
  return request.delete(`/nexus/attachments/${encodeURIComponent(attachmentId)}`, {
    allowFlatResponse: true,
    skipErrorToast: true,
  })
}

/**
 * 会话 runs 恢复查询（NX-E1）：含 Worker 实时态合并；只读，不触发任何执行。
 */
export function listNexusRuns(sessionId) {
  return request.get('/nexus/runs', {
    params: { session_id: sessionId },
    allowFlatResponse: true,
    skipErrorToast: true,
  })
}

/**
 * 产物列表（M3）：当前用户的 Nexus Artifact（owner 过滤在 Backend）。
 */
export function listNexusArtifacts(limit = 50) {
  return request.get('/nexus/artifacts', {
    params: { limit },
    allowFlatResponse: true,
    skipErrorToast: true,
  })
}

/**
 * 产物下载（M3）：JWT 鉴权 + owner 校验，返回 Blob 由调用方触发保存。
 */
export async function downloadNexusArtifact(artifactId) {
  const token = localStorage.getItem('token')
  const response = await fetch(
    `${NEXUS_BASE}/nexus/artifacts/${encodeURIComponent(artifactId)}/download`,
    {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    }
  )
  if (!response.ok) {
    let detail = ''
    try {
      const payload = await response.json()
      detail = payload?.message || payload?.detail || ''
    } catch {
      detail = await response.text().catch(() => '')
    }
    const error = new Error(detail || `产物下载失败（HTTP ${response.status}）`)
    error.status = response.status
    throw error
  }
  return response.blob()
}

/**
 * 非流式对话：等 Agent 循环跑完一次性返回。
 *
 * @deprecated 已知运行时缺陷（见开发文档「待修缺陷 D1」）：
 * nexus/ 的 /chat 把 stream_mode 当字符串传入，而 langgraph 1.2 只在传 list 时
 * 才 yield 元组，真跑必抛 ValueError。在运行时修复前，前端一律走流式
 * streamNexusMessage()，不要调用本函数。
 */
export function sendNexusMessage(payload) {
  return request.post('/nexus/chat', payload, { allowFlatResponse: true })
}

/**
 * 解析 SSE 帧。后端事件类型：token / tool_call / tool_result / done。
 * 只在遇到完整的 `\n\n` 分隔符时才交付，半个帧留在 buffer 里等下一个 chunk。
 */
function parseSseFrames(buffer, onEvent) {
  let rest = buffer
  let separator = rest.indexOf('\n\n')
  while (separator !== -1) {
    const frame = rest.slice(0, separator)
    rest = rest.slice(separator + 2)
    separator = rest.indexOf('\n\n')

    let eventName = 'message'
    const dataLines = []
    for (const line of frame.split('\n')) {
      if (line.startsWith('event:')) eventName = line.slice(6).trim()
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
    }
    if (!dataLines.length) continue

    const raw = dataLines.join('\n')
    let data
    try {
      data = JSON.parse(raw)
    } catch {
      // 上游给了非 JSON 的 data：如实上抛原文，不猜测内容。
      data = { raw }
    }
    onEvent({ event: eventName, data })
  }
  return rest
}

/**
 * 流式对话。逐事件回调 onEvent({ event, data })，返回 Promise，流结束或出错时 settle。
 *
 * @param {object} options
 * @param {string} options.message      用户输入
 * @param {string} [options.sessionId]  会话 ID（P0 阶段服务重启即清）
 * @param {string} [options.mode]       模式标识，接线预留（当前运行时忽略未知字段）
 * @param {number} [options.courseId]   绑定的课程 ID，接线预留（同上）
 * @param {string} [options.model]      模型 id（服务端 allowlist 内；缺省用默认模型）
 * @param {string[]} [options.attachmentIds] 本次对话引用的附件 id（≤5，服务端验主+绑定）
 * @param {(evt: {event: string, data: object}) => void} options.onEvent
 * @param {AbortSignal} [options.signal] 用于取消（组件卸载/用户中止）
 */
export async function streamNexusMessage({
  message,
  sessionId = 'default',
  mode = null,
  courseId = null,
  model = null,
  attachmentIds = [],
  onEvent,
  signal,
}) {
  const body = { message, session_id: sessionId }
  // 接线预留：运行时一旦在 /chat/stream 接收这两个字段，前端无需任何改动。
  if (mode) body.mode = mode
  if (courseId != null) body.context = { course_id: courseId }
  // 模型网关 P0：服务端 allowlist 校验，清单外直接 400（见 NexusPage 模型下拉）。
  if (model) body.model = model
  // NX-A1：附件引用（服务端验主＋绑定会话后才透传给 Runtime）。
  if (Array.isArray(attachmentIds) && attachmentIds.length) {
    body.attachment_ids = attachmentIds.slice(0, 5)
  }
  // 复用 axios 拦截器同一套签名算法：签名参数进 body，与 POST 的签名口径一致。
  const { time, enc } = generateSignature(body)
  const token = localStorage.getItem('token')

  const response = await fetch(`${NEXUS_BASE}/nexus/chat/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ ...body, time, enc }),
    signal,
  })

  if (!response.ok) {
    // 反代与 Runtime 都是 fail-closed 的：把真实错误码交给调用方展示，
    // 不在这里吞掉、也不伪造一个空回答。
    let detail = ''
    let errorCode = ''
    try {
      const payload = await response.json()
      errorCode = payload?.data?.error_code || ''
      detail = payload?.message || payload?.detail || ''
    } catch {
      detail = await response.text().catch(() => '')
    }
    const error = new Error(detail || `Nexus 请求失败（HTTP ${response.status}）`)
    error.status = response.status
    error.errorCode = errorCode
    throw error
  }

  if (!response.body) {
    throw new Error('当前浏览器不支持流式响应')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      buffer = parseSseFrames(buffer, onEvent)
    }
    // 收尾：上游最后一帧可能没有尾随空行。
    buffer += decoder.decode()
    parseSseFrames(`${buffer}\n\n`, onEvent)
  } finally {
    reader.releaseLock()
  }
}
