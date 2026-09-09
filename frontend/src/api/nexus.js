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
 * 会话最近计划快照（NX-H1）：checkpoint 真值投影，只读不触发执行。
 * 无计划时 plan 为 null；恢复读取以整体替换语义消费（见 planState.js）。
 */
export function getNexusPlan(sessionId) {
  return request.get(`/nexus/plan/${encodeURIComponent(sessionId)}`, {
    allowFlatResponse: true,
    skipErrorToast: true,
  })
}

/**
 * 复现作业状态（M4-B1 / NX-E2）：发起人鉴权，返回裁剪后的 Worker 记录
 * （status/stage_events/steps_result/live_log_tail/artifacts）。
 * flatEnvelope：记录自身带 code(业务错误码，运行中为 null) 字段，
 * allowFlatResponse 的形状探测会把整个记录误判为错误响应（轮询数据被吞）。
 */
export function getNexusReproJob(jobId) {
  return request.get(`/nexus/repro/jobs/${encodeURIComponent(jobId)}`, {
    flatEnvelope: true,
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
 * 审批待办恢复（NX-LB2）：进入会话即拉本人的 pending 待办，
 * 供输入框上方浮窗展示。不能静默替用户选中另一个运行的审批——
 * 浮窗必须写明目标运行，因此调用方要按 session_id 过滤并展示全部。
 */
export function listNexusApprovals(sessionId = '', status = 'pending') {
  return request.get('/nexus/approvals', {
    params: { session_id: sessionId, status },
    allowFlatResponse: true,
    skipErrorToast: true,
  })
}

/** 可见 preset 投影（NX-LB1）：参数白名单/默认值/预算/指标基线的唯一来源。 */
export function listNexusReproPresets() {
  return request.get('/nexus/repro/presets', {
    allowFlatResponse: true,
    skipErrorToast: true,
  })
}

/** 建提案草案（NX-LB2）：创建不执行；client_request_id 幂等。 */
export function createNexusProposal(payload) {
  return request.post('/nexus/repro/proposals', payload, { allowFlatResponse: true })
}

/** 提案详情（NX-LB2）：完整方案 + 校验结果 + 与父运行/上一版本的 diff。 */
export function getNexusProposal(proposalId) {
  return request.get(`/nexus/repro/proposals/${encodeURIComponent(proposalId)}`, {
    allowFlatResponse: true,
    skipErrorToast: true,
  })
}

/** 改提案（NX-LB2）：乐观锁 expected_version；仅 draft；旧批准随 hash 失效。 */
export function patchNexusProposal(proposalId, payload) {
  return request.patch(`/nexus/repro/proposals/${encodeURIComponent(proposalId)}`, payload, {
    allowFlatResponse: true,
  })
}

/** 请求审批（NX-LB2）：pin 版本 + hash 生成/复用审批；不直接执行。 */
export function requestNexusProposalApproval(proposalId, expectedVersion) {
  return request.post(
    `/nexus/repro/proposals/${encodeURIComponent(proposalId)}/request-approval`,
    { expected_version: expectedVersion },
    { allowFlatResponse: true }
  )
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
 * T5：透传本次执行门（mode/research_execution_mode），缺省由服务端按
 * 兼容语义裁决（旧 preset 兼容，自主 fail-closed）。
 */
export function executeApprovedRepro(approvalId, sessionId = 'default', gate = {}) {
  const body = { approval_id: approvalId, session_id: sessionId }
  if (gate.mode) body.mode = gate.mode
  if (gate.researchExecutionMode) body.research_execution_mode = gate.researchExecutionMode
  return request.post('/nexus/repro/execute', body, {
    allowFlatResponse: true,
    skipErrorToast: true,
  })
}

/**
 * 用户直接取消运行（T5）：本人＋同会话；preset 走 Worker，自主走 Runtime。
 * 回收确认后终态 cancelled；执行器不可达 → 503，不伪装取消。
 */
export function cancelNexusRun(runId, sessionId) {
  return request.post(`/nexus/runs/${encodeURIComponent(runId)}/cancel`, {
    session_id: sessionId,
  }, { allowFlatResponse: true })
}

/**
 * 会话执行模式偏好（T5 Ask/Auto）：服务端真相源。
 * 无记录默认 ask；保存失败调用方只本地缓存并如实提示。
 */
export function getNexusSessionExecutionMode(sessionId) {
  return request.get(`/nexus/sessions/${encodeURIComponent(sessionId)}/execution-mode`, {
    allowFlatResponse: true,
    skipErrorToast: true,
  })
}

export function saveNexusSessionExecutionMode(sessionId, mode) {
  return request.put(`/nexus/sessions/${encodeURIComponent(sessionId)}/execution-mode`, {
    research_execution_mode: mode,
  }, { allowFlatResponse: true })
}

/**
 * 取消复现作业（NX-E3）：发起人鉴权后转发 Worker。幂等；与自然完成竞争时
 * Worker 保持真实终态。cancelled 之前状态为 cancelling（回收中）。
 */
export function cancelNexusReproJob(jobId) {
  return request.post(`/nexus/repro/jobs/${encodeURIComponent(jobId)}/cancel`, {}, {
    flatEnvelope: true,
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
 * 单个 run 详情（NX-LB1）：含 display_title/run_number/version/冻结配置，
 * NX-LB5 起含已授权 artifacts 引用。非 owner 一律 404。
 * F3：logCursors 为 {operation_id: 已消费字节}，在途会话操作返回增量。
 */
export function getNexusRunDetail(runId, logCursors) {
  const params = {}
  if (logCursors && typeof logCursors === 'object' && Object.keys(logCursors).length) {
    params.log_cursors = JSON.stringify(logCursors)
  }
  return request.get(`/nexus/runs/${encodeURIComponent(runId)}`, {
    params,
    allowFlatResponse: true,
    skipErrorToast: true,
  })
}

/**
 * 重命名运行（NX-LB1）：仅改标题，不改变执行 hash 或配置；乐观锁 409。
 */
export function renameNexusRun(runId, title, expectedVersion) {
  return request.patch(`/nexus/runs/${encodeURIComponent(runId)}`, {
    title,
    expected_version: expectedVersion,
  }, { allowFlatResponse: true })
}

/**
 * 取消授权签发（NX-LB4）：用户在浮窗明确确认取消后调用；一次性、短有效期。
 */
export function requestNexusRunCancelGrant(runId, sessionId) {
  return request.post(`/nexus/runs/${encodeURIComponent(runId)}/cancel-grant`, {
    session_id: sessionId,
  }, { allowFlatResponse: true })
}

/**
 * 运行备注列表（NX-LB5）：追加式，升序；Agent 备注标 author=agent。
 */
export function listNexusRunNotes(runId) {
  return request.get(`/nexus/runs/${encodeURIComponent(runId)}/notes`, {
    allowFlatResponse: true,
    skipErrorToast: true,
  })
}

/**
 * 自主运行报告＋配方生成（T6）：确定性拼装，不经 LLM。
 * 本人终态 run 才可生成；产物关联本 run，可下载；落盘后回收工作区。
 */
export function requestNexusRunReport(runId) {
  return request.post(`/nexus/runs/${encodeURIComponent(runId)}/report`, {}, {
    allowFlatResponse: true,
  })
}

/**
 * 自主运行正式格式产物（SR6）：Word .docx＋LaTeX .tex，确定性转换。
 * 与报告同门（本人终态 run）；内容同源同版本；纯渲染不碰沙箱。
 */
export function requestNexusRunFormats(runId) {
  return request.post(`/nexus/runs/${encodeURIComponent(runId)}/formats`, {}, {
    allowFlatResponse: true,
  })
}

/**
 * 自主运行干净验证（SR6）：全新沙箱重放冻结配方，比对退出码。
 * 重放调用实验沙箱——只在 Auto 下可用（Ask 服务端 403）。
 */
export function requestNexusRunCleanVerify(runId, executionMode) {
  return request.post(`/nexus/runs/${encodeURIComponent(runId)}/clean-verify`, {
    research_execution_mode: executionMode,
  }, {
    allowFlatResponse: true,
  })
}

/**
 * 自主运行恢复认领（F2）：对账在途意图，需继续时后台续跑同一实验。
 * 继续执行调用沙箱——只在 Auto 下可用（Ask 服务端 403）。
 */
export function requestNexusRunResume(runId, executionMode) {
  return request.post(`/nexus/runs/${encodeURIComponent(runId)}/resume`, {
    research_execution_mode: executionMode,
  }, {
    allowFlatResponse: true,
  })
}

/**
 * 自主运行操作级取消（F3）：只停卡住的命令，实验继续。
 * 会话在途 → 中断＋确认；one-shot 在途 → 409（请走 run 级取消）。
 */
export function cancelNexusRunOperation(runId, operationId) {
  return request.post(`/nexus/runs/${encodeURIComponent(runId)}/operations/${encodeURIComponent(operationId)}/cancel`, {}, {
    allowFlatResponse: true,
  })
}

/**
 * 文档作业创建（F6）：一份冻结内容，多格式正式输出。
 * 不要求先有实验 run（Ask 下可用）；同幂等键同内容去重。
 */
export function createNexusDocumentJob(payload) {
  return request.post('/nexus/documents/jobs', {
    source_kind: payload?.source_kind || 'markdown',
    run_id: payload?.run_id || '',
    artifact_id: payload?.artifact_id || '',
    markdown: payload?.markdown || '',
    title: payload?.title || '',
    template: payload?.template || 'tech_doc',
    formats: payload?.formats || ['markdown', 'word', 'latex'],
    idempotency_key: payload?.idempotency_key || '',
  }, {
    allowFlatResponse: true,
  })
}

/**
 * 文档作业查询（F6）：本人；含每格式独立状态/引擎/产物。
 */
export function getNexusDocumentJob(jobId) {
  return request.get(`/nexus/documents/jobs/${encodeURIComponent(jobId)}`, {
    allowFlatResponse: true,
    skipErrorToast: true,
  })
}

/**
 * 文档作业取消（F6）：仅非终态有效。
 */
export function cancelNexusDocumentJob(jobId) {
  return request.post(`/nexus/documents/jobs/${encodeURIComponent(jobId)}/cancel`, {}, {
    allowFlatResponse: true,
  })
}

/**
 * 文档作业重试（F6）：只跑失败格式；成功格式保留不重写。
 */
export function retryNexusDocumentJob(jobId) {
  return request.post(`/nexus/documents/jobs/${encodeURIComponent(jobId)}/retry`, {}, {
    allowFlatResponse: true,
  })
}

/**
 * 研究任务创建（F7）：Brief＋子问题＋预算；只建任务、不执行。
 */
export function createNexusResearchTask(payload) {
  return request.post('/nexus/research/tasks', {
    objective: payload?.objective || '',
    dimensions: payload?.dimensions || '',
    data_range: payload?.data_range || '',
    time_range: payload?.time_range || '',
    delivery_format: payload?.delivery_format || '',
    questions: payload?.questions || [],
    budget: payload?.budget || {},
    parent_task_id: payload?.parent_task_id || '',
  }, {
    allowFlatResponse: true,
  })
}

/**
 * 研究任务列表（F7）：本人；中断恢复查看入口。
 */
export function listNexusResearchTasks(sessionId) {
  const params = {}
  if (sessionId) params.session_id = sessionId
  return request.get('/nexus/research/tasks', {
    params,
    allowFlatResponse: true,
    skipErrorToast: true,
  })
}

/**
 * 研究任务详情（F7）：含预算余量＋交付核对。
 */
export function getNexusResearchTask(taskId) {
  return request.get(`/nexus/research/tasks/${encodeURIComponent(taskId)}`, {
    allowFlatResponse: true,
    skipErrorToast: true,
  })
}

/**
 * 研究任务取消（F7）：置旗即停；已保存材料保留。
 */
export function cancelNexusResearchTask(taskId) {
  return request.post(`/nexus/research/tasks/${encodeURIComponent(taskId)}/cancel`, {}, {
    allowFlatResponse: true,
  })
}

/**
 * 受控对照创建（F8）：对照说明＋两组冻结配方引用；只建对照、不执行。
 */
export function createNexusCompare(payload) {
  return request.post('/nexus/compares', {
    objective: payload?.objective || '',
    common: payload?.common || {},
    allowed_varied: payload?.allowed_varied || [],
    arms: payload?.arms || [],
    approval_ref: payload?.approval_ref || '',
  }, {
    allowFlatResponse: true,
  })
}

/**
 * 受控对照列表（F8）：本人；中断恢复查看入口。
 */
export function listNexusCompares(sessionId) {
  const params = {}
  if (sessionId) params.session_id = sessionId
  return request.get('/nexus/compares', {
    params,
    allowFlatResponse: true,
    skipErrorToast: true,
  })
}

/**
 * 受控对照详情（F8）：含并列报告。
 */
export function getNexusCompare(compareId) {
  return request.get(`/nexus/compares/${encodeURIComponent(compareId)}`, {
    allowFlatResponse: true,
    skipErrorToast: true,
  })
}

/**
 * 受控对照取消（F8）：置终态；已关联结果保留。
 */
export function cancelNexusCompare(compareId) {
  return request.post(`/nexus/compares/${encodeURIComponent(compareId)}/cancel`, {}, {
    allowFlatResponse: true,
  })
}

/**
 * 对照组关联运行（F8）：只关联终态；配方不一致即拒绝。
 */
export function linkNexusCompareRun(compareId, armName, runId) {
  return request.post(`/nexus/compares/${encodeURIComponent(compareId)}/link-run`, {
    arm_name: armName,
    run_id: runId,
  }, {
    allowFlatResponse: true,
  })
}

/**
 * 追加运行备注（NX-LB5）：requestId 幂等；content ≤4000 字符。
 */
export function createNexusRunNote(runId, content, requestId = '') {
  return request.post(`/nexus/runs/${encodeURIComponent(runId)}/notes`, {
    content,
    request_id: requestId,
  }, { allowFlatResponse: true })
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
 * @param {string} [options.researchExecutionMode] T5 Ask/Auto（ask|auto，仅 Research 发送）
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
  researchExecutionMode = null,
  courseId = null,
  model = null,
  attachmentIds = [],
  onEvent,
  signal,
}) {
  const body = { message, session_id: sessionId }
  // 接线预留：运行时一旦在 /chat/stream 接收这两个字段，前端无需任何改动。
  if (mode) body.mode = mode
  // T5 Ask/Auto：Research 显式发送本次 effective 值；General 不传。
  if (researchExecutionMode) body.research_execution_mode = researchExecutionMode
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
