<script setup>
/**
 * Nexus AI 全局工作区（三栏架构：Local Rail ｜ 主工作区 ｜ 右侧回应区）
 *
 * 遵循规范：
 * - page-design.md §4.1 / §4.5 / §3.4 响应式三栏与设备状态持久化
 * - design.md §5 三层滚动模型（L3 根容器 100% + min-height:0 内部滚动）、§9 按钮规范、§12 令牌纪律
 * - UX 规格：Mode 切换即工具白名单、上下文 Chips 三态、过程可见（不暴露 CoT）
 *
 * 本轮可用性重构（2026-09-03）：
 * - 数据源切换收敛到侧栏底部状态区（唯一入口）；演示模式顶部保留一条状态说明条
 * - 首屏 Chips 只展示 ready 能力（工具已配齐，「N 项待接入」开发中说明已删；
 *   三态真相仍在 nexusCapabilities.js，接线状态不靠界面贴条）
 * - 右栏大数字统计块改为「能力状态」列表（与 Chips 同一真相源，不再自相矛盾）
 * - 过程层统一「实验记录轨」视觉：surface-cool 底 + 状态点 + mono 时间戳
 * - 修复：isToolExpanded 未定义导致过程卡展开崩溃；多个模板类名与样式错位；
 *   「添加上下文 / @ / Paperclip」三个无行为死控件移除（文件上传诚实标注为未接入）
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  Activity,
  AlertCircle,
  BookMarked,
  BookOpen,
  Bot,
  Check,
  ChevronDown,
  Copy,
  Database,
  Download,
  ExternalLink,
  FileCode,
  FileText,
  FlaskConical,
  Globe,
  Layers,
  Link2,
  Microscope,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  Paperclip,
  Pencil,
  Pin,
  PinOff,
  Plus,
  RotateCw,
  Search,
  Send,
  Sparkles,
  Square,
  Trash2,
  TriangleAlert,
  User,
  Wrench,
  X
} from 'lucide-vue-next'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxDrawer from '@/app/ui/SfxDrawer.vue'
import { showToast } from '@/utils/toast.js'
import { useCounterStore } from '@/stores/counter.js'
import { renderContent } from '@/utils/markdownRenderer.js'
import { getNexusHealth, getNexusSessionMessages, getNexusPlan, listNexusSessions, listNexusArtifacts, downloadNexusArtifact, getNexusReproJob, requestReproReport, requestNexusRunReport, decideNexusApproval, executeApprovedRepro, cancelNexusReproJob, cancelNexusRun, getNexusRunDetail, getNexusSessionExecutionMode, saveNexusSessionExecutionMode, uploadNexusAttachment, deleteNexusAttachment, listNexusRuns, renameNexusRun, listNexusRunNotes, createNexusRunNote, listNexusReproPresets, listNexusApprovals, requestNexusRunCancelGrant, createNexusProposal, requestNexusProposalApproval } from '@/api/nexus.js'
import {
  NEXUS_MODES,
  NEXUS_MODE_CONFIG,
  nexusDataSourceMode,
  setNexusDataSourceMode,
  loadLocalSessions,
  saveLocalSessions,
  getContextOverview,
  dispatchNexusMessage
} from '@/api/nexusAdapter.js'
import {
  CAPABILITY_STATE,
  EFFECTIVE_STATE,
  isReproductionExecutable,
  resolveEffectiveCapabilities
} from '@/api/nexusCapabilities.js'
import { applyPlanEvent, applyRestoredPlan, createPlanState } from './planState.js'
import NexusPlanCard from './components/NexusPlanCard.vue'
import NexusEvidenceCard from './components/NexusEvidenceCard.vue'
import NexusExperimentWorkspace from './components/NexusExperimentWorkspace.vue'
import NexusAskWindow from './components/NexusAskWindow.vue'
import {
  experimentName,
  reproCancellable,
  reproElapsed,
  reproIsCurrentStep,
  reproLogLines,
  reproLogSource,
  reproStageNotes,
  reproStageRail,
  reproStatusLabel,
  reproStepLabel,
  reproStepState,
  REPRO_TERMINAL_STATUSES
} from './reproShared.js'

// ── 0. 使用权限（转型决策 D10：platform.nexus.use 显式授予）──
const counter = useCounterStore()

// ── 1. 响应式与三栏折叠状态 ──
const railCollapsed = ref(localStorage.getItem('nexus_rail_collapsed') === 'true')
const windowWidth = ref(window.innerWidth)

const isTablet = computed(() => windowWidth.value >= 1024 && windowWidth.value < 1200)
const isMobileOrSmall = computed(() => windowWidth.value < 1024)
const isRailExpanded = computed(() => !railCollapsed.value || isMobileOrSmall.value)

/* 回应区在桌面断点常驻（产品决定：过程与来源必须始终可见），仅窄屏按断点隐藏 */
function updateDimensions() {
  windowWidth.value = window.innerWidth
}

function toggleRail() {
  railCollapsed.value = !railCollapsed.value
  localStorage.setItem('nexus_rail_collapsed', String(railCollapsed.value))
}

// ── 2. 会话状态与持久化（仅本机，UI 如实标注） ──
const sessions = ref([])
const activeSessionId = ref('')
const searchQuery = ref('')
const renamingSessionId = ref('')
const renameDraft = ref('')
const confirmDeleteId = ref('')
const openMenuSessionId = ref('')

const currentSession = computed(() => {
  return sessions.value.find((s) => s.id === activeSessionId.value) || null
})

const activeMode = computed({
  get() {
    return currentSession.value?.mode || NEXUS_MODES.GENERAL
  },
  set(val) {
    if (currentSession.value) {
      currentSession.value.mode = val
      persistSessions()
    }
  }
})

function persistSessions() {
  saveLocalSessions(sessions.value)
}

// ── 2b. v6：同一个研究会话的两个视图（研究对话 ／ 实验工作台）──
// 工作台不是独立页面、不新增路由；它是本会话 run 数据的另一种视图。
// 视图选择记在本会话 sessionStorage：刷新保持，换会话不串。
const workspaceView = ref(
  typeof sessionStorage !== 'undefined' && sessionStorage.getItem('nexus_workspace_view') === 'lab'
    ? 'lab'
    : 'chat'
)

function setWorkspaceView(v) {
  workspaceView.value = v
  // 浮窗属于工作台；离开工作台就收起（运行时才可能执行到这里，无 TDZ 风险）
  if (v !== 'lab') askWindowOpen.value = false
  try {
    sessionStorage.setItem('nexus_workspace_view', v)
  } catch {
    /* 存储不可用时仅退化为本次不记忆 */
  }
}

/**
 * 本会话的 run 列表。显示名以**后端命名**为准（NX-LB1：display_title，
 * 用户命名优先、否则 preset 展示名 + 会话内稳定序号，跨设备一致）；
 * 本地/demo 运行（无后端行）回退 experimentName 本地命名。
 * 后端命名经 backendRunNames 按 job_id 合并——turn.reproRun 本体只读
 * 投影，不在此改写轮询状态。
 */
const backendRunNames = ref({})

function stampBackendRunName(reproRun, backend) {
  if (!reproRun || !backend) return
  // 只合命名类元数据：显示/重命名/序号/版本，不碰状态与轮询字段。
  for (const key of ['display_title', 'title', 'run_number', 'version',
    'preset_display_name', 'paper_title']) {
    if (backend[key] !== undefined) reproRun[key] = backend[key]
  }
  if (backend.runId) reproRun.runId = backend.runId
}

const sessionRuns = computed(() => {
  const s = currentSession.value
  if (!s?.turns?.length) return []
  return s.turns
    // T5：自主 run 无 job_id，按 run_id/runId 收敛（与 preset job 标识不碰撞）。
    .filter((t) => t?.reproRun && (t.reproRun.job_id || t.reproRun.run_id || t.reproRun.runId))
    .map((t, i, arr) => {
      const preset = t.reproRun.preset_id
      const seq = arr.slice(0, i).filter((x) => x?.reproRun?.preset_id === preset).length + 1
      const backend = backendRunNames.value[t.reproRun.job_id]
        || backendRunNames.value[t.reproRun.run_id || t.reproRun.runId] || {}
      // runId = nexus_runs.run_id（NX-LB1 稳定标识）：重命名 / 备注 / 详情用它；
      // job_id 只服务 Worker cancel / report。无 runId → 重命名不可用。
      // T5：自主 run 无 job_id，id 回退 runId（同一会话内唯一，不碰撞）。
      const runId = t.reproRun.runId || t.reproRun.run_id || ''
      return {
        id: t.reproRun.job_id || runId,
        runId,
        name: experimentName({ ...t.reproRun, ...backend }, seq),
        run: t.reproRun,
        turn: t
      }
    })
})

const runningRunCount = computed(
  () => sessionRuns.value.filter((r) => ['queued', 'running', 'cancelling'].includes(r.run.status)).length
)

const activeRunId = ref('')
watch(
  sessionRuns,
  (list) => {
    if (!list.length) {
      if (activeRunId.value) activeRunId.value = ''
      return
    }
    if (!list.some((r) => r.id === activeRunId.value)) {
      activeRunId.value = list[list.length - 1].id
    }
  },
  { immediate: true }
)

const isResearchMode = computed(() => activeMode.value === NEXUS_MODES.RESEARCH)
const isLabView = computed(() => isResearchMode.value && workspaceView.value === 'lab')
const activeRun = computed(() => sessionRuns.value.find((r) => r.id === activeRunId.value) || null)
const activeRunArtifacts = computed(() => activeRun.value?.turn?.artifacts || [])

function switchActiveRun(id) {
  activeRunId.value = id
}

/** 会话内「打开工作台」：定位到该 run 并切到工作台视图 */
function openRunInWorkspace(turn) {
  if (turn?.reproRun?.job_id) activeRunId.value = turn.reproRun.job_id
  else if (turn?.reproRun?.run_id || turn?.reproRun?.runId) {
    activeRunId.value = turn.reproRun.run_id || turn.reproRun.runId
  }
  setWorkspaceView('lab')
}

// 工作台里对某个 run 取消：复用会话内既有的 cancel 实现（同一 API、同一文案）
async function cancelRunFromWorkspace(id) {
  const item = sessionRuns.value.find((r) => r.id === id)
  if (item?.turn) await cancelReproRun(item.turn)
}

// ── 询问 Nexus 浮窗（工作台内）：继承研究对话上下文 ──
const askWindowOpen = ref(false)
function openAskWindow() {
  askWindowOpen.value = true
}
function onAskSend(text) {
  // 引用边界：只带明确的 run ID / 步骤，不复制全量日志、不混其他会话
  const run = activeRun.value?.run
  const ref = run ? `\n\n（引用：本次运行 ${run.job_id}· 第 ${run.currentStep ?? '—'} 步）` : ''
  draft.value = `${text}${ref}`
  setWorkspaceView('chat')
  askWindowOpen.value = false
  send()
}

// 结果态：回到研究对话解释结果（预填，由用户发送，不自动触发模型任务）
function analyzeRunResult(id) {
  const item = sessionRuns.value.find((r) => r.id === id)
  const run = item?.run
  const verdict = run?.verdict ? `判定 ${run.verdict}` : '结果'
  draft.value = `请解释本次实验结果（${item?.name || '本次运行'} · ${verdict}），与预期有什么差异，下一步建议是什么？`
  setWorkspaceView('chat')
  nextTick(() => {
    const el = document.querySelector('.nx-composer-textarea')
    if (el) el.focus()
  })
}

// ── NX-LB2 调整方案再运行：基于父运行的冻结参数开新提案 → 送审 → 浮窗批准 ──
// 白名单/范围来自 GET /repro/presets 的 parameters.schema（零前端硬编码）；
// 基线优先取 run 详情 config_snapshot.parameters，取不到回 preset 默认值。
const proposalDraft = ref(null)

function rerunFromWorkspace(id) {
  const item = sessionRuns.value.find((r) => r.id === (id || activeRunId.value))
  const runId = item?.runId
  const preset = item
    ? reproPresets.value.find((p) => (p.preset_id || p.id) === item.run?.preset_id) || null
    : null
  const schema = preset?.parameters?.schema
  if (!item || !runId) {
    showToast('本次运行还没有服务端记录（run_id 缺失），不能基于它创建新提案', 'error')
    return
  }
  if (!schema || !Object.keys(schema).length) {
    showToast('该预设暂不支持参数化，可在对话里描述要调整的方向', 'info')
    return
  }
  const values = {}
  for (const [name, spec] of Object.entries(schema)) values[name] = String(spec.default ?? '')
  proposalDraft.value = {
    runId,
    presetId: preset.preset_id,
    presetName: preset.display_name || preset.preset_id,
    runName: item.name,
    schema,
    baseline: { ...values },
    values,
    submitting: false,
    error: ''
  }
  // 冻结基线异步补齐：只取白名单内的键；详情取不到就按 preset 默认值当基线
  void (async () => {
    try {
      const det = await getNexusRunDetail(runId)
      const frozen = det?.config_snapshot?.parameters
      const d = proposalDraft.value
      if (d && d.runId === runId && frozen && typeof frozen === 'object') {
        for (const name of Object.keys(schema)) {
          if (frozen[name] !== undefined && frozen[name] !== null) {
            d.baseline[name] = String(frozen[name])
            d.values[name] = String(frozen[name])
          }
        }
      }
    } catch { /* 保持默认基线 */ }
  })()
}

function closeProposalEditor() {
  if (proposalDraft.value?.submitting) return
  proposalDraft.value = null
}

function paramChanged(name) {
  const d = proposalDraft.value
  return !!d && String(d.values[name]) !== String(d.baseline[name])
}

const proposalChangedCount = computed(() => {
  const d = proposalDraft.value
  if (!d) return 0
  return Object.keys(d.schema).filter((n) => String(d.values[n]) !== String(d.baseline[n])).length
})

const metricSensitiveChanged = computed(() => {
  const d = proposalDraft.value
  if (!d) return false
  return Object.entries(d.schema).some(
    ([n, sp]) => sp.metric_sensitive && String(d.values[n]) !== String(d.baseline[n])
  )
})

async function submitProposal() {
  const d = proposalDraft.value
  if (!d || d.submitting) return
  // 前端先做类型/范围校验（与服务端 schema 同规则；422 兜底直接透出）
  const params = {}
  for (const [name, spec] of Object.entries(d.schema)) {
    const raw = String(d.values[name] ?? '').trim()
    const num = Number(raw)
    if (!raw || !Number.isFinite(num)) {
      d.error = name + '：需要数字'
      return
    }
    if (spec.type === 'int' && !Number.isInteger(num)) {
      d.error = name + '：需要整数'
      return
    }
    if (num < spec.min || num > spec.max) {
      d.error = name + '：允许范围 ' + spec.min + '–' + spec.max
      return
    }
    params[name] = num
  }
  d.submitting = true
  d.error = ''
  try {
    let reqId = ''
    try { reqId = crypto.randomUUID() } catch { reqId = 'rerun-' + Date.now() }
    const res = await createNexusProposal({
      preset_id: d.presetId,
      session_id: activeSessionId.value || 'default',
      parent_run_id: d.runId,
      parameters: params,
      client_request_id: reqId
    })
    const p = res?.proposal || res || {}
    await requestNexusProposalApproval(p.proposal_id, p.version)
    proposalDraft.value = null
    await loadPendingApprovals()
    showToast('新提案已送审，请在输入框上方确认后才会执行', 'success')
  } catch (err) {
    const code = err?.errorCode || err?.response?.data?.code || ''
    const map = {
      PROPOSAL_PARAM_UNKNOWN: '参数不在该预设的白名单内',
      PROPOSAL_PARAM_TYPE: '参数类型不符合 schema',
      PROPOSAL_PARAM_OUT_OF_RANGE: '参数超出允许范围',
      PROPOSAL_PRESET_UNSUPPORTED: '该预设暂不支持参数化',
      PROPOSAL_PARENT_NOT_FOUND: '原运行不存在或已不可引用',
      PROPOSAL_VERSION_CONFLICT: '提案版本冲突，请重试'
    }
    d.error = map[code] || err?.message || '提案创建失败，未执行任何操作'
    d.submitting = false
  }
}

// ── NX-LB4 取消授权签发：模型请求取消时，用户在此显式授权 ──
// 模型意图本身不构成授权；grant 只由本端点（登录态）签发，
// 一次性、5 分钟 TTL，绑定 (user, run, cancel_run)，模型工具核销后才真取消。
async function grantCancelFor(turn) {
  const run = turn?.reproRun
  const runId = run?.runId || run?.run_id
  if (!runId) {
    showToast('本次运行还没有服务端记录，无法签发取消授权', 'error')
    return
  }
  if (run.granting) return
  run.granting = true
  try {
    await requestNexusRunCancelGrant(runId, activeSessionId.value || 'default')
    showToast('已签发一次性取消授权（5 分钟内有效）：Nexus 现在可以取消本次运行', 'success')
  } catch (err) {
    const code = err?.errorCode || err?.response?.data?.code || ''
    if (code === 'RUN_SESSION_MISMATCH') {
      showToast('会话不匹配：请回到发起该运行的会话再签发', 'error')
    } else if (err?.status === 404) {
      showToast('运行不存在或没有服务端记录', 'error')
    } else {
      showToast('签发失败，请重试', 'error')
    }
  } finally {
    run.granting = false
  }
}

// ── NX-LB1 重命名：PATCH /runs/{run_id}，乐观锁 ──
// 只改显示名，不改执行 hash / 配置；冲突 409 拉最新不覆盖用户输入。
async function renameRunFromWorkspace({ id, title, onError, onDone }) {
  const item = sessionRuns.value.find((r) => r.id === id)
  const runId = item?.runId
  if (!runId) {
    onError?.('本次运行还没有服务端记录（run_id 缺失），暂不能重命名')
    return
  }
  const version = Number(item.run.version ?? item.run.run_number ?? 0)
  try {
    const res = await renameNexusRun(runId, title || null, version)
    const merged = res?.data ?? res
    if (merged && typeof merged === 'object') {
      item.run.title = merged.title ?? item.run.title
      item.run.display_title = merged.display_title ?? item.run.display_title
      item.run.version = merged.version ?? item.run.version
    }
    // 让 sessionRuns 重算显示名（服务端 display_title 优先）
    backendRunNames.value[item.run.job_id] = {
      ...(backendRunNames.value[item.run.job_id] || {}),
      ...(merged || {}),
      runId
    }
    onDone?.()
    showToast(title ? '已重命名' : '已恢复默认名', 'success')
  } catch (err) {
    const code = err?.response?.data?.code || err?.code || ''
    if (code === 'RUN_VERSION_CONFLICT') {
      onError?.('运行信息已被别处更新，已刷新为最新名称')
    } else if (err?.response?.status === 422) {
      onError?.('名称不合法（1–120 字符）')
    } else {
      onError?.('重命名失败，请稍后重试')
    }
  }
}

// ── NX-LB5 运行备注：追加式，request_id 幂等 ──
const runNotes = ref([])
const noting = ref(false)

async function loadRunNotes(runId) {
  if (!runId) {
    runNotes.value = []
    return
  }
  try {
    const res = await listNexusRunNotes(runId)
    const data = res?.data ?? res
    runNotes.value = Array.isArray(data?.items) ? data.items : Array.isArray(data) ? data : []
  } catch {
    // fail-closed：拉不到就显示为空并如实说明，不伪造条目
    runNotes.value = []
  }
}

watch(
  () => activeRun.value?.runId || '',
  (rid) => {
    if (isLabView.value) loadRunNotes(rid)
  },
  { immediate: true }
)
watch(isLabView, (v) => {
  if (v) loadRunNotes(activeRun.value?.runId || '')
})

async function addRunNote({ content, onError, onDone }) {
  const runId = activeRun.value?.runId
  if (!runId) {
    onError?.('本次运行还没有服务端记录，暂不能加备注')
    return
  }
  noting.value = true
  const requestId = `note-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  try {
    await createNexusRunNote(runId, content, requestId)
    await loadRunNotes(runId)
    onDone?.()
  } catch {
    onError?.('备注保存失败，请重试')
  } finally {
    noting.value = false
  }
}

// ── T6 自主运行报告＋配方：确定性拼装，不经 LLM；产物关联本 run，可下载 ──
async function requestAutoReport(id) {
  const item = sessionRuns.value.find((r) => r.id === id)
  const run = item?.run
  const runId = item?.runId
  if (!run || !runId || run.reportRequested) return
  run.reportRequested = true
  try {
    const res = await requestNexusRunReport(runId)
    for (const a of res?.artifacts || []) {
      if (a?.artifact_id && !(item.turn.artifacts || []).some((x) => x.artifact_id === a.artifact_id)) {
        item.turn.artifacts = [...(item.turn.artifacts || []), a]
      }
    }
    persistSessions()
    showToast(`报告已生成：执行${res?.execution_succeeded ? '成功' : '失败'} · 指标${res?.metric_verdict || '—'} · ${res?.artifacts?.length || 0} 个产物`, 'success')
  } catch (err) {
    run.reportRequested = false
    showToast(err?.message || '报告生成失败', 'error')
  }
}

// ── NX-LB1 preset 投影：参数白名单唯一来源，前端不硬编码 ──
const reproPresets = ref([])
const activePreset = computed(() => {
  const pid = activeRun.value?.run?.preset_id
  if (!pid) return null
  return reproPresets.value.find((p) => (p.preset_id || p.id) === pid) || null
})

async function loadReproPresets() {
  try {
    const res = await listNexusReproPresets()
    const data = res?.data ?? res
    const list = Array.isArray(data?.items) ? data.items : Array.isArray(data) ? data : []
    reproPresets.value = list
  } catch {
    reproPresets.value = []
  }
}
onMounted(() => {
  if (nexusDataSourceMode.value === 'real') loadReproPresets()
})

/**
 * 输入框上方的审批浮窗要展示的提案：本会话**最近一个仍处于 pending** 的审批。
 * 已批准 / 已拒绝 / 已过期的都不再浮在输入框上——它们归消息流留存。
 */
const pendingApproval = computed(() => {
  const turns = currentSession.value?.turns || []
  for (let i = turns.length - 1; i >= 0; i -= 1) {
    const t = turns[i]
    if (t?.approval?.status === 'pending' && t.approval.approval_id) return t
  }
  return null
})

/* ── NX-LB2 审批待办恢复 + 提案摘要（审批浮窗 v2）──
 * SSE 推来的审批卡在消息流里；但刷新/换设备后只剩服务端记录，
 * 浮窗必须能从 GET /approvals?session_id&status=pending 恢复待办。
 * 两条来源按 approval_id 去重，服务端为准（它可能更新了版本/失效）。 */
const restoredApprovals = ref([])

async function loadPendingApprovals() {
  const sid = activeSessionId.value
  if (!sid || nexusDataSourceMode.value !== 'real') {
    restoredApprovals.value = []
    return
  }
  try {
    const res = await listNexusApprovals(sid, 'pending')
    const data = res?.data ?? res
    const items = Array.isArray(data?.items) ? data.items : Array.isArray(data) ? data : []
    restoredApprovals.value = items
  } catch {
    // fail-closed：拉不到就只显示 SSE 来源的待办，不伪造
    restoredApprovals.value = []
  }
}

/** 归一化：SSE 的 turn 与服务端待办项形状不同，浮窗只认这一种 */
function normalizeApproval(src) {
  const ap = src?.approval || src || {}
  return {
    id: ap.approval_id || ap.id || '',
    preset: ap.preset_id || ap.preset || '',
    objective: ap.objective || '',
    repo: ap.repo_url || ap.repo || '',
    license: ap.repo_license || ap.license || '',
    budget: ap.budget || {},
    planHash: ap.plan_hash || ap.hash || '',
    expiresAt: ap.expires_at || '',
    proposalId: ap.proposal_id || '',
    proposalVersion: ap.proposal_version ?? ap.version ?? null,
    diff: Array.isArray(ap.diff) ? ap.diff : Array.isArray(ap.parameter_diff) ? ap.parameter_diff : [],
    baselineNote: ap.baseline_note || ap.metric_policy || '',
    status: ap.status || '',
    turn: src?.approval ? src : null
  }
}

/** 浮窗要展示的待办：服务端恢复项 + SSE 卡，按 approval_id 去重（服务端优先） */
const pendingItems = computed(() => {
  const map = new Map()
  const push = (raw) => {
    const n = normalizeApproval(raw)
    if (!n.id) return
    if (!map.has(n.id)) map.set(n.id, n)
  }
  for (const raw of restoredApprovals.value) push(raw)
  const t = pendingApproval.value
  if (t) {
    const n = normalizeApproval(t)
    // 服务端那条可能带更全的 diff/objective：有提案信息的留服务端，否则补 SSE
    if (!map.has(n.id)) map.set(n.id, n)
  }
  return [...map.values()]
})

/** 服务端恢复项（没有 SSE turn）批准：decide 后走同一 execute 核销 */
async function approveRestored(item) {
  if (item.turn) {
    await decideApprovalFor(item.turn, 'approved')
    await loadPendingApprovals()
    return
  }
  try {
    await decideNexusApproval(item.id, 'approved')
    await executeApprovedRepro(item.id, activeSessionId.value || 'default', {
      mode: activeMode.value,
      researchExecutionMode: isResearchMode.value ? execMode.value : null,
    })
    showToast('已批准并提交执行', 'success')
  } catch (err) {
    const code = err?.response?.data?.code || err?.code || ''
    if (code === 'APPROVAL_STALE' || code === 'APPROVAL_INVALID') {
      showToast('方案已更新或票据失效，请重新确认', 'error')
    } else {
      showToast('批准失败，请重试', 'error')
    }
  }
  await loadPendingApprovals()
}

// T5：浮窗合并操作——切换 Auto＋本次批准＋执行一次完成（无 turn 项专用）。
async function approveRestoredWithAuto(item) {
  if (item.turn) {
    await approveWithAuto(item.turn)
    await loadPendingApprovals()
    return
  }
  try {
    await setExecMode('auto')
    await decideNexusApproval(item.id, 'approved')
    await executeApprovedRepro(item.id, activeSessionId.value || 'default', {
      mode: activeMode.value,
      researchExecutionMode: 'auto',
    })
    showToast('已切换 Auto 并批准提交执行', 'success')
  } catch (err) {
    showToast(err?.message || '切换并批准失败，未执行任何操作', 'error')
  }
  await loadPendingApprovals()
}

async function rejectRestored(item) {
  if (item.turn) {
    await decideApprovalFor(item.turn, 'rejected')
    await loadPendingApprovals()
    return
  }
  try {
    await decideNexusApproval(item.id, 'rejected')
    showToast('已拒绝', 'success')
  } catch {
    showToast('拒绝失败，请重试', 'error')
  }
  await loadPendingApprovals()
}

watch(activeSessionId, () => {
  loadPendingApprovals()
})
onMounted(() => {
  if (nexusDataSourceMode.value === 'real') loadPendingApprovals()
})

function diffKindLabel(kind) {
  const k = String(kind || '').toLowerCase()
  if (k.includes('add') || k === 'new') return '新增'
  if (k.includes('del') || k.includes('remove')) return '移除'
  return '修改'
}
function diffKindClass(kind) {
  const k = String(kind || '').toLowerCase()
  if (k.includes('add') || k === 'new') return 'is-add'
  if (k.includes('del') || k.includes('remove')) return 'is-del'
  return 'is-mod'
}

/**
 * 浮窗继承的引用徽标：如实写出「带进去了什么」。
 * 只带 job_id / 步骤 / 有界日志行数，不复制全量日志、不混入其他会话。
 */
const askContextPill = computed(() => {
  const run = activeRun.value?.run
  if (!run) return ''
  const step = run.currentStep ?? '—'
  const ref = run.job_id || run.run_id || run.runId || '—'
  return `附引用 ${ref} · 第 ${step} 步 · 日志末 ${reproLogLines(run).length} 行`
})

/** 「查看完整方案」：滚到消息流里那张审批卡（提案全文在那儿，浮窗只是摘要） */
function scrollToApprovalInStream() {
  setWorkspaceView('chat')
  nextTick(() => {
    const el = document.querySelector('.nx-repro-live')
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  })
}

function initSessions() {
  sessions.value = loadLocalSessions()
  if (sessions.value.length > 0) {
    activeSessionId.value = sessions.value[0].id
  } else {
    createNewSession()
  }
  // P1-C2/C3：real 模式下拉取服务端持久化会话（best-effort，失败保持本地列表）。
  refreshRemoteSessions()
  // NX-E1：初次加载即恢复当前会话的 runs（刷新后找回原实验，不重新提交）。
  const initial = sessions.value.find((s) => s.id === activeSessionId.value)
  if (initial) {
    void restoreSessionRuns(initial)
    void restoreSessionPlan(initial)
  }
}

/**
 * real 模式：把 Runtime 持久化的会话并入侧栏。
 *
 * 合并规则（本地 id 即发给 Runtime 的 session_id，天然可对齐）：
 * - 服务端有、本地无 → 建 remoteOnly 壳会话，选中时再拉历史；
 * - 两边都有 → 保留本地 turns（含工具轨迹），仅采纳服务端标题兜底；
 * - demo 种子会话（id 以 demo- 开头）在 real 模式下隐藏，避免演示数据混入真实列表。
 * 接口失败时静默保持本地列表——列表缺失不能伪装成"没有历史"。
 */
async function refreshRemoteSessions() {
  if (nexusDataSourceMode.value !== 'real') return
  // M3：服务器产物列表（best-effort，失败保留旧值）
  try {
    const res = await listNexusArtifacts()
    remoteArtifacts.value = Array.isArray(res?.items) ? res.items : []
  } catch {
    /* 保留旧列表 */
  }
  let remote
  try {
    remote = await listNexusSessions()
  } catch {
    return
  }
  const remoteSessions = Array.isArray(remote?.sessions) ? remote.sessions : []
  const byId = new Map(sessions.value.map((s) => [s.id, s]))
  for (const rs of remoteSessions) {
    const sid = String(rs.session_id || '')
    if (!sid) continue
    const existing = byId.get(sid)
    const updatedAt = Date.parse(rs.updated_at) || Date.now()
    if (existing) {
      if (!existing.turns?.length && rs.title && existing.title.startsWith('新建')) {
        existing.title = rs.title
      }
      existing.updatedAt = Math.max(existing.updatedAt || 0, updatedAt)
    } else {
      const shell = {
        id: sid,
        title: rs.title || sid,
        mode: NEXUS_MODES.GENERAL,
        pinned: false,
        createdAt: updatedAt,
        updatedAt,
        courseId: null,
        courseName: null,
        remoteOnly: true,
        historyLoaded: false,
        turns: []
      }
      sessions.value.push(shell)
      byId.set(sid, shell)
    }
  }
  if (nexusDataSourceMode.value === 'real') {
    persistSessions()
  }
}

/** 拉取 remoteOnly 会话的服务端历史，投影成 turns（工具过程未持久化，如实留空）。 */
async function loadRemoteHistory(session) {
  if (!session || session.historyLoaded || nexusDataSourceMode.value !== 'real') return
  session.historyLoaded = true
  let res
  try {
    res = await getNexusSessionMessages(session.id)
  } catch (err) {
    session.historyLoaded = false
    showToast(err?.message || '历史消息加载失败', 'error')
    return
  }
  const messages = Array.isArray(res?.messages) ? res.messages : []
  const turns = []
  let current = null
  for (const m of messages) {
    if (m.role === 'user') {
      current = {
        question: m.content,
        answer: '',
        toolEvents: [],
        papers: [],
        artifacts: [],
        reproductionPreset: null,
        tokenCount: null,
        durationMs: null,
        failure: '',
        remoteHistory: true,
        createdAt: null
      }
      turns.push(current)
    } else if (m.role === 'assistant') {
      if (!current) {
        current = {
          question: '',
          answer: '',
          toolEvents: [],
          papers: [],
          artifacts: [],
          reproductionPreset: null,
          tokenCount: null,
          durationMs: null,
          failure: '',
          remoteHistory: true,
          createdAt: null
        }
        turns.push(current)
      }
      current.answer = current.answer ? `${current.answer}\n\n${m.content}` : m.content
    }
  }
  session.turns = turns
  persistSessions()
  scrollToBottom()
}

function createNewSession(initialMode = NEXUS_MODES.GENERAL) {
  const newId = `session-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`
  const newSession = {
    id: newId,
    title: initialMode === NEXUS_MODES.RESEARCH ? '新建研究任务' : '新建对话',
    mode: initialMode,
    pinned: false,
    createdAt: Date.now(),
    updatedAt: Date.now(),
    courseId: null,
    courseName: null,
    contextSources: {
      course: true,
      courseMaterials: true,
      disciplineKb: true,
      webSearch: 'auto', // 'auto' | 'off'
    },
    turns: [],
  }
  sessions.value.unshift(newSession)
  activeSessionId.value = newId
  persistSessions()
}

function switchSession(id) {
  activeSessionId.value = id
  const target = sessions.value.find((s) => s.id === id)
  if (target?.remoteOnly) {
    loadRemoteHistory(target)
  }
  // NX-E1：切会话即恢复该会话的 runs（只读恢复轮询，绝不重新提交）。
  if (target) {
    void restoreSessionRuns(target)
    void restoreSessionPlan(target)
    // T5：执行模式随会话恢复（服务端偏好真相源；失败本地默认 ask）。
    void restoreExecMode(target)
  }
}

// ── T5 Ask/Auto：Research 输入框选择器 ＋ 服务端会话偏好 ──
// - 只在 Research 展示；General 隐藏且不发送（服务端执行核无授权）。
// - 同一会话的研究对话与询问浮窗共享同一 execMode（单一状态源）。
// - 刷新/切会话由服务端偏好恢复；保存失败只本地缓存并如实提示。
// - 切 Ask 只约束后续新请求：已启动 run 继续按原授权执行，不暗中取消。
const execMode = ref('ask')
const execModeSaved = ref(true)

function sessionExecKey(id) {
  return `nexus_exec_mode_${id || 'default'}`
}

async function restoreExecMode(session) {
  if (!session || nexusDataSourceMode.value !== 'real') return
  try {
    const res = await getNexusSessionExecutionMode(session.id)
    const mode = res?.research_execution_mode
    if (mode === 'ask' || mode === 'auto') {
      execMode.value = mode
      execModeSaved.value = true
      try { localStorage.setItem(sessionExecKey(session.id), mode) } catch { /* 忽略 */ }
      return
    }
  } catch { /* 失败回落本地 */ }
  try {
    const cached = localStorage.getItem(sessionExecKey(session.id))
    execMode.value = cached === 'auto' ? 'auto' : 'ask'
  } catch { execMode.value = 'ask' }
  execModeSaved.value = false
}

/* 选择器说明：分段控件（与视图切换器同语汇），两项一句话差别见模板 title；
 * 模式真值只有 ask|auto（服务端校验，未知值 400）。 */

async function setExecMode(mode) {
  if (mode !== 'ask' && mode !== 'auto') return
  execMode.value = mode
  execModeSaved.value = true
  const sid = currentSession.value?.id
  if (!sid || nexusDataSourceMode.value !== 'real') return
  try {
    await saveNexusSessionExecutionMode(sid, mode)
    try { localStorage.setItem(sessionExecKey(sid), mode) } catch { /* 忽略 */ }
  } catch {
    // 偏好保存失败：只本地缓存并如实提示，不假称跨设备已保存。
    execModeSaved.value = false
    try { localStorage.setItem(sessionExecKey(sid), mode) } catch { /* 忽略 */ }
    showToast('执行模式偏好保存失败，仅本次会话有效', 'warning')
  }
}

// ── NX-A1 附件：会话级引用（服务端验主＋绑定，会话隔离）──
const ATTACHMENT_ACCEPT_EXTS = ['pdf', 'docx', 'jpg', 'jpeg', 'png', 'xlsx', 'pptx', 'ppt', 'doc']
const ATTACHMENT_MAX_BYTES = 20 * 1024 * 1024
const attachmentInput = ref(null)

function sessionAttachmentIds(s) {
  if (!s) return []
  if (!Array.isArray(s.attachmentIds)) s.attachmentIds = []
  return s.attachmentIds
}

function attachmentStateLabel(a) {
  if (a.status === 'uploading') return '上传中'
  if (a.status === 'ready') return '就绪'
  if (a.status === 'partial') return '部分解析'
  if (a.status === 'failed') return `失败·${a.error_code || a.error || '未知'}`
  if (a.status === 'expired') return '已过期'
  return a.status || '未知'
}

function triggerAttachmentPicker() {
  if (nexusDataSourceMode.value !== 'real') {
    showToast('演示模式不支持上传真实资料，请切换真实数据', 'error')
    return
  }
  attachmentInput.value?.click()
}

async function onAttachmentFileChange(event) {
  const files = Array.from(event?.target?.files || [])
  if (event?.target) event.target.value = ''
  if (!files.length || !currentSession.value) return
  const list = sessionAttachmentIds(currentSession.value)
  for (const file of files.slice(0, 5)) {
    const ext = (file.name.split('.').pop() || '').toLowerCase()
    if (!ATTACHMENT_ACCEPT_EXTS.includes(ext)) {
      showToast(`不支持的格式：${file.name}`, 'error')
      continue
    }
    if (file.size > ATTACHMENT_MAX_BYTES) {
      showToast(`文件过大（20MiB 上限）：${file.name}`, 'error')
      continue
    }
    const entry = {
      attachment_id: '', filename: file.name, ext,
      status: 'uploading', error_code: '', error_detail: '',
      size_bytes: file.size,
    }
    list.push(entry)
    persistSessions()
    try {
      const res = await uploadNexusAttachment(file, currentSession.value.id)
      Object.assign(entry, {
        attachment_id: res?.attachment_id || '',
        status: res?.status || 'unknown',
        error_code: res?.error_code || '',
        error_detail: res?.error_detail || '',
        size_bytes: res?.size_bytes ?? file.size,
      })
    } catch (err) {
      entry.status = 'failed'
      entry.error_code = err?.errorCode || ''
      entry.error_detail = err?.message || '上传失败'
    }
    persistSessions()
  }
}

async function removeSessionAttachment(entry) {
  const list = sessionAttachmentIds(currentSession.value)
  if (entry?.attachment_id) {
    try {
      await deleteNexusAttachment(entry.attachment_id)
    } catch {
      /* best-effort：服务端删失败也先清本地引用，避免卡死 */
    }
  }
  const i = list.indexOf(entry)
  if (i >= 0) list.splice(i, 1)
  persistSessions()
}

function readyAttachmentIds(session) {
  return sessionAttachmentIds(session)
    .filter((a) => a.attachment_id && (a.status === 'ready' || a.status === 'partial'))
    .map((a) => a.attachment_id)
}

// ── NX-E1 恢复：刷新/换设备找回原实验，只恢复轮询，不重新提交 ──
// 恢复去重标记用页面级 Set，绝不写进会话对象——否则会被 persistSessions
// 序列化进 localStorage，刷新后恢复逻辑被脏标记永久跳过（2026-09-06 线上验收）。
const _runsRestoredIds = new Set()

// F4（审查 2026-09-07）：终态作业恢复时的一次性详情补齐——拉取完整
// steps_result/日志历史填充 Console；Worker 无记录（重启丢内存，NX-E4
// 范畴）时保持清单快照。不触发自动报告，不重新提交。
async function backfillRestoredRunDetail(turn, jobId) {
  let record
  try {
    record = await getNexusReproJob(jobId)
  } catch {
    return
  }
  if (!record?.status || !turn?.reproRun) return
  applyReproRecord(turn, record)
  persistSessions()
}

// v6 实验名后端接线：按 job_id 重建命名投影（执行后新建 run 即时收敛用；
// 恢复路径复用已拉取的 runs 列表，不另发请求）。失败静默——本地回退名不受影响。
async function refreshBackendRunNames() {
  const session = currentSession.value
  if (!session || nexusDataSourceMode.value !== 'real') return
  let runs
  try {
    const res = await listNexusRuns(session.id)
    runs = Array.isArray(res?.items) ? res.items : []
  } catch {
    return
  }
  for (const run of runs) {
    // T5：自主 run 无 job_id，按 run_id 入 map（与 job 键不碰撞）。
    const mapKey = run?.job_id || run?.run_id
    if (!mapKey) continue
    backendRunNames.value[mapKey] = {
      display_title: run.display_title || '',
      title: run.title || '',
      run_number: run.run_number ?? null,
      version: run.version ?? 1,
      preset_display_name: run.preset_display_name || '',
      paper_title: run.paper_title || '',
      runId: run.run_id || '',
    }
    const existing = (session.turns || []).find((t) => t.reproRun?.job_id === run.job_id
      || (run.run_id && (t.reproRun?.run_id === run.run_id || t.reproRun?.runId === run.run_id)))
    if (existing) stampBackendRunName(existing.reproRun, backendRunNames.value[mapKey])
  }
}

async function restoreSessionRuns(session) {
  if (!session || _runsRestoredIds.has(session.id) || nexusDataSourceMode.value !== 'real') return
  let runs = []
  try {
    const res = await listNexusRuns(session.id)
    runs = Array.isArray(res?.items) ? res.items : []
  } catch {
    return // F4：拉取失败不进去重标记，下次恢复触发可重试
  }
  _runsRestoredIds.add(session.id)
  if (!Array.isArray(session.turns)) session.turns = []
  for (const run of runs) {
    const isAuto = (run?.tool === 'autonomous_experiment') || (!run?.job_id && !!run?.run_id)
    if (!run?.job_id && !isAuto) continue
    // v6 实验名后端接线（NX-LB1）：命名投影按 job_id/run_id 入 map，
    // sessionRuns 合并后显示（用户命名优先、否则 preset + 稳定序号）。
    const mapKey = run.job_id || run.run_id
    const backend = {
      display_title: run.display_title || '',
      title: run.title || '',
      run_number: run.run_number ?? null,
      version: run.version ?? 1,
      preset_display_name: run.preset_display_name || '',
      paper_title: run.paper_title || '',
      runId: run.run_id || '',
    }
    backendRunNames.value[mapKey] = backend
    const liveStatus = run.live?.status || run.status || 'unknown'
    const terminal = REPRO_TERMINAL_STATUSES.includes(liveStatus)
    const existing = session.turns.find((t) => (run.job_id && t.reproRun?.job_id === run.job_id)
      || (run.run_id && (t.reproRun?.run_id === run.run_id || t.reproRun?.runId === run.run_id)))
    if (existing) {
      // 本地 turn 状态落后于远端（如轮询断档期间作业已终态）→ 也恢复一次轮询：
      // 单次拉取即更新卡片并自行停止，不重复提交。
      if (!REPRO_TERMINAL_STATUSES.includes(existing.reproRun.status)
        && !['unknown', 'stale'].includes(liveStatus)) {
        if (run.job_id) startReproPolling(existing, run.job_id)
        else if (run.run_id) startRunDetailPolling(existing, run.run_id)
      }
      // 跨设备重命名一致：后端命名（含 title/display_title/序号/版本）向本地收敛。
      stampBackendRunName(existing.reproRun, backend)
      // T5：自主恢复带回 attempts/live（详情合并口径一致）。
      if (isAuto && run.live?.attempts) {
        existing.reproRun.attempts = run.live.attempts
        existing.reproRun.provider = 'autonomous'
        existing.reproRun.reconciling = run.live.status === 'reconciling'
      }
      continue
    }
    // 孤儿 run（换设备/刷新丢本地 turn）：建恢复 turn 展示，不重新提交；
    // reportRequested=true 抑制自动补报告（避免重复产物），用户可手动补领。
    // T5：自主孤儿 run 同样恢复（attempt 投影＋详情轮询，不重放执行）。
    const known = REPRO_RESTORE_KNOWN.includes(liveStatus)
    const turn = {
      question: `（已恢复）${run.preset_id || run.preset_display_name || '实验'}复现`,
      answer: '',
      toolEvents: [],
      papers: [],
      artifacts: [],
      reproductionPreset: null,
      tokenCount: null,
      durationMs: null,
      failure: '',
      restoredRun: true,
      createdAt: null,
      reproRun: {
        job_id: run.job_id || '',
        run_id: run.run_id || '',
        runId: run.run_id || '',
        provider: isAuto ? 'autonomous' : 'preset',
        status: known ? liveStatus : 'unknown',
        stages: [],
        attempts: isAuto && Array.isArray(run.live?.attempts) ? run.live.attempts : [],
        reconciling: isAuto && run.live?.status === 'reconciling',
        stageEvents: Array.isArray(run.live?.stage_events) ? run.live.stage_events : [],
        currentStep: run.live?.current_step ?? null,
        liveLog: '',
        startedAt: run.live?.started_at ?? null,
        finishedAt: run.live?.finished_at ?? null,
        expanded: false,
        cancelling: false,
        verdict: null,
        comparison: [],
        reportRequested: true,
        pollExhausted: false,
        code: run.live?.code || null,
        detail: run.live?.note || run.live?.detail || null,
        seedUsed: false,
        reportError: null,
        // 后端命名随行（恢复 turn 持久化后仍显示服务端名，不回退本地命名）。
        display_title: run.display_title || '',
        title: run.title || '',
        run_number: run.run_number ?? null,
        version: run.version ?? 1,
        preset_display_name: run.preset_display_name || '',
        paper_title: run.paper_title || '',
        runId: run.run_id || '',
      },
    }
    session.turns.push(turn)
    // F4：恢复时为所有已知作业补齐详情——queued/running/**cancelling** 持续
    // 轮询；终态（succeeded/failed/rejected/cancelled）一次性拉取历史步骤
    // 与日志，不因"清单只给状态"而停在空 Console。
    // T5：自主 run 走详情轮询（attempt 恢复），同样不重放执行。
    if (REPRO_RESTORE_NONTERMINAL.includes(liveStatus)) {
      if (run.job_id) startReproPolling(turn, run.job_id)
      else if (run.run_id) startRunDetailPolling(turn, run.run_id)
    } else if (known) {
      if (run.job_id) void backfillRestoredRunDetail(turn, run.job_id)
      else if (run.run_id) startRunDetailPolling(turn, run.run_id)
    }
  }
  persistSessions()
}

// ── NX-H1 计划恢复：首次进入/刷新拉取最近快照（checkpoint 真值） ──
// 成功后才进去重标记；失败不标记，下次进入/切换可重试（不永久置 restored）。
const _planRestoredSessions = new Set()

async function restoreSessionPlan(session) {
  if (!session || nexusDataSourceMode.value !== 'real') return
  if (_planRestoredSessions.has(session.id)) return
  if (!session.planState) session.planState = createPlanState()
  let payload
  try {
    payload = await getNexusPlan(session.id)
  } catch {
    return // 网络失败：不标记，可重试
  }
  _planRestoredSessions.add(session.id)
  if (applyRestoredPlan(session.planState, payload)) persistSessions()
}

function togglePinSession(s) {
  s.pinned = !s.pinned
  persistSessions()
}

function toggleSessionMenu(id) {
  openMenuSessionId.value = openMenuSessionId.value === id ? '' : id
}

function startRename(s) {
  openMenuSessionId.value = ''
  renamingSessionId.value = s.id
  renameDraft.value = s.title
}

function cancelRename() {
  renamingSessionId.value = ''
}

function saveRename(s) {
  if (renameDraft.value.trim()) {
    s.title = renameDraft.value.trim()
    persistSessions()
  }
  renamingSessionId.value = ''
}

function deleteSession(id) {
  if (confirmDeleteId.value !== id) {
    confirmDeleteId.value = id
    return
  }
  sessions.value = sessions.value.filter((s) => s.id !== id)
  confirmDeleteId.value = ''
  openMenuSessionId.value = ''
  persistSessions()
  if (activeSessionId.value === id) {
    if (sessions.value.length > 0) {
      activeSessionId.value = sessions.value[0].id
    } else {
      createNewSession()
    }
  }
}

/**
 * 导出会话为 Markdown（纯客户端，数据本就仅存本机，导出是真实可兑现的操作）。
 */
function exportSession(s) {
  openMenuSessionId.value = ''
  const modeLabel = s.mode === NEXUS_MODES.RESEARCH ? 'Nexus Research' : 'Nexus'
  const lines = [
    `# ${s.title}`,
    '',
    `- 模式：${modeLabel}`,
    `- 导出时间：${new Date().toLocaleString()}`,
    '- 说明：会话仅保存在本机浏览器，此文件为手动备份。',
    '',
  ]
  for (const t of s.turns || []) {
    lines.push('## 你', '', t.question, '')
    const calls = (t.toolEvents || []).filter((e) => e.kind === 'call').length
    if (calls) lines.push(`> 执行过程：${calls} 次工具调用`, '')
    if (t.answer) lines.push('## Nexus', '', t.answer, '')
    if (t.failure) lines.push(`> 回答失败：${t.failure}`, '')
  }
  const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `nexus-${(s.title || 'session').replace(/[\\/:*?"<>|]/g, '').slice(0, 40) || 'session'}.md`
  link.click()
  URL.revokeObjectURL(url)
}

// 会话搜索与分组（置顶 / 今天 / 最近 7 天 / 更早）
const filteredSessions = computed(() => {
  // real 模式下隐藏 demo 种子会话（仅展示层过滤，不落盘删除——切回演示模式要还在）。
  const pool =
    nexusDataSourceMode.value === 'real'
      ? sessions.value.filter((s) => !s.id.startsWith('demo-'))
      : sessions.value
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return pool
  return pool.filter((s) => s.title.toLowerCase().includes(q))
})

const groupedSessions = computed(() => {
  const now = Date.now()
  const oneDay = 24 * 3600 * 1000
  const sevenDays = 7 * oneDay

  const pinned = []
  const today = []
  const past7Days = []
  const earlier = []

  for (const s of filteredSessions.value) {
    if (s.pinned) {
      pinned.push(s)
      continue
    }
    const diff = now - s.updatedAt
    if (diff < oneDay) {
      today.push(s)
    } else if (diff < sevenDays) {
      past7Days.push(s)
    } else {
      earlier.push(s)
    }
  }

  return { pinned, today, past7Days, earlier }
})

const sessionGroups = computed(() => {
  const g = groupedSessions.value
  return [
    { key: 'pinned', label: '置顶会话', items: g.pinned },
    { key: 'today', label: '今天', items: g.today },
    { key: 'week', label: '最近 7 天', items: g.past7Days },
    { key: 'earlier', label: '更早', items: g.earlier },
  ].filter((gr) => gr.items.length)
})

function sessionSubLabel(s) {
  const mode = s.mode === NEXUS_MODES.RESEARCH ? '研究' : '通用'
  return `${mode} · ${formatSessionTime(s.updatedAt)}`
}

function formatSessionTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  const now = new Date()
  const hm = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
  if (d.toDateString() === now.toDateString()) return hm
  return `${d.getMonth() + 1}/${d.getDate()} ${hm}`
}

/**
 * 「本机资料」区：只统计真实存在于本地会话中的产物与复现记录，
 * 没有数据时整区不渲染（与右栏「有数据才出」同一原则）。
 */
/* 本机资料：real 模式以服务器产物列表为准（M3）；demo 模式统计本地会话。 */
const remoteArtifacts = ref([])

const localResources = computed(() => {
  if (nexusDataSourceMode.value === 'real') {
    return { artifacts: remoteArtifacts.value.length, repro: 0 }
  }
  let artifacts = 0
  let repro = 0
  for (const s of sessions.value) {
    if ((s.turns || []).some((t) => Array.isArray(t.artifacts) && t.artifacts.length)) artifacts += 1
    if ((s.turns || []).some((t) => t.reproStatus)) repro += 1
  }
  return { artifacts, repro }
})

const hasLocalResources = computed(
  () => localResources.value.artifacts > 0 || localResources.value.repro > 0
)

/* 本机资料行默认收起：没有数据时这一层不该占地方，有数据时也由用户决定展开。 */
const localPanelOpen = ref(false)

const localResourcesSummary = computed(() => {
  const { artifacts, repro } = localResources.value
  if (!artifacts && !repro) return '仅聊天记录'
  const parts = ['聊天记录']
  if (repro) parts.push(`复现 ${repro}`)
  if (artifacts) parts.push(`产物 ${artifacts}`)
  return parts.join(' · ')
})

function toggleLocalPanel() {
  if (!hasLocalResources.value) {
    showToast('这台设备还没有产物或复现记录')
    return
  }
  localPanelOpen.value = !localPanelOpen.value
}

function jumpToLocalResource(kind) {
  const matcher =
    kind === 'repro'
      ? (t) => t.reproStatus
      : (t) => Array.isArray(t.artifacts) && t.artifacts.length
  const target = [...sessions.value]
    .filter((s) => (s.turns || []).some(matcher))
    .sort((a, b) => b.updatedAt - a.updatedAt)[0]
  if (target) switchSession(target.id)
}

function formatBytes(n) {
  const size = Number(n) || 0
  if (size >= 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`
  if (size >= 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${size} B`
}

async function downloadArtifact(artifact) {
  if (!artifact?.artifact_id) return
  try {
    const blob = await downloadNexusArtifact(artifact.artifact_id)
    const ext = artifact.artifact_type === 'latex' ? 'tex' : 'md'
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${(artifact.title || 'artifact').replace(/[\\/:*?"<>|]/g, '_').slice(0, 40) || 'artifact'}.${ext}`
    link.click()
    URL.revokeObjectURL(url)
    showToast('已开始下载', 'success')
  } catch (err) {
    showToast(err?.message || '产物下载失败', 'error')
  }
}

// ── M4：复现作业受控轮询与确定性报告（B2/B3）；NX-E2/E3 Console 增量接线 ──
const REPRO_POLL_INTERVAL_MS = 5000
const REPRO_POLL_MAX = 200 // 5s × 200 ≈ 17min，覆盖 Worker 900s 硬截止 + 余量
const reproPollTimers = new Map()

// 复现作业的状态/阶段/耗时/日志等**只读投影**已抽到 ./reproShared.js ——
// 会话内 Console 与实验工作台（v6 主舞台）共用同一真相源，不允许两处各写一份。
// F4：恢复分类。注意声明顺序——模块级展开引用，放前面会触发 TDZ 使整个 chunk 崩掉（线上实测）。
const REPRO_RESTORE_NONTERMINAL = ['queued', 'running', 'cancelling']
const REPRO_RESTORE_KNOWN = [...REPRO_RESTORE_NONTERMINAL, ...REPRO_TERMINAL_STATUSES,
  // T5：reconciling 是自主 run 的已知展示态（执行器失联但运行未终止），继续轮询。
  'reconciling']

// NX-G2：审批状态文案（pending/approved/consumed/rejected/expired）。
const APPROVAL_STATUS_LABELS = {
  pending: '待批准',
  approved: '已批准',
  consumed: '已执行',
  rejected: '已拒绝',
  expired: '已过期',
}

function approvalStatusLabel(ap) {
  return APPROVAL_STATUS_LABELS[ap?.status] || ap?.status || '未知'
}

function stopReproPolling(jobId) {
  const timer = reproPollTimers.get(jobId)
  if (timer) {
    clearInterval(timer)
    reproPollTimers.delete(jobId)
  }
}

function stopAllReproPolling() {
  for (const id of reproPollTimers.keys()) stopReproPolling(id)
}

// Console 轮询与恢复共用的记录投影：把 Worker job 记录写入 turn.reproRun。
function applyReproRecord(turn, record) {
  if (!turn?.reproRun || !record) return
  turn.reproRun.status = record.status
  turn.reproRun.code = record.code || null
  turn.reproRun.detail = record.detail || null
  turn.reproRun.seedUsed = !!record.seed_used
  turn.reproRun.startedAt = record.started_at ?? null
  turn.reproRun.finishedAt = record.finished_at ?? null
  // NX-E2：真实边界 Stage 事件 / 当前步骤 / 运行中增量日志（代理已脱敏）。
  turn.reproRun.stageEvents = Array.isArray(record.stage_events) ? record.stage_events : []
  turn.reproRun.currentStep = record.current_step ?? null
  turn.reproRun.liveLog = record.live_log_tail || ''
  turn.reproRun.stages = (record.steps_result || []).map((s, i) => ({
    index: i + 1,
    command: s.command,
    exit_code: s.exit_code,
    timed_out: s.timed_out,
    duration_s: s.duration_s,
    log_tail: s.log_tail || ''
  }))
}

function startReproPolling(turn, jobId) {
  if (!jobId || reproPollTimers.has(jobId)) return
  let polls = 0
  const tick = async () => {
    polls += 1
    if (polls > REPRO_POLL_MAX) {
      stopReproPolling(jobId)
      if (turn?.reproRun) turn.reproRun.pollExhausted = true
      return
    }
    let record
    try {
      record = await getNexusReproJob(jobId)
    } catch (err) {
      // 单次失败不终止轮询（瞬时不可达）；轮询上限兜底
      return
    }
    if (!record || !turn?.reproRun) return
    applyReproRecord(turn, record)
    persistSessions()
    if (REPRO_TERMINAL_STATUSES.includes(record.status)) {
      stopReproPolling(jobId)
      if (record.status === 'succeeded') void requestReproReportFor(turn, jobId)
    }
  }
  reproPollTimers.set(jobId, setInterval(tick, REPRO_POLL_INTERVAL_MS))
  void tick()
}

// ── NX-E3 取消（投影辅助见 ./reproShared.js）──
// T5：聊天 Stop（abort SSE）绝不冒充取消；取消走独立 API。
// 自主 run 无 job_id → 按 run_id 经 Runtime 取消（回收确认后 cancelled）。

async function cancelReproRun(turn) {
  const run = turn?.reproRun
  if (!run || run.cancelling || !reproCancellable(run)) return
  const runId = run.runId || run.run_id || ''
  if (!run.job_id && !runId) return
  run.cancelling = true
  try {
    if (!run.job_id && runId) {
      const res = await cancelNexusRun(runId, activeSessionId.value || 'default')
      run.status = res?.status || 'cancelling'
      run.reconciling = false
      persistSessions()
      if (!res?.already_terminal) showToast('已发出取消，等待回收确认…', 'warning')
      return
    }
    const res = await cancelNexusReproJob(run.job_id)
    run.status = res?.status || 'cancelling'
    persistSessions()
    if (!res?.already_terminal) showToast('已发出取消，等待回收确认…', 'warning')
  } catch (err) {
    showToast(err?.message || '取消失败，运行可能已结束', 'error')
  } finally {
    run.cancelling = false
  }
}

// T5：自主 run 详情轮询（服务端快照恢复）：attempt 投影＋reconciling 语义。
// 与作业轮询共用 timers 表（键为 run_id），上限一致；终态停轮询。
function applyRunDetail(turn, detail) {
  if (!turn?.reproRun || !detail) return
  const run = turn.reproRun
  run.status = detail.status || run.status
  run.provider = 'autonomous'
  run.attempts = Array.isArray(detail.live?.attempts) ? detail.live.attempts : (run.attempts || [])
  run.attempt_no = detail.live?.attempt_no ?? detail.attempt_no ?? run.attempt_no ?? 0
  run.reconciling = (detail.live?.status === 'reconciling')
  run.detail = detail.live?.detail || detail.live?.note || run.detail || null
  // 自主运行中增量日志：取最后一条有日志尾的 attempt（只读呈现）。
  if (run.status === 'running' && Array.isArray(run.attempts)) {
    const tailed = run.attempts.filter((a) => a.log_tail)
    if (tailed.length) run.liveLog = tailed[tailed.length - 1].log_tail
  }
  stampBackendRunName(run, {
    display_title: detail.display_title || '',
    title: detail.title || '',
    run_number: detail.run_number ?? null,
    version: detail.version ?? 1,
    preset_display_name: detail.preset_display_name || '',
    paper_title: detail.paper_title || '',
    runId: detail.run_id || '',
  })
}

function startRunDetailPolling(turn, runId) {
  if (!runId || reproPollTimers.has(runId)) return
  let polls = 0
  const tick = async () => {
    polls += 1
    if (polls > REPRO_POLL_MAX) {
      stopReproPolling(runId)
      if (turn?.reproRun) turn.reproRun.pollExhausted = true
      return
    }
    let detail
    try {
      detail = await getNexusRunDetail(runId)
    } catch {
      return // 单次失败不终止轮询；上限兜底
    }
    if (!detail || !turn?.reproRun) return
    applyRunDetail(turn, detail)
    persistSessions()
    if (REPRO_TERMINAL_STATUSES.includes(detail.status)) {
      stopReproPolling(runId)
    }
  }
  reproPollTimers.set(runId, setInterval(tick, REPRO_POLL_INTERVAL_MS))
  void tick()
}

function toggleReproExpanded(turn) {
  const run = turn?.reproRun
  if (!run) return
  run.expanded = !run.expanded
  persistSessions()
}


// ── NX-G2 执行审批：决定 + 手工执行（UI 只提交决定，放行由服务端核销）──
async function decideApprovalFor(turn, decision) {
  const ap = turn?.approval
  if (!ap?.approval_id || ap.deciding || ap.executing) return
  // 已批准后重复点击"批准"：直接走执行（服务端 decide 幂等，但 consumed 票据
  // 会 409；前端短路更符合"批准一次、执行一次"的直觉）。
  if (decision === 'approved' && ap.status === 'approved') {
    await executeApprovalFor(turn)
    return
  }
  if (ap.status !== 'pending') return
  ap.deciding = true
  ap.error = null
  try {
    const res = await decideNexusApproval(ap.approval_id, decision)
    const next = res?.approval || {}
    if (next?.status) ap.status = next.status
    if (decision === 'rejected' && ap.status === 'pending') ap.status = 'rejected'
    persistSessions()
    if (decision === 'approved' && ap.status === 'approved') {
      await executeApprovalFor(turn)
    }
  } catch (err) {
    ap.error = err?.errorCode
      ? `${err.errorCode}：${err?.message || '审批失败，未执行任何操作'}`
      : (err?.message || '审批失败，未执行任何操作')
  } finally {
    ap.deciding = false
  }
}

async function executeApprovalFor(turn) {
  const ap = turn?.approval
  if (!ap?.approval_id || ap.executing) return
  ap.executing = true
  ap.error = null
  try {
    // T5：透传本次执行门（Research+Auto 才放行；Ask 由服务端 403）。
    const res = await executeApprovedRepro(ap.approval_id, activeSessionId.value || 'default', {
      mode: activeMode.value,
      researchExecutionMode: isResearchMode.value ? execMode.value : null,
    })
    // T5 自主执行：返回 run_id（无 job），建 run 引用条并按详情轮询恢复。
    const runId = res?.run_id
    if (runId && !res?.job && !turn.reproRun) {
      turn.reproRun = {
        job_id: '',
        run_id: runId,
        runId,
        status: res?.status || 'running',
        provider: 'autonomous',
        stages: [],
        attempts: [],
        stageEvents: [],
        currentStep: null,
        liveLog: '',
        startedAt: null,
        finishedAt: null,
        expanded: true,
        cancelling: false,
        reconciling: false,
        verdict: null,
        comparison: [],
        reportRequested: true,
        pollExhausted: false,
        code: null,
        detail: null,
        seedUsed: false,
        reportError: null
      }
      persistSessions()
      startRunDetailPolling(turn, runId)
      void refreshBackendRunNames()
      return
    }
    const job = res?.job
    if (job?.job_id && !turn.reproRun) {
      turn.reproRun = {
        job_id: job.job_id,
        status: job.status || 'queued',
        stages: [],
        stageEvents: [],
        currentStep: null,
        liveLog: '',
        startedAt: null,
        finishedAt: null,
        expanded: true,
        cancelling: false,
        verdict: null,
        comparison: [],
        reportRequested: false,
        pollExhausted: false,
        code: null,
        detail: null,
        seedUsed: false,
        reportError: null
      }
      persistSessions()
      startReproPolling(turn, job.job_id)
      // 本轮新建的 run 也收敛到后端命名（不等下次刷新；失败静默，保持本地回退名）。
      void refreshBackendRunNames()
    } else if (!job?.job_id) {
      ap.error = res?.detail || res?.code || '执行未返回作业，未启动实验'
    }
  } catch (err) {
    ap.error = err?.errorCode
      ? `${err.errorCode}：${err?.message || '执行失败'}`
      : (err?.message || '执行失败')
  } finally {
    ap.executing = false
  }
}

// T5：Ask 下确认卡的合并操作——一次点击完成"切换 Auto＋本次批准＋执行"，
// 不弹第二个模式确认。任一步失败如实报错，不伪装已切换/已批准。
async function approveWithAuto(turn) {
  const ap = turn?.approval
  if (!ap?.approval_id || ap.deciding || ap.executing) return
  ap.deciding = true
  ap.error = null
  try {
    await setExecMode('auto')
    const res = await decideNexusApproval(ap.approval_id, 'approved')
    const next = res?.approval || {}
    if (next?.status) ap.status = next.status
    if (ap.status !== 'approved') {
      ap.error = '批准未成功，未切换执行'
      return
    }
    persistSessions()
    await executeApprovalFor(turn)
  } catch (err) {
    ap.error = err?.errorCode
      ? `${err.errorCode}：${err?.message || '切换并批准失败，未执行任何操作'}`
      : (err?.message || '切换并批准失败，未执行任何操作')
  } finally {
    ap.deciding = false
  }
}

// T5：本会话活跃 run（切换 Ask 后继续按原授权执行，不暗中取消）。
const activeRuns = computed(() => sessionRuns.value.filter((r) =>
  ['queued', 'running', 'cancelling'].includes(r.run.status)))
const hasActiveRuns = computed(() => activeRuns.value.length > 0)

// NX-E1：恢复 turn 手动补领报告（自动补会重复产物；手动一次由用户控制）。
async function claimRestoredReport(turn) {
  if (!turn?.reproRun) return
  turn.reproRun.reportRequested = false
  await requestReproReportFor(turn, turn.reproRun.job_id)
}

async function requestReproReportFor(turn, jobId) {
  if (!turn?.reproRun || turn.reproRun.reportRequested) return
  turn.reproRun.reportRequested = true
  try {
    const res = await requestReproReport(jobId)
    turn.reproRun.verdict = res?.verdict ?? null
    turn.reproRun.comparison = Array.isArray(res?.comparison) ? res.comparison : []
    for (const a of res?.artifacts || []) {
      if (a?.artifact_id && !(turn.artifacts || []).some((x) => x.artifact_id === a.artifact_id)) {
        turn.artifacts = [...(turn.artifacts || []), a]
      }
    }
    persistSessions()
    showToast(`复现报告已生成：${turn.reproRun.verdict || '完成'}`, 'success')
  } catch (err) {
    turn.reproRun.reportError = err?.message || '报告生成失败'
    showToast(turn.reproRun.reportError, 'error')
  }
}

// ── 3. Mode 切换与上下文 ──
const modeDropdownOpen = ref(false)
const pendingOpen = ref(false)
const dsOpen = ref(false)
const coursePickerOpen = ref(false)

// 初值一律为 null：在没有真实数据之前，宁可显示"—"，也不预置一个看起来正常的数字。
const contextOverview = ref({
  source: 'demo',
  disciplineKb: { nodeCount: null, relationCount: null, coursesCount: null },
  coursesList: [],
  materialsCount: null
})

async function loadContextData() {
  contextOverview.value = await getContextOverview({
    courseId: currentSession.value?.courseId
  })
}

function switchMode(key) {
  if (streaming.value) return
  activeMode.value = key
  modeDropdownOpen.value = false
}

/**
 * 能力三态渲染：一律从 nexusCapabilities.js 读取，禁止模板硬编码。
 * NX-G3：首屏 Chips 消费 effective（manifest ∩ mode ∩ 依赖健康），不再只看
 * 静态 ready；演示数据源无真实 health 时退回清单原文。
 */
const effectiveCapabilities = computed(() =>
  resolveEffectiveCapabilities({
    mode: activeMode.value,
    health: health.value,
    trustManifest: nexusDataSourceMode.value === 'demo',
  })
)
const readyCapabilities = computed(() =>
  effectiveCapabilities.value.filter((c) => c.effective === EFFECTIVE_STATE.READY)
)

function chipLabel(cap) {
  return cap.id === 'web_search' ? 'Web 搜索 · 自动' : cap.label
}

function capHint(id) {
  const cap = effectiveCapabilities.value.find((c) => c.id === id)
  if (!cap) return ''
  // NX-G3：effective 原因优先（如"依赖不可达"），回退到清单原文。
  if (cap.effectiveNote) return cap.effectiveNote
  if (cap.state === CAPABILITY_STATE.WIRED) return cap.wiredHint || ''
  if (cap.state === CAPABILITY_STATE.UNWIRED) return cap.unwiredHint || ''
  return ''
}

/* 状态文案全局统一为三种（UX 评审 P2-8）：
 *   已生效        = ready，工具真的在回答链路上
 *   已连接·未生效 = wired，数据源已接通但还没注入回答
 *   未建立        = unwired，能力根本不存在
 * 此前出现过「已接通 / 数据就绪 · 未注入回答 / 数据就绪」四种变体，
 * 同一状态两套说法，用户无法判断差别。改文案只动展示层，
 * nexusCapabilities.js 的数据结构不变。 */
function capStateText(cap) {
  // NX-G3：effective 优先——依赖不可达/状态未知时不沿用永久 Ready 文案。
  if (cap.effective === EFFECTIVE_STATE.DEGRADED) return '部分可用'
  if (cap.effective === EFFECTIVE_STATE.UNKNOWN) return '状态未知'
  if (cap.state === CAPABILITY_STATE.READY) return '已生效'
  if (cap.state === CAPABILITY_STATE.WIRED) return '已连接 · 未生效'
  return '未建立'
}

function capStateTagText(cap) {
  if (cap.effective === EFFECTIVE_STATE.DEGRADED) return '部分可用'
  if (cap.effective === EFFECTIVE_STATE.UNKNOWN) return '状态未知'
  if (cap.state === CAPABILITY_STATE.READY) return '已生效'
  if (cap.state === CAPABILITY_STATE.WIRED) return '已连接 · 未生效'
  return '未建立'
}

/* ── 启动页右侧「本会话上下文」：只列本轮真正生效（ready 态）的能力 ──
 * wired/unwired 的开发中说明已按 2026-09-08 决定从界面移除：
 * 未接入的能力不显示行（缺席 ≠ 谎称已生效），降级/未知仍如实标出。
 * 能力真相仍在 nexusCapabilities.js，这里只做展示映射。 */
const CONTEXT_CAP_ROWS = [
  { id: 'web_search', k: 'Web 检索' },
  { id: 'cs_knowledge', k: 'CS 知识库' },
  { id: 'course_materials', k: '课程资料' }
]

function capTagClass(cap) {
  if (!cap) return 'no'
  if (cap.effective === EFFECTIVE_STATE.READY) return 'ok'
  if (cap.effective === EFFECTIVE_STATE.DEGRADED || cap.effective === EFFECTIVE_STATE.UNKNOWN) return 'half'
  if (cap.state === CAPABILITY_STATE.WIRED) return 'half'
  return 'no'
}

const contextRows = computed(() =>
  CONTEXT_CAP_ROWS
    .map((r) => ({ r, cap: effectiveCapabilities.value.find((c) => c.id === r.id) }))
    .filter(({ cap }) => cap && cap.state === CAPABILITY_STATE.READY)
    .map(({ r, cap }) => ({
      k: r.k,
      v: capStateTagText(cap),
      cls: capTagClass(cap),
      hint: capHint(r.id)
    }))
)

const capIconMap = {
  FileText,
  Database,
  Globe,
  BookMarked,
  FlaskConical,
  Paperclip,
  Layers,
  Wrench,
}

/** 复现执行是否真的可执行（当前恒 false，直到 Repro Worker 落地）。 */
const reproExecutable = computed(() => isReproductionExecutable())

/**
 * 信息源面板的真实数据：从本会话的 tool_result 事件里现提取，不写死任何来源描述。
 * M1-B4 起 tool_result 携带结构化 items（条目边界截断），优先消费 items；
 * 旧会话（仅有 content JSON）回退到解析 content，仍解析失败计入 unparsable 哨兵。
 */
const sessionSources = computed(() => {
  const turns = currentSession.value?.turns || []
  const web = []
  const papers = []
  const course = []
  const csKb = []
  let unparsable = 0

  const itemsOf = (evt) => {
    if (Array.isArray(evt?.items)) return evt.items
    try {
      const payload = JSON.parse(evt?.content)
      return Array.isArray(payload?.items) ? payload.items : null
    } catch {
      return null
    }
  }

  for (const t of turns) {
    for (const p of t.papers || []) {
      if (p?.title) papers.push(p)
    }
    for (const evt of t.toolEvents || []) {
      if (evt?.kind !== 'result') continue
      if (evt?.name === 'web_search') {
        const items = itemsOf(evt)
        if (items === null) {
          unparsable += 1
          continue
        }
        for (const item of items) {
          if (item?.title && item?.url) web.push(item)
        }
      } else if (evt?.name === 'search_course_materials') {
        for (const item of itemsOf(evt) || []) {
          if (!item?.text) continue
          course.push({
            text: item.text,
            resource: item.resource_id || '',
            page: item.page ?? null,
            node: item.node_key || ''
          })
        }
      } else if (evt?.name === 'search_cs_knowledge') {
        for (const item of itemsOf(evt) || []) {
          // CR5：语料块（title/reference_id）与精编概念（name）分开收录，
          // 回源身份保留，展示截断不删除引用入口。
          if (item?.result_type === 'corpus_chunk' || item?.chunk_id) {
            if (!item?.title) continue
            csKb.push({
              name: item.title,
              source: item.source_kind || '',
              course: '',
              reference_id: item.reference_id || '',
              chunk_id: item.chunk_id || '',
              license: item.license || '',
            })
            continue
          }
          if (!item?.name) continue
          csKb.push({ name: item.name, source: item.source || '', course: item.course || '' })
        }
      }
    }
  }
  return { web, papers, course, csKb, unparsable }
})

const sourcesTotal = computed(
  () =>
    sessionSources.value.web.length +
    sessionSources.value.papers.length +
    sessionSources.value.course.length +
    sessionSources.value.csKb.length
)

function selectCourse(course) {
  if (!currentSession.value) return
  if (course === null) {
    currentSession.value.courseId = null
    currentSession.value.courseName = null
  } else {
    currentSession.value.courseId = course.course_id
    currentSession.value.courseName = course.title
  }
  persistSessions()
  coursePickerOpen.value = false
  loadContextData()
}

function roleLabel(role) {
  const map = { teacher: '教师', student: '学生', admin: '管理员' }
  return map[role] || role || '—'
}

// ── 4. 对话、流式与消息流 ──
const draft = ref('')
const streaming = ref(false)
const scrollArea = ref(null)
const expandedTools = ref(new Set())
const activeDetailTab = ref('context') // 'context' | 'activity' | 'sources'
let abortController = null

/* ── 右栏：48px 图标轨 + 320px overlay 抽屉（UX 评审 P0-1）──
 * 抽屉开合按设备持久化（page-design.md §3.4），默认收起以还回主工作区 272px。
 * 收起时新到达的执行记录用「未读」计数在图标轨上提示，过程信息不丢失可见性。 */
const detailDrawerOpen = ref(localStorage.getItem('nexus_detail_open') === 'true')
const unseenActivity = ref(0)

const detailTabs = computed(() => [
  { id: 'context', label: '上下文', hint: '当前会话引用了什么', icon: Layers, badge: 0, unseen: 0 },
  {
    id: 'activity',
    label: '执行轨迹',
    hint: '工具调用与返回',
    icon: Activity,
    badge: 0,
    unseen: unseenActivity.value
  },
  { id: 'sources', label: '信息源', hint: '命中的论文与网页', icon: Link2, badge: sourcesTotal.value, unseen: 0 }
])

const activeDetailMeta = computed(
  () => detailTabs.value.find((t) => t.id === activeDetailTab.value) || detailTabs.value[0]
)

function selectDetailTab(id) {
  if (activeDetailTab.value === id && detailDrawerOpen.value) {
    closeDetailDrawer()
    return
  }
  activeDetailTab.value = id
  if (id === 'activity') unseenActivity.value = 0
  detailDrawerOpen.value = true
  localStorage.setItem('nexus_detail_open', 'true')
}

function closeDetailDrawer() {
  detailDrawerOpen.value = false
  localStorage.setItem('nexus_detail_open', 'false')
}

/* 抽屉内 tab：只切面板，不因重复点击而收起（与图标轨上的行为区分开） */
function selectDetailTabInDrawer(id) {
  activeDetailTab.value = id
  if (id === 'activity') unseenActivity.value = 0
  detailDrawerOpen.value = true
}

function noteActivityArrived() {
  if (!detailDrawerOpen.value || activeDetailTab.value !== 'activity') {
    unseenActivity.value += 1
  }
}

// ── 模型选择（模型网关 P0）：选项唯一来源 = /health models 清单
// （服务端 allowlist 投影）；选择随请求透传，服务端强制校验。
// localStorage 只记偏好，不做授权；清单外 id 发出去会被 400 打回。
const selectedModel = ref(localStorage.getItem('nexus_model') || '')
const availableModels = computed(() => health.value?.models?.available || [])
const effectiveModel = computed(() => {
  const list = availableModels.value
  if (!list.length) return ''
  if (list.some((m) => m.id === selectedModel.value)) return selectedModel.value
  return health.value?.models?.default || list[0].id
})
function selectModel(id) {
  selectedModel.value = id || ''
  if (id) localStorage.setItem('nexus_model', id)
  else localStorage.removeItem('nexus_model')
}

// 健康状态
const health = ref(null)
const healthError = ref('')

async function checkHealth() {
  if (nexusDataSourceMode.value === 'demo') {
    health.value = {
      status: 'ok',
      llm_configured: true,
      searxng_configured: true,
      ddgs_enabled: true,
      repro_worker_configured: false,
    }
    healthError.value = ''
    return
  }
  try {
    health.value = await getNexusHealth()
    healthError.value = ''
  } catch (err) {
    health.value = null
    healthError.value = err?.errorCode || err?.message || 'Nexus 运行时不可达'
  }
}

watch(nexusDataSourceMode, (mode) => {
  checkHealth()
  if (mode === 'real') {
    refreshRemoteSessions()
    // 当前激活的是 demo 种子会话时，切到 real 列表的第一个会话，避免演示内容
    // 在"真实"徽标下继续展示。
    if (activeSessionId.value.startsWith('demo-')) {
      const first = sessions.value.find((s) => !s.id.startsWith('demo-'))
      if (first) switchSession(first.id)
    }
  }
})

async function scrollToBottom() {
  await nextTick()
  if (scrollArea.value) {
    scrollArea.value.scrollTop = scrollArea.value.scrollHeight
  }
}

/* 流式节流滚动：token 到达只排队一个 rAF，且仅用户停留在底部附近时跟随；
 * 用户上滑阅读历史时不再被拽回底部。替代 handleEvent 里逐 token 的 nextTick 强置滚动。 */
let scrollRafQueued = false
function queueScroll() {
  if (scrollRafQueued) return
  scrollRafQueued = true
  requestAnimationFrame(() => {
    scrollRafQueued = false
    const el = scrollArea.value
    if (!el) return
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 140
    if (nearBottom) el.scrollTop = el.scrollHeight
  })
}

function toolKey(turnIdx, evtIdx) {
  return `${turnIdx}:${evtIdx}`
}

function isToolExpanded(turnIdx, evtIdx) {
  return expandedTools.value.has(toolKey(turnIdx, evtIdx))
}

function toggleTool(turnIdx, evtIdx) {
  const k = toolKey(turnIdx, evtIdx)
  const next = new Set(expandedTools.value)
  if (next.has(k)) next.delete(k)
  else next.add(k)
  expandedTools.value = next
}

// 格式化展示工具名称
function formatToolDisplayName(name) {
  const map = {
    web_search: '网页检索',
    search_arxiv_papers: 'arXiv 论文检索',
    plan_reproduction: '复现规划',
    run_reproduction: '复现执行',
    read_file: '读取文件',
    write_file: '写入文件',
    task: '子任务代理'
  }
  return map[name] || name
}

const TOOL_RUNNING_LABEL = {
  web_search: '正在检索网页',
  search_arxiv_papers: '正在检索 arXiv 论文',
  plan_reproduction: '正在生成复现计划',
  run_reproduction: '正在执行复现',
}

/** 运行状态行：流式期间始终可见（规格 §54.3，不允许"AI 没反应"）。 */
const streamingTurn = ref(null)
const streamElapsed = ref('00:00')
let elapsedTimer = null
let streamStartedAt = 0

const liveStatusText = computed(() => {
  const turn = streamingTurn.value
  if (!turn) return '正在思考…'
  const events = turn.toolEvents || []
  if (!events.length) return '正在思考…'
  const last = events[events.length - 1]
  if (last.kind === 'call') {
    return `${TOOL_RUNNING_LABEL[last.name] || `正在调用 ${formatToolDisplayName(last.name)}`}…`
  }
  return '正在整理结果…'
})

function formatElapsed(ms) {
  const total = Math.max(0, Math.floor(ms / 1000))
  const mm = String(Math.floor(total / 60)).padStart(2, '0')
  const ss = String(total % 60).padStart(2, '0')
  return `${mm}:${ss}`
}

function failedToolCount(turn) {
  return (turn.toolEvents || []).filter((e) => e.kind === 'result' && e.status === 'error').length
}

function processSummaryLabel(turn) {
  const calls = (turn.toolEvents || []).filter((e) => e.kind === 'call').length
  const dur = turn.durationMs ? ` · ${(turn.durationMs / 1000).toFixed(1)}s` : ''
  const failed = failedToolCount(turn)
  const failedText = failed ? ` · ${failed} 次失败` : ''
  return `执行过程 · ${calls} 次工具调用${failedText}${dur}`
}

/* Markdown 节流渲染（防"突进式"输出的核心）：
 * renderContent（marked + highlight.js + KaTeX + DOMPurify）跑在全量答案上，
 * 每 token 全量跑一次必然"冻住—突进"。流式 turn 最多 200ms 重解析一次，
 * 其余重渲染命中缓存；缓存引用不变时 v-html 不写 DOM，从根本上消掉逐 token
 * 的 DOM 替换。WeakMap 避免缓存污染 localStorage 持久化。 */
const renderCache = new WeakMap()
function renderedAnswer(turn) {
  const answer = turn.answer || ''
  const cached = renderCache.get(turn)
  if (cached && cached.len === answer.length) return cached.html
  const isLive = streaming.value && turn === streamingTurn.value
  const now =
    typeof performance !== 'undefined' && performance.now ? performance.now() : Date.now()
  if (!isLive || now - (cached?.at || 0) >= 200) {
    try {
      const html = renderContent(answer)
      renderCache.set(turn, { html, len: answer.length, at: now })
      return html
    } catch {
      return cached?.html || ''
    }
  }
  return cached?.html || ''
}

function handleEvent(turn, { event, data }, session = null) {
  if (event === 'plan') {
    // NX-H1：计划快照（真实 state 投影）。会话级状态——经 planState 状态机
    // 去重/排序，旧 revision 忽略；session 缺省时（历史调用方）不消费。
    const target = session || currentSession.value
    if (target) {
      if (!target.planState) target.planState = createPlanState()
      if (applyPlanEvent(target.planState, data)) persistSessions()
    }
  } else if (event === 'token') {
    turn.answer += data?.content ?? ''
  } else if (event === 'tool_call') {
    turn.toolEvents.push({
      kind: 'call',
      name: data?.name || '未知工具',
      args: data?.args,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    })
    noteActivityArrived()
  } else if (event === 'tool_result') {
    turn.toolEvents.push({
      kind: 'result',
      name: data?.name || '未知工具',
      status: data?.status || 'success',
      content: data?.content ?? '',
      items: Array.isArray(data?.items) ? data.items : null,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    })

    // 解析结构化论文卡片
    if (data?.name === 'search_arxiv_papers' && data?.content) {
      try {
        const parsed = JSON.parse(data.content)
        if (parsed.items && Array.isArray(parsed.items)) {
          turn.papers = parsed.items
        }
      } catch (e) {
        // truncated json fallback（运行时缺陷 D2 哨兵）
      }
    }

    // NX-R1a：论文证据卡（上传 PDF 全文薄链；搜索候选不进此卡）
    if (data?.name === 'collect_paper_evidence' && data?.status !== 'error') {
      let evidences = Array.isArray(data?.items) ? data.items : []
      if (!evidences.length && data?.content) {
        try {
          const parsed = JSON.parse(data.content)
          if (Array.isArray(parsed?.evidences)) evidences = parsed.evidences
        } catch (e) {
          // 结构化兜底失败：证据卡暂缺，但结果本身如实留存在轨迹里
        }
      }
      if (evidences.length) {
        turn.evidences = evidences
        persistSessions()
      }
    }

    // 解析复现规划卡片
    if (data?.name === 'plan_reproduction' && data?.content) {
      try {
        const parsed = JSON.parse(data.content)
        if (parsed.plan) {
          turn.reproductionPreset = parsed.plan
        }
      } catch (e) {
        // pass
      }
    }

    // 解析复现执行提交（M4-B2）：job 提交成功 → 受控轮询状态
    // NX-G2：approval_required → 审批卡（暂停，不执行）；approval_denied → 如实失败。
    if (data?.name === 'run_reproduction' && data?.status !== 'error') {
      let payload = null
      if (data?.content) {
        try {
          payload = JSON.parse(data.content)
        } catch (e) {
          payload = null
        }
      }
      if (payload?.status === 'approval_required' && payload?.approval?.approval_id) {
        const incoming = payload.approval.approval_id
        if (!turn.approval || turn.approval.approval_id !== incoming) {
          turn.approval = {
            ...payload.approval,
            deciding: false,
            executing: false,
            error: null,
          }
          persistSessions()
        }
      } else if (payload?.status === 'approval_denied') {
        turn.failure = payload?.code
          ? `${payload.code}：${payload?.detail || '复现未获批准，未执行'}`
          : '复现未获批准，未执行'
      } else {
        let job = Array.isArray(data?.items) && data.items[0] ? data.items[0] : null
        if (!job && payload?.job) job = payload.job
      if (job?.job_id && job.status !== 'rejected' && !turn.reproRun) {
        turn.reproRun = {
          job_id: job.job_id,
          status: job.status || 'queued',
          stages: [],
          stageEvents: [],
          currentStep: null,
          liveLog: '',
          startedAt: null,
          finishedAt: null,
          expanded: true,
          cancelling: false,
          verdict: null,
          comparison: [],
          reportRequested: false,
          pollExhausted: false,
          code: null,
          detail: null,
          seedUsed: false,
          reportError: null
        }
        persistSessions()
        startReproPolling(turn, job.job_id)
      }
      }
    }

    // M3：write_artifact 成功 → turn.artifacts（消息流产物卡 + 本机资料计数）
    // NX-R1a：write_research_report 同样产出 Markdown Artifact，共用产物卡。
    if ((data?.name === 'write_artifact' || data?.name === 'write_research_report') && data?.status !== 'error') {
      let artifact = Array.isArray(data?.items) && data.items[0] ? data.items[0] : null
      if (!artifact && data?.content) {
        try {
          const parsed = JSON.parse(data.content)
          if (parsed?.artifact) artifact = parsed.artifact
        } catch (e) {
          // 结构化 items 兜底解析失败：产物卡暂缺，但结果本身如实留存在轨迹里
        }
      }
      if (artifact?.artifact_id && !(turn.artifacts || []).some((a) => a.artifact_id === artifact.artifact_id)) {
        turn.artifacts = [...(turn.artifacts || []), artifact]
        persistSessions()
      }
    }
  } else if (event === 'error') {
    // M1-B3（D5）：流内错误以稳定错误码呈现，不再停在"进行中"。
    // 服务端保证 done/error 互斥；本分支后流即关闭，runTurn 的 finally 复位状态。
    turn.failure = data?.code ? `${data.code}：${data?.message || '执行失败'}` : (data?.message || '执行失败')
  } else if (event === 'done') {
    turn.tokenCount = data?.token_count ?? null
  }
  queueScroll()
}

async function send() {
  const msg = draft.value.trim()
  if (!msg || streaming.value || !currentSession.value) return
  // NX-A1：有附件仍在上传时拦截发送（避免引用不完整），提示等完成。
  if (sessionAttachmentIds(currentSession.value).some((a) => a.status === 'uploading')) {
    showToast('附件上传中，请稍候再发送', 'error')
    return
  }
  draft.value = ''
  await runTurn(msg)
}

/** 重新生成：同一问题追加一个新 turn（保留历史证据链，不覆盖原回答）。 */
function retryTurn(tIdx) {
  if (streaming.value || !currentSession.value) return
  const q = currentSession.value.turns?.[tIdx]?.question
  if (!q || !q.trim()) return
  runTurn(q)
}

/** runTurn 是 send / retry 的共享执行体：建 turn → 流式 → 落盘。 */
async function runTurn(message) {
  if (!currentSession.value) return

  const turn = {
    question: message,
    answer: '',
    toolEvents: [],
    papers: [],
    evidences: [],
    artifacts: [],
    reproductionPreset: null,
    tokenCount: null,
    durationMs: null,
    failure: '',
    createdAt: Date.now()
  }

  currentSession.value.turns.push(turn)
  currentSession.value.updatedAt = Date.now()
  if (currentSession.value.turns?.length === 1 && currentSession.value.title.startsWith('新建')) {
    currentSession.value.title = message.slice(0, 20) + (message.length > 20 ? '...' : '')
  }
  persistSessions()

  streaming.value = true
  streamingTurn.value = turn
  streamStartedAt = Date.now()
  streamElapsed.value = formatElapsed(0)
  if (elapsedTimer) clearInterval(elapsedTimer)
  elapsedTimer = setInterval(() => {
    streamElapsed.value = formatElapsed(Date.now() - streamStartedAt)
  }, 1000)
  abortController = new AbortController()
  /* 流式开始自动切到「执行轨迹」，来源到达后信息源图标会出现计数角标。
   * 抽屉不强制展开——尊重用户上一次的开合选择；收起时用未读计数提示。 */
  activeDetailTab.value = 'activity'
  unseenActivity.value = 0
  scrollToBottom()

  try {
    await dispatchNexusMessage({
      // 修复：原先误写 message: msg（msg 不在作用域，真实链路必抛
      // ReferenceError）；与模型透传同批修正。
      message,
      sessionId: currentSession.value.id,
      mode: activeMode.value,
      // T5 Ask/Auto：Research 显式发送本次 effective 值；General 不传。
      researchExecutionMode: isResearchMode.value ? execMode.value : null,
      courseId: currentSession.value.courseId ?? null,
      model: effectiveModel.value || null,
      // NX-A1：仅发送就绪附件 id；绑定与验主在服务端完成。
      attachmentIds: readyAttachmentIds(currentSession.value),
      signal: abortController.signal,
      onEvent: (evt) => handleEvent(turn, evt, currentSession.value),
    })
  } catch (err) {
    if (err?.name === 'AbortError') {
      turn.failure = '已停止回答'
    } else {
      const code = err?.errorCode ? `${err.errorCode}：` : ''
      turn.failure = `${code}${err?.message || '请求失败'}`
    }
  } finally {
    if (elapsedTimer) {
      clearInterval(elapsedTimer)
      elapsedTimer = null
    }
    turn.durationMs = Date.now() - streamStartedAt
    streaming.value = false
    streamingTurn.value = null
    abortController = null
    persistSessions()
    scrollToBottom()
  }
}

function stop() {
  if (abortController) abortController.abort()
}

/* 回答操作条：复制（剪贴板）与重试（追加新 turn）真实可用；
 * 点赞/点踩暂无评价服务，点击只给轻提示，不伪造"已反馈"。 */
async function copyAnswer(turn) {
  const text = turn.answer || ''
  if (!text) return
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      fallbackCopyText(text)
    }
    showToast('已复制回答', 'success')
  } catch {
    showToast('复制失败', 'error')
  }
}

function fallbackCopyText(text) {
  const ta = document.createElement('textarea')
  ta.value = text
  ta.style.position = 'fixed'
  ta.style.opacity = '0'
  document.body.appendChild(ta)
  ta.select()
  try {
    document.execCommand('copy')
  } finally {
    document.body.removeChild(ta)
  }
}

// 快捷操作填入输入框
function applySuggestion(text) {
  draft.value = text
  send()
}

// ── 5. 复现二次确认弹窗 ──
const reproModalOpen = ref(false)
const selectedReproPreset = ref(null)

function openReproductionModal(preset) {
  selectedReproPreset.value = preset
  reproModalOpen.value = true
}

/**
 * 复现审批后的动作。
 *
 * 这里守一条硬线：确认不等于执行。Repro Worker 尚未接入时，
 * 必须落一张明确写着 REPRO_WORKER_UNAVAILABLE 的状态卡，
 * 而不是把确认文案塞回输入框重发一遍假装开始了。
 */
function confirmStartReproduction() {
  reproModalOpen.value = false
  // NX-G1：General 模式结构性不绑定 run_reproduction，确认消息发出去也只会
  // 被模型拒绝——在此直接拦截，给出确定恢复动作（切 Research）。
  if (activeMode.value !== NEXUS_MODES.RESEARCH) {
    showToast('复现执行仅在 Nexus Research 模式可用', 'error')
    return
  }
  const preset = selectedReproPreset.value
  const name = preset?.preset_id || 'nanoGPT'

  if (!reproExecutable.value) {
    pushReproUnavailableTurn(name, preset)
    return
  }

  draft.value = `确认执行 ${name} 实验复现`
  send()
}

function pushReproUnavailableTurn(name, preset) {
  const s = currentSession.value
  if (!s) return
  if (!Array.isArray(s.turns)) s.turns = []

  s.turns.push({
    question: `（已通过安全确认）执行 ${name} 实验复现`,
    answer: '',
    toolEvents: [],
    papers: [],
    artifacts: [],
    tokenCount: 0,
    durationMs: null,
    reproStatus: {
      preset_id: name,
      repo_url: preset?.repo_url || '',
      repo_license: preset?.repo_license || '',
      state: 'unavailable',
      code: 'REPRO_WORKER_UNAVAILABLE',
    },
  })
  s.updatedAt = Date.now()
  persistSessions()
  scrollToBottom()
}

// ── 6. 快捷键与全局关闭 ──
function closeAllFlyouts() {
  modeDropdownOpen.value = false
  pendingOpen.value = false
  dsOpen.value = false
  openMenuSessionId.value = ''
}

function handleDocClick(e) {
  if (e.target instanceof Element && e.target.closest('.nx-flyout')) return
  closeAllFlyouts()
}

function handleKeydown(e) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    createNewSession()
    return
  }
  if (e.key === 'Escape') {
    closeAllFlyouts()
  }
}

onMounted(() => {
  initSessions()
  loadContextData()
  checkHealth()
  window.addEventListener('resize', updateDimensions)
  window.addEventListener('keydown', handleKeydown)
  document.addEventListener('click', handleDocClick)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updateDimensions)
  window.removeEventListener('keydown', handleKeydown)
  document.removeEventListener('click', handleDocClick)
  if (elapsedTimer) clearInterval(elapsedTimer)
  if (abortController) abortController.abort()
  stopAllReproPolling()
})

// ── 7. 空态快捷建议（数据驱动） ──
const GENERAL_SUGGESTIONS = [
  {
    icon: 'Layers',
    title: '结合课程深入剖析',
    desc: '关联课程资料与学科知识，解释算法异同',
    prompt: '请结合当前课程资料，详细解释 Dijkstra 算法与 Prim 算法的异同与实现瓶颈。',
  },
  {
    icon: 'Globe',
    title: 'Web 文献综合调研',
    desc: '检索 Web 资源并生成 Markdown 综述',
    prompt: '搜索目前最新的大语言模型上下文压缩方案，整理为技术综述。',
  },
  {
    icon: 'Wrench',
    title: '多步任务拆解',
    desc: '把大问题拆成可执行的步骤清单',
    prompt: '帮我制定一个为期两周的 Transformer 论文精读计划，按天拆解任务。',
  },
]

const RESEARCH_SUGGESTIONS = [
  {
    icon: 'BookMarked',
    title: '调研一个研究方向',
    desc: '对比 standard attention 与 flash attention 的显存机制',
    prompt: '对比一下 standard attention 与 flash attention 的内存占用机制，并列出经典论文。',
  },
  {
    icon: 'Layers',
    title: '比较几篇论文',
    desc: '多论文机制对比，输出结构化对比表',
    prompt: '对比 MemGPT、Generative Agents 与 LongMem 三篇论文的记忆管理机制，输出对比表。',
  },
  {
    icon: 'FileText',
    title: '分析一篇论文',
    desc: '总结核心贡献、实验设计与适用场景',
    prompt: '分析 FlashAttention-2 的核心贡献与实验设计，总结其适用场景。',
  },
  {
    icon: 'FlaskConical',
    title: '快速复现一个实验',
    desc: '调用预设基准代码库生成执行计划',
    prompt: '帮我规划一下 nanoGPT 的复现步骤',
  },
]

const emptySuggestions = computed(() =>
  activeMode.value === NEXUS_MODES.RESEARCH ? RESEARCH_SUGGESTIONS : GENERAL_SUGGESTIONS
)
</script>

<template>
<div v-if="counter.canUseNexus" class="sfx nx-workspace">
    <!-- ── 1. 左侧 Local Rail：会话 + 本机资料 + 数据源状态 ── -->
    <aside class="nx-rail" :class="{ 'is-collapsed': railCollapsed && !isMobileOrSmall }">
      <div class="nx-rail-head">
        <SfxButton
          variant="primary"
          size="sm"
          class="nx-btn-new-chat"
          title="新建会话（Ctrl / ⌘ + K）"
          @click="createNewSession()"
        >
          <template #icon><Plus :size="15" /></template>
          <span v-if="isRailExpanded">新建会话</span>
        </SfxButton>
      </div>

      <div v-if="isRailExpanded" class="nx-rail-search">
        <div class="nx-search-wrapper">
          <Search :size="14" class="nx-search-icon" />
          <input
            v-model="searchQuery"
            type="text"
            placeholder="搜索会话…"
            class="nx-search-input"
          />
        </div>
      </div>

      <div class="nx-rail-list">
        <div v-for="group in sessionGroups" :key="group.key" class="nx-session-group">
          <div v-if="isRailExpanded" class="nx-group-title">{{ group.label }}</div>
          <div
            v-for="s in group.items"
            :key="s.id"
            class="nx-session-item"
            :class="{ 'is-active': s.id === activeSessionId }"
            @click="switchSession(s.id)"
          >
            <component
              :is="s.mode === NEXUS_MODES.RESEARCH ? Microscope : Sparkles"
              :size="15"
              class="nx-session-icon"
            />
            <template v-if="isRailExpanded">
              <div v-if="renamingSessionId === s.id" class="nx-session-meta" @click.stop>
                <input
                  v-model="renameDraft"
                  class="nx-rename-input"
                  autofocus
                  @blur="saveRename(s)"
                  @keydown.enter="saveRename(s)"
                  @keydown.escape="cancelRename"
                />
              </div>
              <div v-else class="nx-session-meta">
                <span class="nx-session-title" :title="s.title">{{ s.title }}</span>
                <span class="nx-session-sub">{{ sessionSubLabel(s) }}</span>
              </div>
              <div class="nx-session-more nx-flyout" @click.stop>
                <SfxButton
                  variant="tertiary"
                  size="sm"
                  class="nx-session-more-btn"
                  title="更多操作"
                  @click="toggleSessionMenu(s.id)"
                >
                  <template #icon><MoreHorizontal :size="14" /></template>
                </SfxButton>
                <div v-if="openMenuSessionId === s.id" class="nx-menu">
                  <SfxButton variant="tertiary" size="sm" class="nx-menu-item" @click="togglePinSession(s)">
                    <template #icon>
                      <PinOff v-if="s.pinned" :size="13" />
                      <Pin v-else :size="13" />
                    </template>
                    {{ s.pinned ? '取消置顶' : '置顶' }}
                  </SfxButton>
                  <SfxButton variant="tertiary" size="sm" class="nx-menu-item" @click="startRename(s)">
                    <template #icon><Pencil :size="13" /></template>
                    重命名
                  </SfxButton>
                  <SfxButton variant="tertiary" size="sm" class="nx-menu-item" @click="exportSession(s)">
                    <template #icon><Download :size="13" /></template>
                    导出 Markdown
                  </SfxButton>
                  <SfxButton
                    variant="tertiary"
                    size="sm"
                    class="nx-menu-item is-danger"
                    @click="deleteSession(s.id)"
                  >
                    <template #icon><Trash2 :size="13" /></template>
                    {{ confirmDeleteId === s.id ? '确认删除？' : '删除' }}
                  </SfxButton>
                </div>
              </div>
            </template>
          </div>
        </div>
      </div>

      <!-- 侧栏底部：单一「本机状态」区（UX 评审 P0-2）
           原先「本机资料列表 / 数据源切换 / 收起侧栏」三层语义被平铺在同一视觉层级，
           且「N 个会话」是孤立数字。现收敛为一个带分组标题的状态区，两行各自有标签。 -->
      <div class="nx-rail-foot">
        <div v-if="isRailExpanded" class="nx-device-status">
          <div class="nx-dv-title">本机状态</div>

          <!-- 行 1：数据源（全站唯一切换入口，dev 控件不占据一级 header） -->
          <div class="nx-ds-wrap nx-flyout">
            <div
              class="nx-dv-row"
              role="button"
              tabindex="0"
              :aria-expanded="dsOpen"
              title="切换数据源"
              @click.stop="dsOpen = !dsOpen"
              @keydown.enter.stop.prevent="dsOpen = !dsOpen"
              @keydown.space.stop.prevent="dsOpen = !dsOpen"
            >
              <span class="nx-ds-dot" :class="nexusDataSourceMode" aria-hidden="true" />
              <span class="nx-dv-label">
                数据源：{{ nexusDataSourceMode === 'demo' ? '演示数据' : '真实' }}
                <small>
                  {{ nexusDataSourceMode === 'demo' ? '本地模拟 · 会话仅存本机' : '运行时已连通 · 会话仅存本机' }}
                </small>
              </span>
              <span class="nx-dv-act">切换</span>
              <ChevronDown :size="11" class="nx-ds-caret" :class="{ 'is-open': dsOpen }" />
            </div>
            <div v-if="dsOpen" class="nx-menu nx-ds-menu">
              <div class="nx-menu-head">数据源</div>
              <SfxButton
                variant="tertiary"
                size="sm"
                class="nx-menu-item"
                :class="{ 'is-current': nexusDataSourceMode === 'demo' }"
                @click="setNexusDataSourceMode('demo'); dsOpen = false"
              >
                演示数据 · 本地模拟
              </SfxButton>
              <SfxButton
                variant="tertiary"
                size="sm"
                class="nx-menu-item"
                :class="{ 'is-current': nexusDataSourceMode === 'real' }"
                @click="setNexusDataSourceMode('real'); dsOpen = false"
              >
                真实数据源 · 连接 Runtime
              </SfxButton>
            </div>
          </div>

          <!-- 行 2：本机资料（无数据也如实显示「仅聊天记录」，不隐藏这一层） -->
          <div
            class="nx-dv-row"
            :class="{ 'is-static': !hasLocalResources }"
            role="button"
            tabindex="0"
            :aria-expanded="localPanelOpen"
            :title="hasLocalResources ? '展开本机资料' : '当前设备还没有产物或复现记录'"
            @click="toggleLocalPanel"
            @keydown.enter.stop.prevent="toggleLocalPanel"
            @keydown.space.stop.prevent="toggleLocalPanel"
          >
            <span class="nx-dv-ico" aria-hidden="true">
              <FileText :size="14" />
            </span>
            <span class="nx-dv-label">
              本机资料
              <small>{{ localResourcesSummary }}</small>
            </span>
            <span v-if="hasLocalResources" class="nx-dv-act">
              {{ localPanelOpen ? '收起' : '展开' }}
            </span>
            <ChevronDown
              v-if="hasLocalResources"
              :size="11"
              class="nx-ds-caret"
              :class="{ 'is-open': localPanelOpen }"
            />
          </div>

          <div v-if="localPanelOpen && hasLocalResources" class="nx-dv-sublist">
            <div
              v-if="localResources.repro"
              class="nx-dv-subrow"
              role="button"
              tabindex="0"
              title="跳到最近一个有复现记录的会话"
              @click="jumpToLocalResource('repro')"
              @keydown.enter.prevent="jumpToLocalResource('repro')"
            >
              <FlaskConical :size="13" />
              <span class="nx-dv-subname">复现记录</span>
              <span class="nx-dv-subcount">{{ localResources.repro }}</span>
            </div>
            <!-- demo 模式：产物行跳本地会话 -->
            <div
              v-if="nexusDataSourceMode !== 'real' && localResources.artifacts"
              class="nx-dv-subrow"
              role="button"
              tabindex="0"
              title="跳到最近一个有产物的会话"
              @click="jumpToLocalResource('artifacts')"
              @keydown.enter.prevent="jumpToLocalResource('artifacts')"
            >
              <FileText :size="13" />
              <span class="nx-dv-subname">产物</span>
              <span class="nx-dv-subcount">{{ localResources.artifacts }}</span>
            </div>
            <!-- real 模式：服务器产物列表（M3），逐项可下载 -->
            <template v-if="nexusDataSourceMode === 'real'">
              <div
                v-for="a in remoteArtifacts"
                :key="a.artifact_id"
                class="nx-dv-subrow"
                role="button"
                tabindex="0"
                :title="`下载 ${a.title}`"
                @click="downloadArtifact(a)"
                @keydown.enter.prevent="downloadArtifact(a)"
              >
                <FileText :size="13" />
                <span class="nx-dv-subname nx-dv-artifact-title">{{ a.title }}</span>
                <span class="nx-dv-subcount">{{ formatBytes(a.size_bytes) }}</span>
              </div>
              <p class="nx-dv-note">产物保存在服务器，登录同一账号即可下载。</p>
            </template>
            <p v-else class="nx-dv-note">只存在这台设备的浏览器里，换设备看不到。</p>
          </div>
        </div>

        <SfxButton
          variant="tertiary"
          size="sm"
          class="nx-rail-toggle-sfx"
          :title="railCollapsed ? '展开侧栏' : '收起侧栏'"
          @click="toggleRail"
        >
          <template #icon>
            <component :is="railCollapsed ? PanelLeftOpen : PanelLeftClose" :size="15" />
          </template>
          <span v-if="isRailExpanded" class="nx-rail-toggle-text">收起侧栏</span>
        </SfxButton>
      </div>
    </aside>

    <!-- ── 2. 中央主工作区 ── -->
    <main class="nx-main">
      <header class="nx-top-header">
        <div class="nx-top-left">
        <div class="nx-mode-selector-wrap nx-flyout">
          <SfxButton
            variant="tertiary"
            size="sm"
            class="nx-mode-sfx-btn"
            :disabled="streaming"
            title="切换工作模式"
            @click="modeDropdownOpen = !modeDropdownOpen"
          >
            <span class="nx-mode-title">{{ NEXUS_MODE_CONFIG[activeMode].label }}</span>
            <ChevronDown :size="15" class="nx-chevron" :class="{ 'is-open': modeDropdownOpen }" />
          </SfxButton>

          <!-- 模式下拉（ChatGPT 式，2026-09-08 家良拍板二次简化）：只留 名称 + 一句话差别 + ✓。
               工具白名单不进菜单——真实白名单由服务端在执行时裁决，菜单里铺 pill 只制造噪音；
               一句话描述已在切换前把「它做什么」说清。 -->
          <div v-if="modeDropdownOpen" class="nx-dropdown-menu">
            <div
              v-for="(cfg, key) in NEXUS_MODE_CONFIG"
              :key="key"
              class="nx-dropdown-item"
              role="button"
              tabindex="0"
              @click="switchMode(key)"
              @keydown.enter.prevent="switchMode(key)"
              @keydown.space.prevent="switchMode(key)"
            >
              <div class="nx-dropdown-item-title">
                {{ cfg.label }}
                <Check v-if="activeMode === key" :size="14" class="nx-check" />
              </div>
              <div class="nx-dropdown-item-desc">{{ cfg.desc }}</div>
            </div>
          </div>
        </div>

        <!-- v6：左上角 = 当前视图的身份。研究对话显示会话名，实验工作台显示实验名。
             实验名以后端命名为准（NX-LB1 display_title，用户命名优先、否则
             preset 展示名 + 会话内稳定序号）；本地/demo 运行回退本地命名。 -->
        <div class="nx-top-title">
          <span class="nx-tt-main">
            {{ isLabView ? (activeRun?.name || '未命名实验') : (currentSession?.title || '新对话') }}
          </span>
          <span class="nx-tt-sub">
            {{ isLabView
              ? (activeRun?.run?.job_id || activeRun?.runId || '未建立')
              : (isResearchMode ? 'Research 会话' : 'General 会话') }}
          </span>
        </div>
        </div><!-- /.nx-top-left -->

        <!-- v6：视图切换器固定右上角，两个视图同位同款。
             工作台内不再提供左上「← 返回研究对话」——切换器即返回：
             一处切换、处处可见，用户不会在两个层级间迷路。 -->
        <div
          v-if="isResearchMode"
          class="nx-view-switch"
          role="tablist"
          aria-label="本会话视图切换"
        >
          <span
            class="nx-vs-btn"
            :class="{ 'is-on': !isLabView }"
            role="tab"
            tabindex="0"
            :aria-selected="!isLabView"
            @click="setWorkspaceView('chat')"
            @keydown.enter.prevent="setWorkspaceView('chat')"
            @keydown.space.prevent="setWorkspaceView('chat')"
          >研究对话</span>
          <span
            class="nx-vs-btn"
            :class="{ 'is-on': isLabView }"
            role="tab"
            tabindex="0"
            :aria-selected="isLabView"
            @click="setWorkspaceView('lab')"
            @keydown.enter.prevent="setWorkspaceView('lab')"
            @keydown.space.prevent="setWorkspaceView('lab')"
          >实验工作台<b v-if="runningRunCount" class="nx-vs-cnt">{{ runningRunCount }} 个运行中</b></span>
        </div>
      </header>

      <!-- v6：实验工作台 —— 同一 Research 会话的第二视图，与上方切换器联动。
           不新增路由、不是独立页面；它只是本会话 run 数据的另一种视图。 -->
      <NexusExperimentWorkspace
        v-if="isLabView"
        class="nx-lab-host"
        :runs="sessionRuns"
        :active-id="activeRunId"
        :artifacts="activeRunArtifacts"
        :cancelling="!!activeRun?.run?.cancelling"
        :notes="runNotes"
        :preset="activePreset"
        :noting="noting"
        :execution-mode="execMode"
        @switch="switchActiveRun"
        @cancel="cancelRunFromWorkspace"
        @ask="openAskWindow"
        @analyze="analyzeRunResult"
        @report="requestAutoReport"
        @rerun="rerunFromWorkspace"
        @rename="renameRunFromWorkspace"
        @add-note="addRunNote"
      />

      <!-- Context Chips：只展示 ready 能力。
           工具已配齐，wired/unwired 的开发中说明不再上界面（2026-09-08 家良拍板）；
           能力接线真相仍由 nexusCapabilities.js 单源驱动，chips 自动跟随。 -->
      <!-- Context Chips：只放「本轮回答真正会用到的能力」。
           课程绑定入口已下沉——首屏在启动页引导条，对话中在右栏「上下文」面板
           （UX 评审 P1-4）。它属于低频设置，不该在每轮对话的顶部占一个 chip。 -->
      <div v-show="!isLabView" class="nx-context-bar">
        <div class="nx-chips-scroll">
          <span
            v-for="cap in readyCapabilities"
            :key="cap.id"
            class="nx-chip is-ready"
            :title="capHint(cap.id)"
          >
            <component :is="capIconMap[cap.icon]" :size="13" class="nx-chip-icon" />
            <span>{{ chipLabel(cap) }}</span>
          </span>
        </div>
      </div>

      <!-- 状态条：演示说明 / 真实模式健康错误（互斥，同一位置） -->
      <div v-if="nexusDataSourceMode === 'demo' && !isLabView" class="nx-status-strip is-demo" role="status">
        <TriangleAlert :size="13" class="nx-strip-icon" />
        <span>演示数据：由浏览器本地模拟，不会发送到服务器；会话仅保存在本机。</span>
      </div>
      <div v-else-if="healthError && !isLabView" class="nx-status-strip is-error" role="alert">
        <AlertCircle :size="13" class="nx-strip-icon" />
        <span>Nexus 运行时不可达（{{ healthError }}）。可在左栏底部切换回演示数据预览界面。</span>
      </div>

      <!-- 消息流主滚动区 -->
      <div v-show="!isLabView" ref="scrollArea" class="nx-chat-scroll">
        <!-- 空状态 -->
        <!-- ── 启动页（空态）v2 · 控制台方向 ──
             这块界面只服务一件事：让用户打出第一句话。因此：
             · 左对齐到消息列（发出第一条消息时不跳位），不再居中；
             · 去卡片化，靠 1px 发丝线分区；
             · 用右侧「本会话上下文」回答真正的问题——这次回答会用到什么；
             · 不引入任何装饰性元素（v1 的 46px 衬线标题 / 幽灵描边字已废弃）。 -->
        <div v-if="!currentSession?.turns?.length" class="nx-welcome">
          <section class="nx-wl-main">
            <p class="nx-wl-eyebrow">
              <i class="nx-wl-mark" aria-hidden="true" />
              Nexus · {{ currentSession?.title || '新会话' }} ·
              {{ activeMode === NEXUS_MODES.RESEARCH ? 'Research' : 'General' }}
            </p>
            <h2 class="nx-wl-title">
              {{ activeMode === NEXUS_MODES.RESEARCH ? '从一个研究问题开始' : '从一个问题开始' }}
            </h2>
            <p class="nx-wl-lede">
              {{ activeMode === NEXUS_MODES.RESEARCH
                ? '搜索论文、整理证据、比较方法；需要验证时进入实验复现。'
                : 'Nexus 会拆解复杂任务，检索课程资料与 Web，给出可核对的过程与答案。' }}
            </p>

            <!-- 模式即工具白名单（UX 评审 P1-5）：打字之前就看得见，
                 切换在原地完成；控件语汇与右上「研究对话／实验工作台」一致。 -->
            <div class="nx-wl-modeset">
              <div class="nx-seg" role="tablist" aria-label="工作模式">
                <span
                  v-for="(cfg, key, i) in NEXUS_MODE_CONFIG"
                  :key="key"
                  class="nx-seg-btn"
                  :class="{ 'is-on': activeMode === key }"
                  role="tab"
                  tabindex="0"
                  :aria-selected="activeMode === key"
                  :aria-pressed="activeMode === key"
                  @click="switchMode(key)"
                  @keydown.enter.prevent="switchMode(key)"
                  @keydown.space.prevent="switchMode(key)"
                >
                  <i class="nx-seg-no">{{ String(i + 1).padStart(2, '0') }}</i>{{ cfg.label }}
                </span>
              </div>
              <span
                class="nx-wl-tools"
                :title="`可用工具 ${NEXUS_MODE_CONFIG[activeMode].tools.length} 项：${NEXUS_MODE_CONFIG[activeMode].tools.map(formatToolDisplayName).join(' · ')}`"
              >
                <em>·</em>可用工具 <b>{{ NEXUS_MODE_CONFIG[activeMode].tools.length }}</b> 项<em>·</em>
                <template
                  v-for="(t, i) in NEXUS_MODE_CONFIG[activeMode].tools.slice(0, 5)"
                  :key="t"
                >
                  <em v-if="i">·</em>{{ formatToolDisplayName(t) }}
                </template>
                <span
                  v-if="NEXUS_MODE_CONFIG[activeMode].tools.length > 5"
                  class="nx-wl-more"
                >+{{ NEXUS_MODE_CONFIG[activeMode].tools.length - 5 }}</span>
              </span>
            </div>

            <div class="nx-wl-sect">
              <span class="nx-wl-sect-t">起点建议</span>
              <span class="nx-wl-sect-c">Starters</span>
            </div>
            <div class="nx-starters">
              <div
                v-for="(sg, i) in emptySuggestions"
                :key="sg.title"
                class="nx-starter"
                role="button"
                tabindex="0"
                @click="applySuggestion(sg.prompt)"
                @keydown.enter.prevent="applySuggestion(sg.prompt)"
                @keydown.space.prevent="applySuggestion(sg.prompt)"
              >
                <span class="nx-starter-no">{{ String(i + 1).padStart(2, '0') }}</span>
                <span class="nx-starter-tx">
                  <b>{{ sg.title }}</b>
                  <span>{{ sg.desc }}</span>
                </span>
                <span class="nx-starter-ar" aria-hidden="true">→</span>
              </div>
            </div>
          </section>

          <!-- 右侧上下文面板：回答"这次回答会用到什么"。
               能力三态只读 nexusCapabilities.js，这里不硬编码任何状态。 -->
          <aside class="nx-ctx">
            <div class="nx-ctx-h">本会话上下文 / Context</div>
            <div class="nx-ctx-row">
              <span class="nx-ctx-k">课程</span>
              <span class="nx-ctx-v" :class="{ 'is-off': !currentSession?.courseId }">
                {{ currentSession?.courseName || '未绑定' }}
              </span>
              <SfxButton
                variant="secondary"
                size="sm"
                class="nx-ctx-bind"
                @click="coursePickerOpen = true"
              >
                {{ currentSession?.courseId ? '更换' : '绑定课程' }}
              </SfxButton>
            </div>
            <div
              v-for="row in contextRows"
              :key="row.k"
              class="nx-ctx-row"
              :title="row.hint"
            >
              <span class="nx-ctx-k">{{ row.k }}</span>
              <span class="nx-ctx-v">
                <span class="nx-ctx-tag" :class="row.cls">{{ row.v }}</span>
              </span>
            </div>
            <div class="nx-ctx-row">
              <span class="nx-ctx-k">会话存储</span>
              <span class="nx-ctx-v">
                {{ nexusDataSourceMode === 'demo' ? '本地模拟 · 仅存本机' : '仅保存在本机' }}
              </span>
            </div>
            <p class="nx-ctx-note">
              {{ currentSession?.courseId
                ? '本轮回答会参考这门课的资料与知识图谱。'
                : '未绑定课程时，回答只会用到 Web 与通用知识；绑定后该课的资料与知识图谱会进入检索范围。' }}
            </p>
          </aside>
        </div>

        <!-- 对话 Turns 消息流 -->
        <article
          v-for="(turn, tIdx) in currentSession?.turns"
          :key="tIdx"
          class="nx-chat-turn"
          :class="{ 'is-live': streaming && turn === streamingTurn }"
        >
          <!-- 用户消息 -->
          <div class="nx-turn-user">
            <div class="nx-user-avatar"><User :size="13" /></div>
            <div class="nx-user-content">{{ turn.question }}</div>
          </div>

          <!-- 智能体回应区 -->
          <div class="nx-turn-agent">
            <div class="nx-agent-avatar">
              <component
                :is="activeMode === NEXUS_MODES.RESEARCH ? Microscope : Sparkles"
                :size="14"
              />
            </div>

            <div class="nx-agent-body">
              <!-- 过程折叠摘要（实验记录轨：一行摘要 + 展开时间线） -->
              <div
                v-if="turn.toolEvents?.length"
                class="nx-process-summary-card"
                :class="{ 'is-failed': turn.failure || failedToolCount(turn) > 0 }"
              >
                <div
                  class="nx-process-header"
                  role="button"
                  tabindex="0"
                  @click="toggleTool(tIdx, 'all')"
                  @keydown.enter.prevent="toggleTool(tIdx, 'all')"
                  @keydown.space.prevent="toggleTool(tIdx, 'all')"
                >
                  <div class="nx-process-badge">
                    <TriangleAlert v-if="turn.failure || failedToolCount(turn) > 0" :size="12" />
                    <Wrench v-else :size="12" />
                    <span>{{ processSummaryLabel(turn) }}</span>
                  </div>
                  <ChevronDown
                    :size="14"
                    class="nx-process-chevron"
                    :class="{ 'is-open': isToolExpanded(tIdx, 'all') }"
                  />
                </div>

                <div v-if="isToolExpanded(tIdx, 'all')" class="nx-process-steps">
                  <div
                    v-for="(evt, eIdx) in turn.toolEvents"
                    :key="eIdx"
                    class="nx-process-step"
                    :class="[evt.kind, evt.status]"
                  >
                    <div class="nx-step-head">
                      <span class="nx-step-name">
                        {{ evt.kind === 'call' ? '调用' : '返回' }} · {{ formatToolDisplayName(evt.name) }}
                      </span>
                      <span class="nx-step-time">{{ evt.time }}</span>
                    </div>
                    <pre v-if="evt.kind === 'call'" class="nx-step-json">{{ JSON.stringify(evt.args, null, 2) }}</pre>
                    <pre v-else class="nx-step-json">{{ evt.content }}</pre>
                  </div>
                </div>
              </div>

              <!-- 运行状态行：流式期间始终可见 -->
              <div v-if="streaming && turn === streamingTurn" class="nx-live-line" role="status">
                <span class="nx-live-dot" aria-hidden="true" />
                <span>{{ liveStatusText }}</span>
                <span class="nx-live-timer">{{ streamElapsed }}</span>
              </div>

              <!-- 论文检索结果（行式列表，避免卡片海） -->
              <div v-if="turn.papers?.length" class="nx-paper-list">
                <div v-for="paper in turn.papers" :key="paper.paper_id" class="nx-paper-row">
                  <div class="nx-pr-meta">
                    <span>arXiv:{{ paper.paper_id }}</span>
                    <span>{{ paper.year }}</span>
                  </div>
                  <h4 class="nx-pr-title">{{ paper.title }}</h4>
                  <p class="nx-pr-authors">{{ (paper.authors || []).join(', ') }}</p>
                  <p class="nx-pr-abstract">{{ paper.abstract }}</p>
                  <a
                    class="nx-pr-link"
                    :href="paper.source_url"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    查看原文 <ExternalLink :size="11" />
                  </a>
                </div>
              </div>

              <!-- NX-R1a：论文证据卡（Research-only 工具产出；General 无此工具不渲染） -->
              <NexusEvidenceCard :evidences="turn.evidences" />

              <!-- 实验复现规划卡片（入口走 Approval Gate） -->
              <div v-if="turn.reproductionPreset" class="nx-repro-card">
                <div class="nx-rc-header">
                  <FlaskConical :size="15" class="nx-rc-icon" />
                  <span class="nx-rc-title">实验复现规划 · {{ turn.reproductionPreset.preset_id }}</span>
                </div>
                <div class="nx-rc-meta">
                  <span>
                    仓库：
                    <a :href="turn.reproductionPreset.repo_url" target="_blank" rel="noopener noreferrer">
                      {{ turn.reproductionPreset.repo_url }}
                    </a>
                  </span>
                  <span>许可：{{ turn.reproductionPreset.repo_license }}</span>
                </div>
                <div class="nx-rc-steps">
                  <div class="nx-rc-steps-title">执行计划</div>
                  <ol>
                    <li v-for="(step, sIdx) in turn.reproductionPreset.steps" :key="sIdx">
                      <code>{{ step }}</code>
                    </li>
                  </ol>
                </div>
                <!-- NX-G1：执行入口仅 Research。规划卡可从历史残留（切模式后），
                     但 General 下不得出现可点的复现执行按钮。 -->
                <div v-if="activeMode === NEXUS_MODES.RESEARCH" class="nx-rc-footer">
                  <SfxButton variant="secondary" size="sm" @click="openReproductionModal(turn.reproductionPreset)">
                    <template #icon><FlaskConical :size="13" /></template>
                    尝试复现
                  </SfxButton>
                </div>
                <div v-else class="nx-rc-footer">
                  <span class="nx-rl-note">复现执行仅在 Nexus Research 模式可用，请切换模式后继续。</span>
                </div>
              </div>

              <!-- NX-G2 执行审批卡：提案展示 + 本人批准/拒绝。批准前零执行；
                   放行由服务端票据核销决定，本卡只提交决定。 -->
              <div v-if="turn.approval" class="nx-repro-live">
                <div class="nx-rl-head">
                  <FlaskConical :size="15" class="nx-rl-icon" />
                  <span class="nx-rl-title">复现执行审批 · {{ turn.approval.preset_id }}</span>
                  <span class="nx-rl-status" :class="turn.approval.status">{{ approvalStatusLabel(turn.approval) }}</span>
                </div>
                <div class="nx-rs-meta">
                  <span>{{ turn.approval.repo_url }}</span>
                  <span>许可 {{ turn.approval.repo_license }}</span>
                </div>
                <p class="nx-rl-note">
                  计划指纹 {{ String(turn.approval.plan_hash || '').slice(0, 12) }}…
                  · 预算约 {{ turn.approval.budget?.estimated_minutes ?? '—' }} 分钟 /
                  {{ turn.approval.budget?.max_steps ?? '—' }} 步
                  · 批准后才提交执行，未批准不会运行任何代码
                </p>
                <div v-if="turn.approval.status === 'pending'" class="nx-answer-actions">
                  <!-- T5 Ask：运行按钮改为一次完成的合并操作（切换 Auto＋本次批准＋执行）。 -->
                  <SfxButton
                    v-if="isResearchMode && execMode === 'ask'"
                    variant="primary"
                    size="sm"
                    :loading="turn.approval.deciding || turn.approval.executing"
                    title="一次点击完成切换到 Auto、本次批准与执行，不再二次确认"
                    @click="approveWithAuto(turn)"
                  >
                    切换 Auto 并批准执行
                  </SfxButton>
                  <SfxButton
                    v-else
                    variant="primary"
                    size="sm"
                    :loading="turn.approval.deciding || turn.approval.executing"
                    @click="decideApprovalFor(turn, 'approved')"
                  >
                    批准并执行
                  </SfxButton>
                  <SfxButton
                    variant="secondary"
                    size="sm"
                    :disabled="turn.approval.deciding || turn.approval.executing"
                    @click="decideApprovalFor(turn, 'rejected')"
                  >
                    拒绝
                  </SfxButton>
                </div>
                <!-- T5：切 Ask 不暗中取消已启动 run；卡片下标注并保留用户取消。 -->
                <div v-if="turn.approval.status === 'pending' && hasActiveRuns" class="nx-rl-note">
                  已启动实验继续运行，可在工作台取消。
                  <SfxButton
                    v-for="r in activeRuns"
                    :key="r.id"
                    variant="danger"
                    size="sm"
                    :loading="r.run.cancelling"
                    @click="cancelReproRun(r.turn)"
                  >
                    取消 {{ r.name }}
                  </SfxButton>
                </div>
                <p v-if="turn.approval.error" class="nx-turn-failure">{{ turn.approval.error }}</p>
              </div>

              <!-- 复现执行状态卡：确认不等于执行，未接入时必须如实报出错误码 -->
              <div v-if="turn.reproStatus" class="nx-repro-status">
                <div class="nx-rs-head">
                  <AlertCircle :size="14" class="nx-rs-icon" />
                  <span class="nx-rs-title">复现未执行 · {{ turn.reproStatus.code }}</span>
                </div>
                <p class="nx-rs-desc">
                  安全确认已通过，但复现执行器尚未接入。本次<strong>不会在任何环境运行任何代码</strong>；
                  执行器（Repro Worker）接入后，这里会展示真实的构建、日志与指标对比。
                </p>
                <div v-if="turn.reproStatus.repo_url" class="nx-rs-meta">
                  <span>{{ turn.reproStatus.repo_url }}</span>
                  <span>许可 {{ turn.reproStatus.repo_license }}</span>
                </div>
              </div>

              <!-- NX-E2/E3 实验控制台：会话内就地展开（设计板 2026-09-06 v1）。
                   阶段条来自 Worker 真实边界事件；取消是独立作业 API，不等于聊天 Stop。 -->
              <div v-if="turn.reproRun" class="nx-repro-live" :class="{ 'is-collapsed': !turn.reproRun.expanded }">
                <div class="nx-rl-head nx-cs-head" @click="toggleReproExpanded(turn)">
                  <FlaskConical :size="15" class="nx-rl-icon" />
                  <!-- T5：自主 run 无 job_id，标题用运行名；状态含 reconciling。 -->
                  <span class="nx-rl-title">{{ turn.reproRun.job_id ? `复现作业 · ${turn.reproRun.job_id}` : `自主实验 · ${turn.reproRun.run_id || turn.reproRun.runId || ''}` }}</span>
                  <span class="nx-rl-status" :class="turn.reproRun.status">{{ reproStatusLabel(turn.reproRun) }}</span>
                  <span v-if="turn.reproRun.reconciling" class="nx-rl-note" title="执行器不可达，显示登记快照；运行未终止，恢复后继续">对账中</span>
                  <span class="nx-cs-spacer" />
                  <span v-if="reproElapsed(turn.reproRun)" class="nx-cs-elapsed">{{ reproElapsed(turn.reproRun) }}</span>
                  <SfxButton
                    v-if="reproCancellable(turn.reproRun)"
                    variant="secondary"
                    size="sm"
                    :loading="turn.reproRun.cancelling"
                    @click.stop="cancelReproRun(turn)"
                  >
                    取消
                  </SfxButton>
                  <SfxButton
                    v-if="reproCancellable(turn.reproRun) && (turn.reproRun.runId || turn.reproRun.run_id)"
                    variant="tertiary"
                    size="sm"
                    title="Nexus 请求取消本次运行时，你在此签发一次性授权（5 分钟内有效）"
                    :loading="turn.reproRun.granting"
                    @click.stop="grantCancelFor(turn)"
                  >
                    授权取消
                  </SfxButton>
                  <!-- v6：会话内这张卡只做「引用条」——看清状态、能取消；
                        要看全量（日志/步骤/指标）去实验工作台，那里才是主舞台。 -->
                  <SfxButton
                    variant="tertiary"
                    size="sm"
                    title="在实验工作台查看（右上角可切回研究对话）"
                    @click.stop="openRunInWorkspace(turn)"
                  >
                    打开工作台
                  </SfxButton>
                  <span class="nx-cs-toggle">{{ turn.reproRun.expanded ? '▾' : '▸' }}</span>
                </div>

                <template v-if="turn.reproRun.expanded">
                  <!-- T5 自主 run：attempt 即步骤（编号/命令摘要/退出码/日志尾），
                       不套用 Worker 六段轨道（无 Building/Verifying 即 skipped，不假装）。 -->
                  <div v-if="turn.reproRun.provider === 'autonomous' && (turn.reproRun.attempts || []).length" class="nx-cs-sec">
                    <div class="nx-cs-sech">
                      <span>尝试记录</span>
                      <span class="nx-cs-secn">实际命令与退出码只读呈现，不重放执行</span>
                    </div>
                    <table class="nx-cs-table">
                      <thead>
                        <tr><th>#</th><th>命令摘要</th><th>退出码</th><th>耗时</th><th>结果</th></tr>
                      </thead>
                      <tbody>
                        <tr
                          v-for="a in turn.reproRun.attempts"
                          :key="a.attempt_no"
                          :class="{ 'is-bad': a.result === 'failed' }"
                        >
                          <td class="nx-cs-mono">{{ a.attempt_no }}</td>
                          <td class="nx-cs-cmd">{{ a.command_summary }}</td>
                          <td class="nx-cs-mono">{{ a.exit_code ?? '—' }}</td>
                          <td class="nx-cs-mono">{{ a.duration_s != null ? `${Math.round(a.duration_s)}s` : '—' }}</td>
                          <td><span class="nx-cs-chip" :class="`is-${a.result === 'succeeded' ? 'ok' : a.result === 'failed' ? 'err' : a.result === 'running' ? 'run' : 'pend'}`">{{ a.result === 'succeeded' ? '完成' : a.result === 'failed' ? '失败' : a.result === 'running' ? '运行中' : '—' }}</span></td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                  <!-- 阶段条：Preparing→Building→Running→Metric→Verifying→Completed。
                       自主 run 无 Worker 轨道时隐藏（attempt 表才是真相源）。 -->
                  <div v-if="turn.reproRun.provider !== 'autonomous'" class="nx-cs-stagebar" role="list" aria-label="执行阶段">
                    <template v-for="(st, i) in reproStageRail(turn.reproRun)" :key="st.stage">
                      <div v-if="i" class="nx-cs-stgline" :class="{ 'is-done': st.state === 'done' }" />
                      <div class="nx-cs-stg" :class="`is-${st.state}`" role="listitem" :title="st.note || st.label">
                        <span class="nx-cs-stgn">{{
                          st.state === 'done' ? '✓' : st.state === 'skipped' ? '⊘' : st.state === 'failed' ? '✕' : i + 1
                        }}</span>
                        {{ st.label }}
                      </div>
                    </template>
                  </div>
                  <p v-if="reproStageNotes(turn.reproRun)" class="nx-rl-note">{{ reproStageNotes(turn.reproRun) }}</p>

                  <!-- 步骤表：命令为服务端审核标签，只读、无编辑 / 无 stdin -->
                  <div v-if="turn.reproRun.stages.length" class="nx-cs-sec">
                    <div class="nx-cs-sech">
                      <span>步骤</span>
                      <span class="nx-cs-secn">命令为服务端审核标签，只读、无编辑 / 无 stdin</span>
                    </div>
                    <table class="nx-cs-table">
                      <thead>
                        <tr><th>命令</th><th>退出码</th><th>耗时</th><th>状态</th></tr>
                      </thead>
                      <tbody>
                        <tr
                          v-for="s in turn.reproRun.stages"
                          :key="s.index"
                          :class="{ 'is-cur': reproIsCurrentStep(turn.reproRun, s.index), 'is-bad': reproStepState(turn.reproRun, s) === 'err' }"
                        >
                          <td class="nx-cs-cmd">{{ s.command }}</td>
                          <td class="nx-cs-mono">{{ s.exit_code ?? '—' }}</td>
                          <td class="nx-cs-mono">{{ s.duration_s != null ? `${s.duration_s}s` : (reproIsCurrentStep(turn.reproRun, s.index) ? '…' : '—') }}</td>
                          <td><span class="nx-cs-chip" :class="`is-${reproStepState(turn.reproRun, s)}`">{{ reproStepLabel(turn.reproRun, s) }}</span></td>
                        </tr>
                      </tbody>
                    </table>
                  </div>

                  <!-- 日志：运行中当前步骤增量（服务端已脱敏），终态为最后一步日志尾 -->
                  <div v-if="reproLogLines(turn.reproRun)" class="nx-cs-sec">
                    <div class="nx-cs-sech">
                      <span>日志</span>
                      <span class="nx-cs-secn">{{ reproLogSource(turn.reproRun) }} · 最近 20 行</span>
                    </div>
                    <pre class="nx-cs-log">{{ reproLogLines(turn.reproRun) }}</pre>
                  </div>

                  <p v-if="!turn.reproRun.stages.length && turn.reproRun.status === 'queued'" class="nx-rl-note">
                    排队中，等待执行器开始…
                  </p>
                  <p v-if="turn.reproRun.status === 'cancelling'" class="nx-rl-note">取消已受理，等待进程回收确认…</p>
                  <p v-if="turn.reproRun.status === 'cancelled'" class="nx-rl-note">作业已取消：当前步骤进程组已回收，已完成步骤的结果如实保留。</p>
                  <p v-if="turn.reproRun.code && turn.reproRun.status !== 'cancelled'" class="nx-rl-note">
                    失败语义：{{ turn.reproRun.code }}{{ turn.reproRun.detail ? ' — ' + turn.reproRun.detail : '' }}
                  </p>
                  <p v-if="turn.reproRun.pollExhausted" class="nx-rl-note">轮询已达上限，可刷新查看最新状态。</p>
                  <!-- NX-E1：恢复 turn（换设备/刷新）成功态无本地报告时，手动补领。
                       自动补会重复产物；手动一次幂等由用户控制。 -->
                  <div
                    v-if="turn.restoredRun && turn.reproRun.status === 'succeeded' && !turn.reproRun.verdict"
                    class="nx-answer-actions"
                  >
                    <SfxButton variant="secondary" size="sm" @click="claimRestoredReport(turn)">
                      补领复现报告
                    </SfxButton>
                    <span class="nx-rl-note">该作业在别处完成，报告可能已在产物面板</span>
                  </div>
                  <div
                    v-if="turn.reproRun.verdict"
                    class="nx-rl-verdict"
                    :class="turn.reproRun.verdict === 'PASS' ? 'is-pass' : 'is-fail'"
                  >
                    <span class="nx-rl-verdict-label">指标判定：{{ turn.reproRun.verdict }}</span>
                    <span
                      v-for="c in turn.reproRun.comparison"
                      :key="c.metric"
                      class="nx-rl-metric"
                    >
                      {{ c.metric }}：期望 {{ c.target }} ±{{ c.tolerance }}，实测
                      {{ c.observed == null ? '未提取' : c.observed }} → {{ c.pass ? 'PASS' : 'FAIL' }}
                    </span>
                    <span class="nx-rl-note">PASS/FAIL 由确定性指标比较生成，非 LLM 判定</span>
                  </div>
                  <p v-if="turn.reproRun.reportError" class="nx-rl-note">{{ turn.reproRun.reportError }}</p>
                </template>
              </div>

              <!-- Markdown 核心答复正文（节流渲染，禁止直接逐 token 调 renderContent） -->
              <div
                v-if="turn.answer"
                class="nx-markdown-body"
                v-html="renderedAnswer(turn)"
              />

              <!-- M3 产物卡：write_artifact 真实写入后的可下载文件 -->
              <div v-if="turn.artifacts?.length" class="nx-artifact-list">
                <div
                  v-for="a in turn.artifacts"
                  :key="a.artifact_id"
                  class="nx-artifact-card"
                >
                  <component
                    :is="a.artifact_type === 'latex' ? FileCode : FileText"
                    :size="15"
                    class="nx-art-icon"
                  />
                  <div class="nx-art-meta">
                    <div class="nx-art-title">{{ a.title }}</div>
                    <div class="nx-art-sub">
                      {{ a.artifact_type === 'latex' ? 'LaTeX' : 'Markdown' }} · {{ formatBytes(a.size_bytes) }}
                    </div>
                  </div>
                  <SfxButton variant="secondary" size="sm" @click="downloadArtifact(a)">
                    <template #icon><ExternalLink :size="12" /></template>
                    下载
                  </SfxButton>
                </div>
              </div>

              <!-- 失败状态卡片 -->
              <div v-if="turn.failure" class="nx-turn-failure">
                <AlertCircle :size="15" />
                <span>{{ turn.failure }}</span>
              </div>

              <!-- 回答操作条：只保留真实可用的动作。
                   点赞/点踩已移除（UX 评审 P1-3）：评价服务未接入，占位按钮
                   只制造「能反馈」的错觉，等有真实落点再放回来。 -->
              <div
                v-if="(turn.answer || turn.failure) && !(streaming && turn === streamingTurn)"
                class="nx-answer-actions"
              >
                <div class="nx-answer-actions-left">
                  <SfxButton
                    variant="tertiary"
                    size="sm"
                    class="nx-act-btn"
                    title="复制回答"
                    aria-label="复制回答"
                    @click="copyAnswer(turn)"
                  >
                    <template #icon><Copy :size="13" /></template>
                  </SfxButton>
                  <SfxButton
                    variant="tertiary"
                    size="sm"
                    class="nx-act-btn"
                    title="重新生成"
                    aria-label="重新生成"
                    :disabled="streaming"
                    @click="retryTurn(tIdx)"
                  >
                    <template #icon><RotateCw :size="13" /></template>
                  </SfxButton>
                </div>
                <span class="nx-answer-actions-right">由 AI 生成</span>
              </div>
            </div>
          </div>
        </article>
      </div>

      <!-- NX-H1：会话当前计划卡（write_todos 快照投影；无计划不渲染） -->
      <NexusPlanCard :plan="currentSession?.planState?.plan" />

      <!-- 底部 Composer -->
      <footer v-show="!isLabView" class="nx-composer-box">
        <div class="nx-composer-inner">
          <!-- NX-A1 附件 chips：就绪/部分解析随消息引用；失败可删重传 -->
          <div
            v-if="sessionAttachmentIds(currentSession).length"
            class="nx-attach-chips"
          >
            <span
              v-for="a in sessionAttachmentIds(currentSession)"
              :key="a.attachment_id || a.filename"
              class="nx-attach-chip"
              :class="a.status"
              :title="a.error_detail || a.filename"
            >
              <Paperclip :size="11" />
              <span class="nx-attach-name">{{ a.filename }}</span>
              <span class="nx-attach-state">{{ attachmentStateLabel(a) }}</span>
              <X :size="11" class="nx-attach-remove" @click="removeSessionAttachment(a)" />
            </span>
          </div>
          <!-- v6：审批浮窗挂在输入框上方。
               理由：决定与「提出修改」必须在同一个视线落点——用户在输入框打字时
               就能看到提案并改它，不必上翻到消息流里找那张卡（历史上滚过就看不见了）。
               消息流里那张卡保留不动，作为提案的留存记录。 -->
          <!-- v2（NX-LB2）：支持多条待办（服务端恢复 + SSE），带结构化 diff 与基线提示。
               不静默替用户选中某个运行——每条都写明 preset 与指纹。 -->
          <div v-for="item in pendingItems" :key="item.id" class="nx-approval-dock">
            <div class="nx-ad-head">
              <FlaskConical :size="14" class="nx-ad-icon" />
              <span class="nx-ad-title">复现方案待你确认 · {{ item.preset || '未命名 preset' }}</span>
              <span class="nx-ad-status">待批准</span>
            </div>
            <p v-if="item.objective" class="nx-ad-obj">{{ item.objective }}</p>
            <div class="nx-ad-meta">
              <span v-if="item.repo" class="nx-ad-repo">{{ item.repo }}</span>
              <span v-if="item.license">许可 {{ item.license }}</span>
              <span>
                预算约 {{ item.budget?.estimated_minutes ?? '—' }} 分钟 /
                {{ item.budget?.max_steps ?? '—' }} 步
              </span>
              <span v-if="item.expiresAt">有效期至 {{ item.expiresAt }}</span>
            </div>

            <!-- 结构化 diff：只渲染服务端给的差异，前端不自己比对 -->
            <div v-if="item.diff.length" class="nx-ad-diff">
              <div class="nx-ad-diffcap">与上一版的差异</div>
              <div v-for="(d, di) in item.diff" :key="di" class="nx-ad-drow">
                <span class="nx-ad-dk" :class="diffKindClass(d.kind || d.type)">
                  {{ diffKindLabel(d.kind || d.type) }}
                </span>
                <span class="nx-ad-dn">{{ d.name || d.key || d.field || '—' }}</span>
                <span class="nx-ad-dv">
                  <s v-if="d.before !== undefined && d.before !== null">{{ d.before }}</s>
                  <template v-if="d.before !== undefined && d.before !== null"> → </template>
                  <b>{{ d.after ?? d.value ?? '—' }}</b>
                </span>
              </div>
            </div>

            <!-- 基线不匹配：如实标注，不沿用旧容差判 PASS -->
            <p v-if="item.baselineNote" class="nx-ad-warn">
              {{ item.baselineNote }}
            </p>

            <p class="nx-ad-note">
              计划指纹 {{ String(item.planHash || '').slice(0, 12) }}…
              <template v-if="item.proposalId"> · 提案 v{{ item.proposalVersion ?? '—' }}</template>
              · 批准后才提交执行，未批准不会运行任何代码
            </p>
            <div class="nx-ad-actions">
              <!-- T5 Ask：一次完成的合并操作（切换 Auto＋本次批准＋执行）。 -->
              <SfxButton
                v-if="isResearchMode && execMode === 'ask'"
                variant="primary"
                size="sm"
                :loading="item.turn?.approval?.deciding || item.turn?.approval?.executing"
                title="一次点击完成切换到 Auto、本次批准与执行，不再二次确认"
                @click="approveRestoredWithAuto(item)"
              >
                切换 Auto 并批准执行
              </SfxButton>
              <SfxButton
                v-else
                variant="primary"
                size="sm"
                :loading="item.turn?.approval?.deciding || item.turn?.approval?.executing"
                @click="approveRestored(item)"
              >
                批准执行
              </SfxButton>
              <SfxButton variant="secondary" size="sm" @click="scrollToApprovalInStream">
                查看完整方案
              </SfxButton>
              <SfxButton
                variant="danger"
                size="sm"
                :disabled="item.turn?.approval?.deciding"
                @click="rejectRestored(item)"
              >
                拒绝
              </SfxButton>
              <span class="nx-ad-hint">↓ 在下面输入框提出修改，改完重新确认</span>
            </div>
            <p v-if="item.turn?.approval?.error" class="nx-ad-error">{{ item.turn.approval.error }}</p>
          </div>

          <textarea
            v-model="draft"
            class="nx-composer-textarea"
            rows="3"
            placeholder="输入你的问题…"
            :disabled="streaming"
            @keydown.enter.exact.prevent="send"
          />

          <div class="nx-composer-toolbar">
            <div class="nx-toolbar-left">
              <!-- NX-A1 真实上传入口（此前为无行为死控件，已移除；现接通后恢复） -->
              <SfxButton
                variant="tertiary"
                size="sm"
                title="上传资料（pdf/docx/图片/xlsx/pptx/ppt/doc）"
                :disabled="streaming"
                @click="triggerAttachmentPicker"
              >
                <template #icon><Paperclip :size="13" /></template>
                附件
              </SfxButton>
              <!-- T5 Ask/Auto：只在 Research 展示；General 隐藏且不发送。
                   下拉式（对齐 ChatGPT 模式切换的形态）：收起只占当前模式名，
                   展开后每项一句话说清差别——模式差异在切换前就看得见。
                   同一会话的研究对话与询问浮窗共享 execMode；切 Ask 不取消已启动 run。 -->
              <div
                v-if="isResearchMode"
                class="nx-seg nx-exec-seg"
                role="tablist"
                aria-label="执行模式"
                title="Ask 自主研究与文档输出，不运行实验；Auto 确认一次后可自主配置、运行和修复实验"
              >
                <span
                  class="nx-seg-btn"
                  :class="{ 'is-on': execMode === 'ask' }"
                  role="tab"
                  tabindex="0"
                  :aria-selected="execMode === 'ask'"
                  title="自主研究与文档输出，不运行实验"
                  @click="setExecMode('ask')"
                  @keydown.enter.prevent="setExecMode('ask')"
                  @keydown.space.prevent="setExecMode('ask')"
                >
                  <i class="nx-seg-no">研</i>研究与写作
                </span>
                <span
                  class="nx-seg-btn"
                  :class="{ 'is-on': execMode === 'auto' }"
                  role="tab"
                  tabindex="0"
                  :aria-selected="execMode === 'auto'"
                  title="可在确认后自主配置、运行和修复实验"
                  @click="setExecMode('auto')"
                  @keydown.enter.prevent="setExecMode('auto')"
                  @keydown.space.prevent="setExecMode('auto')"
                >
                  <i class="nx-seg-no">验</i>研究与实验
                </span>
              </div>
              <span v-if="isResearchMode && !execModeSaved" class="nx-rl-note" title="偏好保存失败，仅本次会话有效">
                偏好未同步
              </span>
              <input
                ref="attachmentInput"
                type="file"
                multiple
                accept=".pdf,.docx,.jpg,.jpeg,.png,.xlsx,.pptx,.ppt,.doc"
                class="nx-file-hidden"
                @change="onAttachmentFileChange"
              />
            </div>
            <!-- 模型网关 P0：下拉选项 = /health models 清单投影；单模型时如实只显示一个。
                 演示数据源无真实清单，退回静态徽标（不伪造可选项）。 -->
            <select
              v-if="nexusDataSourceMode === 'real' && availableModels.length"
              :value="effectiveModel"
              class="nx-model-select"
              title="选择本次对话的模型（服务端 allowlist 校验）"
              :disabled="streaming"
              @change="selectModel($event.target.value)"
            >
              <option v-for="m in availableModels" :key="m.id" :value="m.id">
                {{ m.label }}{{ m.default ? '（默认）' : '' }}
              </option>
            </select>
            <span
              v-else
              class="nx-engine-badge"
              title="引擎由 Nexus Runtime 配置（NEXUS_LLM_MODEL）；编排层为 Nexus Agent 工作流"
            >
              <Bot :size="12" />
              <span>DeepSeek-V3 · Nexus Agent 编排</span>
            </span>

            <div class="nx-toolbar-right">
              <SfxButton v-if="streaming" variant="secondary" size="sm" @click="stop">
                <template #icon><Square :size="13" /></template>
                停止
              </SfxButton>
              <SfxButton
                v-else
                variant="primary"
                size="sm"
                :disabled="!draft.trim()"
                title="Enter 发送 · Shift+Enter 换行"
                @click="send"
              >
                <template #icon><Send :size="13" /></template>
                发送
              </SfxButton>
            </div>
          </div>
        </div>
      </footer>
    </main>

    <!-- v6：工作台内的「询问 Nexus」浮窗。继承同一研究会话的上下文，可自由拖动；
         关闭后实验继续运行——它只是把对话搬过来，不是切换会话、也不是中断。 -->
    <NexusAskWindow
      :open="askWindowOpen"
      :context-text="currentSession?.title || '本会话'"
      :context-pill="askContextPill"
      :busy="streaming"
      @close="askWindowOpen = false"
      @send="onAskSend"
    />

    <!-- ── 3. 右侧回应区：48px 图标轨（常驻）+ 320px overlay 抽屉（按需展开） ──
         图标轨保证「过程与来源始终一键可达」，抽屉默认收起，把 272px 还回主工作区；
         开合状态按设备持久化（page-design.md §3.4）。 -->
    <div v-if="!isTablet && !isMobileOrSmall" class="nx-detail-zone">
      <!-- 3.1 overlay 抽屉：覆盖主工作区右侧，不挤压主内容宽度 -->
      <Transition name="nx-drawer">
      <section v-if="detailDrawerOpen" class="nx-detail-drawer">
        <header class="nx-dd-head">
          <div class="nx-dd-bar">
            <span class="nx-dd-title">回应区</span>
            <SfxButton
              variant="tertiary"
              size="sm"
              class="nx-dd-close"
              title="收起面板"
              aria-label="收起面板"
              @click="closeDetailDrawer"
            >
              <template #icon><X :size="15" /></template>
            </SfxButton>
          </div>

          <!-- 抽屉内 tab 条（对齐设计板 Board B 状态 B）：
               展开后可直接切三个面板，不必先收起再点图标轨 -->
          <div class="nx-drawer-tabs">
            <SfxButton
              v-for="tab in detailTabs"
              :key="tab.id"
              variant="tertiary"
              size="sm"
              class="nx-dt"
              :class="{ 'is-active': activeDetailTab === tab.id }"
              :title="tab.hint"
              @click="selectDetailTabInDrawer(tab.id)"
            >
              <span class="nx-dt-label">{{ tab.label }}</span>
              <span v-if="tab.badge" class="nx-dt-n">{{ tab.badge }}</span>
              <span v-else-if="tab.unseen" class="nx-dt-dot" aria-hidden="true" />
            </SfxButton>
          </div>
        </header>

        <div class="nx-detail-content">
          <!-- 上下文面板：课程卡 + 能力状态列表（取代大数字统计块） -->
          <div v-if="activeDetailTab === 'context'" class="nx-tab-pane">
            <div class="nx-pane-section">
              <h4 class="nx-section-eyebrow">当前上下文</h4>
              <div class="nx-context-card">
                <BookOpen :size="15" class="nx-cc-icon" />
                <div class="nx-cc-meta">
                  <div class="nx-cc-title">{{ currentSession?.courseName || '未绑定课程' }}</div>
                  <div class="nx-cc-desc">
                    {{ currentSession?.courseId ? '回答会参考这门课的资料与知识图谱' : '绑定课程后，回答可以参考该课的资料' }}
                  </div>
                </div>
              </div>
              <SfxButton variant="secondary" size="sm" class="nx-cc-change" @click="coursePickerOpen = true">
                更换课程
              </SfxButton>
            </div>

            <div class="nx-pane-section">
              <h4 class="nx-section-eyebrow">能力状态</h4>
            <div class="nx-cap-list">
              <!-- NX-G3：能力状态列表同样消费 effective，与首屏 Chips 同一真相源。 -->
              <div
                v-for="cap in effectiveCapabilities"
                :key="cap.id"
                class="nx-cap-row"
                :class="cap.state"
                :title="capHint(cap.id)"
              >
                <component :is="capIconMap[cap.icon]" :size="14" class="nx-cap-icon" />
                <div class="nx-cap-body">
                  <span class="nx-cap-name">{{ cap.label }}</span>
                  <span v-if="capHint(cap.id)" class="nx-cap-hint">{{ capHint(cap.id) }}</span>
                </div>
                <span class="nx-cap-tag" :class="cap.state">{{ capStateTagText(cap) }}</span>
              </div>
            </div>
            </div>
          </div>

          <!-- 执行轨迹面板（实验记录轨） -->
          <div v-if="activeDetailTab === 'activity'" class="nx-tab-pane">
            <div v-if="!currentSession?.turns?.length" class="nx-pane-empty">
              还没有执行记录。提问后，工具调用会按时间排列在这里。
            </div>
            <div v-else class="nx-log-stream">
              <div v-for="(turn, tIdx) in currentSession?.turns" :key="tIdx" class="nx-log-turn">
                <div class="nx-log-turn-label">提问 #{{ tIdx + 1 }}</div>
                <div v-if="!turn.toolEvents?.length" class="nx-log-empty">本次回答未调用工具</div>
                <div
                  v-for="(evt, eIdx) in turn.toolEvents"
                  :key="eIdx"
                  class="nx-log-item"
                  :class="evt.kind"
                >
                  <span class="nx-log-dot" aria-hidden="true" />
                  <div class="nx-log-body">
                    <div class="nx-log-title">
                      {{ evt.kind === 'call' ? '发起' : '返回' }} · {{ formatToolDisplayName(evt.name) }}
                    </div>
                    <div class="nx-log-time">{{ evt.time }}</div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 信息源面板：只展示本会话真实检索到的结果 -->
          <div v-if="activeDetailTab === 'sources'" class="nx-tab-pane">
            <div
              v-if="sourcesTotal === 0"
              class="nx-pane-empty"
            >
              本会话还没有检索结果。提问后，命中的论文、网页、课程资料与知识库条目会汇总到这里。
            </div>

            <div v-else class="nx-src-groups">
              <div v-if="sessionSources.course.length" class="nx-src-group">
                <div class="nx-src-head">课程资料 · {{ sessionSources.course.length }}（经核实）</div>
                <div
                  v-for="(c, i) in sessionSources.course"
                  :key="`c${i}`"
                  class="nx-src-row"
                >
                  <span class="nx-src-title">{{ c.text }}</span>
                  <span class="nx-src-meta">
                    {{ c.resource }}{{ c.page != null ? ` · 第 ${c.page} 页` : '' }}{{ c.node ? ` · ${c.node}` : '' }}
                  </span>
                </div>
              </div>

              <div v-if="sessionSources.csKb.length" class="nx-src-group">
                <div class="nx-src-head">CS 知识库 · {{ sessionSources.csKb.length }}（权威来源）</div>
                <div
                  v-for="(k, i) in sessionSources.csKb"
                  :key="`k${i}`"
                  class="nx-src-row"
                >
                  <span class="nx-src-title">{{ k.name }}</span>
                  <span class="nx-src-meta">{{ [k.source, k.course].filter(Boolean).join(' · ') }}</span>
                </div>
              </div>

              <div v-if="sessionSources.papers.length" class="nx-src-group">
                <div class="nx-src-head">论文 · {{ sessionSources.papers.length }}</div>
                <a
                  v-for="p in sessionSources.papers"
                  :key="p.paper_id"
                  class="nx-src-row"
                  :href="p.source_url"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <span class="nx-src-title">{{ p.title }}</span>
                  <span class="nx-src-meta">arXiv:{{ p.paper_id }} · {{ p.year }}</span>
                </a>
              </div>

              <div v-if="sessionSources.web.length" class="nx-src-group">
                <div class="nx-src-head">网页 · {{ sessionSources.web.length }}</div>
                <a
                  v-for="(s, i) in sessionSources.web"
                  :key="i"
                  class="nx-src-row"
                  :href="s.url"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <span class="nx-src-title">{{ s.title }}</span>
                  <span class="nx-src-meta">{{ s.snippet }}</span>
                </a>
              </div>

              <p v-if="sessionSources.unparsable" class="nx-src-note">
                另有 {{ sessionSources.unparsable }} 条检索结果无法解析（旧会话的截断结果）；
                新会话使用结构化 items，不再出现该问题。
              </p>
            </div>
        </div>
        </div>
      </section>
      </Transition>

      <!-- 3.2 48px 图标轨：常驻，点击切换面板 / 再点收起 -->
      <aside class="nx-detail-rail" aria-label="回应区面板">
        <SfxButton
          v-for="tab in detailTabs"
          :key="tab.id"
          variant="tertiary"
          size="sm"
          class="nx-dr-item"
          :class="{ 'is-active': detailDrawerOpen && activeDetailTab === tab.id }"
          :title="`${tab.label} · ${tab.hint}`"
          :aria-label="`${tab.label} · ${tab.hint}`"
          :aria-pressed="detailDrawerOpen && activeDetailTab === tab.id"
          @click="selectDetailTab(tab.id)"
        >
          <template #icon>
            <span class="nx-dr-icon-wrap">
              <component :is="tab.icon" :size="18" />
              <span v-if="tab.badge" class="nx-dr-badge">{{ tab.badge }}</span>
              <span v-else-if="tab.unseen" class="nx-dr-dot" aria-hidden="true" />
            </span>
          </template>
        </SfxButton>

        <div class="nx-dr-foot">
          <span class="nx-dr-foot-line" aria-hidden="true" />
        </div>
      </aside>
    </div>

    <!-- ── 4. 课程选择 ── -->
    <SfxDrawer
      :open="coursePickerOpen"
      title="选择绑定课程"
      :width="480"
      @close="coursePickerOpen = false"
    >
      <div class="nx-course-picker-list">
        <div
          class="nx-course-picker-item is-none"
          :class="{ 'is-selected': !currentSession?.courseId }"
          role="button"
          tabindex="0"
          @click="selectCourse(null)"
          @keydown.enter.prevent="selectCourse(null)"
        >
          <div class="nx-cpi-title">不绑定特定课程（全局问答）</div>
          <div class="nx-cpi-desc">仅基于学科知识库与搜索引擎</div>
        </div>
        <div
          v-for="c in contextOverview.coursesList"
          :key="c.course_id"
          class="nx-course-picker-item"
          :class="{ 'is-selected': currentSession?.courseId === c.course_id }"
          role="button"
          tabindex="0"
          @click="selectCourse(c)"
          @keydown.enter.prevent="selectCourse(c)"
        >
          <div class="nx-cpi-title">{{ c.title }}</div>
          <div class="nx-cpi-desc">
            身份：{{ roleLabel(c.role) }} · 进度 {{ Math.round((c.progress || 0) * 100) }}%
          </div>
        </div>
      </div>
    </SfxDrawer>

    <!-- ── 5. 复现二次确认（Approval Gate） ── -->
    <SfxDrawer
      :open="reproModalOpen"
      title="确认实验复现环境与许可"
      :width="480"
      @close="reproModalOpen = false"
    >
      <div v-if="selectedReproPreset" class="nx-repro-confirm-pane">
        <div class="nx-rcp-warn">
          <TriangleAlert :size="15" />
          <span>代码将在隔离沙箱中执行，执行前需确认依赖与许可合规。</span>
        </div>
        <div class="nx-rcp-grid">
          <div class="nx-rcp-row">
            <span class="nx-rcp-label">目标项目</span>
            <span class="nx-rcp-val">{{ selectedReproPreset.preset_id }}</span>
          </div>
          <div class="nx-rcp-row">
            <span class="nx-rcp-label">开源许可</span>
            <span class="nx-rcp-val">{{ selectedReproPreset.repo_license }}</span>
          </div>
          <div class="nx-rcp-row">
            <span class="nx-rcp-label">预估耗时</span>
            <span class="nx-rcp-val">约 {{ selectedReproPreset.estimated_minutes }} 分钟</span>
          </div>
        </div>
        <p class="nx-rcp-confirm-note">
          点击「确认执行」即表示你已确认该仓库的许可允许演示用途，并接受其在隔离沙箱中运行。
        </p>
        <div class="nx-rcp-actions">
          <SfxButton variant="secondary" @click="reproModalOpen = false">取消</SfxButton>
          <SfxButton variant="primary" @click="confirmStartReproduction">确认执行</SfxButton>
        </div>
      </div>
    </SfxDrawer>

    <!-- NX-LB2 提案编辑器：基于已完成的运行改参数 → 新提案 → 送审。
         只列服务端白名单参数（parameters.schema），前端先校验，服务端兜底。 -->
    <Transition name="nx-prop-fade">
    <div v-if="proposalDraft" class="nx-prop-backdrop" @click.self="closeProposalEditor">
      <div class="nx-prop" role="dialog" aria-modal="true" aria-label="调整方案再运行">
        <div class="nx-prop-head">
          <span class="nx-prop-title">调整方案 · {{ proposalDraft.presetName }}</span>
          <span class="nx-prop-sub">基于 {{ proposalDraft.runName }}</span>
        </div>
        <div class="nx-prop-body">
          <div v-for="(spec, name) in proposalDraft.schema" :key="name" class="nx-prop-row">
            <div class="nx-prop-k">
              <span class="nx-prop-name">{{ name }}</span>
              <span class="nx-prop-help">{{ spec.help }}</span>
            </div>
            <div class="nx-prop-ctl">
              <input
                v-model="proposalDraft.values[name]"
                class="nx-prop-input"
                type="number"
                :min="spec.min"
                :max="spec.max"
                :step="spec.type === 'float' ? '0.1' : '1'"
              />
              <span class="nx-prop-base">基线 {{ proposalDraft.baseline[name] }}</span>
            </div>
            <span v-if="paramChanged(name)" class="nx-prop-changed">改</span>
          </div>
          <p v-if="metricSensitiveChanged" class="nx-prop-warn">
            修改了影响指标的参数：无已验证基线时，本次结果只出探索性结论，不宣称复现通过。
          </p>
          <p v-if="proposalDraft.error" class="nx-prop-error">{{ proposalDraft.error }}</p>
        </div>
        <div class="nx-prop-foot">
          <span class="nx-prop-count">{{ proposalChangedCount ? '改动 ' + proposalChangedCount + ' 项' : '未改动' }}</span>
          <span class="nx-prop-spacer" />
          <SfxButton variant="secondary" size="sm" @click="closeProposalEditor">取消</SfxButton>
          <SfxButton variant="primary" size="sm" :loading="proposalDraft.submitting" @click="submitProposal">
            生成提案并送审
          </SfxButton>
        </div>
      </div>
    </div>
    </Transition>
  </div>
  <div v-else class="nx-perm-denied">
    <AlertCircle :size="30" />
    <h2>暂无 Nexus AI 使用权限</h2>
    <p>Nexus AI 默认向所有用户开放（platform.nexus.use）。你的账号当前未持有该权限（可能已被管理员撤销），如需使用请联系平台管理员授权。</p>
  </div>
</template>

<style scoped>
/* 无 platform.nexus.use 权限时的整页空态（决策 D10） */
.nx-perm-denied {
  min-height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-3, 12px);
  padding: var(--space-8, 48px) var(--space-5, 24px);
  text-align: center;
  color: var(--text-secondary, #8B93A7);
}

.nx-perm-denied h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary, #E8ECF4);
}

.nx-perm-denied p {
  margin: 0;
  max-width: 420px;
  font-size: 13px;
  line-height: 1.6;
}

/* ── L3 容器规范：height: 100%; min-height: 0; overflow: hidden ── */
.nx-workspace {
  display: flex;
  height: 100%;
  min-height: 0;
  width: 100%;
  overflow: hidden;
  background: var(--surface-canvas);
  color: var(--text-primary);
  font-family: var(--font-sans);
}

/* 浮层通用：触发器 + 弹层共用的定位上下文 */
.nx-flyout {
  position: relative;
}

/* 键盘可达性：所有自绘可点元素统一焦点环 */
.nx-starter:focus-visible,
.nx-seg-btn:focus-visible,
.nx-chip:focus-visible,
.nx-dv-row:focus-visible,
.nx-dv-subrow:focus-visible,
.nx-process-header:focus-visible,
.nx-dropdown-item:focus-visible,
.nx-session-item:focus-visible,
.nx-course-picker-item:focus-visible,
.nx-dr-item:focus-visible,
.nx-dd-close:focus-visible {
  outline: 2px solid var(--color-focus);
  outline-offset: 2px;
}

/* ── 1. 左侧 Local Rail ── */
.nx-rail {
  width: var(--nexus-rail-width);
  height: 100%;
  background: var(--surface-page);
  border-right: 1px solid var(--border-default);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  transition: width var(--duration-normal) var(--ease-out);
}

.nx-rail.is-collapsed {
  width: var(--nexus-rail-collapsed);
}

.nx-rail-head {
  padding: var(--space-3) var(--space-4);
}

.nx-btn-new-chat {
  width: 100%;
}

.nx-rail.is-collapsed .nx-btn-new-chat {
  padding-left: 0;
  padding-right: 0;
}

.nx-rail-search {
  padding: 0 var(--space-4) var(--space-2);
}

.nx-search-wrapper {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 6px 10px;
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
}

.nx-search-wrapper:focus-within {
  border-color: var(--color-focus);
  box-shadow: 0 0 0 2px var(--ink-100);
}

.nx-search-icon {
  color: var(--text-muted);
  flex-shrink: 0;
}

.nx-search-input {
  border: none;
  background: transparent;
  outline: none;
  font-size: var(--ui-sm-size);
  color: var(--text-primary);
  width: 100%;
}

.nx-search-input::placeholder {
  color: var(--text-muted);
}

.nx-rail-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-2) var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.nx-group-title {
  font-size: var(--caption-size);
  color: var(--text-muted);
  padding: var(--space-1) var(--space-2);
}

.nx-session-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 7px 10px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  color: var(--text-secondary);
  transition: background var(--duration-fast) var(--ease-out);
}

.nx-session-item:hover {
  background: var(--surface-soft);
  color: var(--text-primary);
}

.nx-session-item.is-active {
  background: var(--ink-100);
  color: var(--ink-900);
}

/* 当前项状态线：::before 伪元素（design.md §12.5，禁用阴影模拟） */
.nx-session-item.is-active::before {
  content: '';
  position: absolute;
  left: 0;
  top: var(--space-2);
  bottom: var(--space-2);
  width: 3px;
  background: var(--ink-900);
  border-radius: var(--radius-full);
}

.nx-session-icon {
  flex-shrink: 0;
  color: var(--text-muted);
}

.nx-session-item.is-active .nx-session-icon {
  color: var(--ink-900);
}

.nx-session-meta {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.nx-session-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--ui-sm-size);
  line-height: var(--ui-sm-line);
}

.nx-session-sub {
  font-size: var(--caption-size);
  line-height: var(--caption-line);
  color: var(--text-muted);
}

.nx-rename-input {
  width: 100%;
  border: 1px solid var(--color-focus);
  border-radius: var(--radius-xs);
  padding: 3px 6px;
  font-size: var(--ui-sm-size);
  color: var(--text-primary);
  background: var(--surface-panel);
  outline: none;
}

.nx-session-more {
  display: none;
  flex-shrink: 0;
}

/* focus-within 补齐键盘可达性：只靠 :hover 时，Tab 进不去这个按钮 */
.nx-session-item:hover .nx-session-more,
.nx-session-item:focus-within .nx-session-more {
  display: block;
}

.nx-session-more-btn {
  padding: 0 var(--space-1);
  min-height: 26px;
}

/* ── 浮层菜单（会话 More / 数据源） ── */
.nx-menu {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  min-width: 164px;
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
  padding: 4px;
  z-index: 60;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nx-menu-head {
  font-size: var(--caption-size);
  color: var(--text-muted);
  padding: var(--space-1) var(--space-2) 2px;
}

.nx-menu-item {
  width: 100%;
  justify-content: flex-start;
  gap: var(--space-2);
  padding: 6px var(--space-2);
  font-size: var(--ui-sm-size);
  min-height: 30px;
}

.nx-menu-item.is-danger {
  color: var(--red-700);
}

.nx-menu-item.is-danger:hover:not(:disabled) {
  background: var(--red-100);
}

.nx-menu-item.is-current {
  color: var(--ink-900);
  font-weight: 600;
}

.nx-ds-menu {
  left: 0;
  right: auto;
  top: auto;
  bottom: calc(100% + 6px);
  min-width: 208px;
}

/* ── 侧栏底部：单一「本机状态」区（UX 评审 P0-2） ── */
.nx-rail-foot {
  padding: var(--space-2) var(--space-3) var(--space-3);
  border-top: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  flex-shrink: 0;
}

/* 本机状态：两张独立白卡（UX 评审 P2-6，对齐设计板 .dev-row）
   每张卡自带「标题 + 副标题 + 动作词」，外层只做纵向排布，不再套灰底大卡——
   灰卡 + 灰底 + 灰字三层叠灰，整块会读成一段不可点的说明文案。 */
.nx-device-status {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.nx-dv-title {
  padding: 0 2px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--text-muted);
}

.nx-dv-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 9px;
  background: var(--surface-panel);
  cursor: pointer;
  font-size: var(--caption-size);
  color: var(--text-secondary);
  transition: border-color var(--duration-fast) var(--ease-out),
    box-shadow var(--duration-fast) var(--ease-out);
}

.nx-dv-row:hover {
  border-color: var(--nexus-accent-line);
  box-shadow: var(--shadow-xs);
  color: var(--text-primary);
}

/* 无数据时不给「可展开」的错觉：光标、边框与配色都降级 */
.nx-dv-row.is-static {
  cursor: default;
  color: var(--text-muted);
}

.nx-dv-row.is-static:hover {
  border-color: var(--border-subtle);
  box-shadow: none;
  color: var(--text-muted);
}

.nx-dv-ico {
  display: inline-flex;
  flex-shrink: 0;
  color: var(--text-muted);
}

.nx-dv-label {
  flex: 1;
  min-width: 0;
  font-size: 12px;
  font-weight: 550;
  color: var(--text-primary);
}

.nx-dv-label small {
  display: block;
  margin-top: 1px;
  overflow: hidden;
  font-size: 10.5px;
  font-weight: 400;
  color: var(--text-muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 动作词常驻：让两行都明确「可点」，不靠 hover 才暴露（键盘可达性的另一半） */
.nx-dv-act {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 600;
  color: var(--nexus-accent-strong);
}

.nx-dv-sublist {
  display: flex;
  flex-direction: column;
  gap: 1px;
  margin-top: 2px;
  padding-top: 4px;
  border-top: 1px dashed var(--border-default);
}

.nx-dv-subrow {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 6px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: var(--caption-size);
  color: var(--text-secondary);
}

.nx-dv-subrow:hover {
  background: var(--surface-page);
  color: var(--text-primary);
}

.nx-dv-subname {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nx-dv-subcount {
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  color: var(--ink-900);
}

.nx-dv-note {
  margin: 2px 6px 0;
  font-size: 10px;
  line-height: 1.5;
  color: var(--text-muted);
}

.nx-ds-dot {
  width: 7px;
  height: 7px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

.nx-ds-dot.demo {
  background: var(--amber-500);
}

.nx-ds-dot.real {
  background: var(--green-500);
}

.nx-ds-caret {
  color: var(--text-muted);
  transition: transform var(--duration-fast) var(--ease-out);
}

.nx-ds-caret.is-open {
  transform: rotate(180deg);
}

.nx-rail-toggle-sfx {
  justify-content: flex-start;
  padding: 5px 6px;
  min-height: 30px;
}

.nx-rail-toggle-text {
  font-size: var(--ui-sm-size);
}

/* ── 2. 中央主工作区 ── */
.nx-main {
  flex: 1;
  min-width: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: transparent;
}

/* 工作区 Header + 双细线（厚墨蓝 + 细灰，arXiv 论文头版式惯例） */
.nx-top-header {
  position: relative;
  height: 56px;
  padding: 0 var(--space-6);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}

.nx-top-header::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 0;
  border-top: 2px solid var(--ink-900);
  border-bottom: 1px solid var(--border-default);
}

.nx-mode-selector-wrap {
  position: relative;
}

/* ── v6：顶栏左侧组（模式选择器 + 当前视图身份） ── */
.nx-top-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}

.nx-top-title {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  min-width: 0;
  padding-left: var(--space-3);
  border-left: 1px solid var(--border-default);
}

.nx-tt-main {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 34ch;
}

.nx-tt-sub {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-muted);
  white-space: nowrap;
}

/* ── v6：视图切换器（固定右上角，两个视图同位同款） ── */
.nx-view-switch {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  background: var(--surface-soft);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

.nx-vs-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  height: 26px;
  padding: 0 var(--space-3);
  border-radius: var(--radius-full);
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
  transition:
    background var(--duration-fast) var(--ease-out),
    color var(--duration-fast) var(--ease-out),
    box-shadow var(--duration-fast) var(--ease-out);
}

.nx-vs-btn:hover {
  color: var(--text-primary);
}

.nx-vs-btn:focus-visible {
  outline: 2px solid var(--color-focus);
  outline-offset: 1px;
}

.nx-vs-btn.is-on {
  background: var(--surface-panel);
  color: var(--text-primary);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(20, 33, 61, 0.08);
}

.nx-vs-cnt {
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
  color: var(--nexus-accent);
  background: var(--nexus-accent-soft);
  border-radius: var(--radius-full);
  padding: 1px 6px;
}

/* 工作台主舞台：吃掉主区剩余高度，自己内部再分栏 */
.nx-lab-host {
  flex: 1;
  min-height: 0;
}

/* ── v6：输入框上方的审批浮窗 ── */
.nx-approval-dock {
  margin-bottom: var(--space-2);
  padding: var(--space-3) var(--space-4);
  background: var(--surface-panel);
  border: 1px solid var(--nexus-accent-line);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
}

.nx-ad-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.nx-ad-icon {
  color: var(--nexus-accent);
  flex-shrink: 0;
}

.nx-ad-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.nx-ad-status {
  font-size: 10.5px;
  font-weight: 600;
  color: var(--nexus-accent);
  background: var(--nexus-accent-soft);
  border: 1px solid var(--nexus-accent-line);
  border-radius: var(--radius-full);
  padding: 1px 8px;
}

.nx-ad-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1) var(--space-3);
  margin-top: var(--space-2);
  font-size: 11.5px;
  color: var(--text-secondary);
}

.nx-ad-meta .nx-ad-repo {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.nx-ad-note {
  margin: var(--space-2) 0 0;
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-muted);
}

.nx-ad-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-3);
  flex-wrap: wrap;
}

.nx-ad-hint {
  font-size: 11px;
  color: var(--text-disabled);
}

.nx-ad-error {
  margin: var(--space-2) 0 0;
  font-size: 11.5px;
  color: var(--red-700);
}

/* 审批浮窗 v2：目标 / diff / 基线提示 */
.nx-ad-obj {
  margin: var(--space-2) 0 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-primary);
}

.nx-ad-diff {
  margin-top: var(--space-2);
  border-top: 1px solid var(--border-subtle);
  padding-top: var(--space-2);
}

.nx-ad-diffcap {
  font-family: var(--font-mono);
  font-size: 9.5px;
  letter-spacing: 0.1em;
  color: var(--text-muted);
  text-transform: uppercase;
  margin-bottom: 4px;
}

.nx-ad-drow {
  display: grid;
  grid-template-columns: 44px 120px minmax(0, 1fr);
  gap: var(--space-2);
  align-items: baseline;
  padding: 3px 0;
  font-size: 12px;
}

.nx-ad-dk {
  font-family: var(--font-mono);
  font-size: 9.5px;
  text-align: center;
  padding: 1px 0;
  border-radius: var(--radius-xs);
  background: var(--surface-soft);
  color: var(--text-secondary);
}

.nx-ad-dk.is-mod { color: var(--nexus-accent); background: var(--nexus-accent-soft); }
.nx-ad-dk.is-add { color: var(--green-700); background: var(--green-100); }
.nx-ad-dk.is-del { color: var(--red-700); background: var(--red-100); }

.nx-ad-dn {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-secondary);
}

.nx-ad-dv {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-primary);
  word-break: break-all;
}

.nx-ad-dv s { color: var(--text-disabled); }

.nx-ad-warn {
  margin: var(--space-2) 0 0;
  padding: 7px 10px;
  border-radius: var(--radius-xs);
  background: #fdf6e3;
  box-shadow: inset 0 0 0 1px #ecd9a4;
  font-size: 11.5px;
  line-height: 1.65;
  color: #8a6a1f;
}

.nx-mode-sfx-btn {
  padding: 4px var(--space-2);
  min-height: 40px;
}

.nx-mode-title {
  font-size: var(--title-3-size);
  font-weight: 600;
  color: var(--text-primary);
}

.nx-chevron {
  color: var(--text-muted);
  transition: transform var(--duration-fast) var(--ease-out);
}

.nx-chevron.is-open {
  transform: rotate(180deg);
}

.nx-dropdown-menu {
  position: absolute;
  top: calc(100% + 8px);
  left: 0;
  width: 264px;
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
  padding: var(--space-2);
  z-index: 60;
}

.nx-dropdown-item {
  padding: 9px 12px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
}

.nx-dropdown-item:hover {
  background: var(--surface-cool);
}

.nx-dropdown-item-title {
  font-weight: 600;
  font-size: 13px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.nx-check {
  color: var(--nexus-accent);
  flex-shrink: 0;
}

.nx-dropdown-item-desc {
  font-size: var(--caption-size);
  color: var(--text-secondary);
  margin-top: 2px;
  line-height: var(--caption-line);
}


/* ── Context Chips 行 ── */
.nx-context-bar {
  padding: var(--space-2) var(--space-6);
  background: var(--surface-canvas);
  flex-shrink: 0;
}

.nx-chips-scroll {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  overflow-x: auto;
}

.nx-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 26px;
  padding: 0 10px;
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-full);
  font-size: var(--caption-size);
  color: var(--text-secondary);
  white-space: nowrap;
  flex-shrink: 0;
  transition:
    background var(--duration-fast) var(--ease-out),
    border-color var(--duration-fast) var(--ease-out),
    color var(--duration-fast) var(--ease-out);
}

/* ready：唯一允许"激活观感"的能力状态 */
.nx-chip.is-ready {
  border-color: var(--border-strong);
  color: var(--text-primary);
}

/* 待接入聚合入口：虚线 + 菱形标记，中性不报警 */

.nx-chip-icon {
  color: var(--text-muted);
}

/* ── 状态条（演示说明 / 运行时不可达） ── */
.nx-status-strip {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 6px var(--space-6);
  font-size: var(--caption-size);
  line-height: var(--caption-line);
  flex-shrink: 0;
}

.nx-status-strip.is-demo {
  background: var(--amber-100);
  color: var(--amber-700);
  border-bottom: 1px solid var(--amber-300);
}

.nx-status-strip.is-error {
  background: var(--red-100);
  color: var(--red-700);
  border-bottom: 1px solid var(--red-300);
}

.nx-strip-icon {
  flex-shrink: 0;
}

/* ── 消息流与滚动 ── */
.nx-chat-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  /* 预留滚动条槽位：Research 建议 4 条比 General 3 条高，若刚好跨过
     出滚动条的临界点，宽度会突变导致整块横向抖一下。 */
  scrollbar-gutter: stable;
  padding: var(--space-6);
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

/* ══════════════════════════════════════════════════════════════
   启动页（空态）v2 · 控制台方向
   与 NexusLab v4/v6 共用视觉词：1px 发丝线分区、mono 大写小标、
   26–28px 控件 / 1px 描边、accent 只出现在关键动作。
   不引入任何装饰性字符（v1 的衬线大标题与幽灵描边字已废弃）。
   ══════════════════════════════════════════════════════════════ */
.nx-welcome {
  /* 顶部对齐，不用 margin:auto 垂直居中。
     原因（实测）：General 3 条建议 / Research 4 条，工具白名单 5 vs 10 项，
     切换模式时内容高度会变；居中会把这个差值的一半变成"整块上下平移"，
     用户看到的就是整个启动页在跳。顶部对齐后，上方元素零位移，
     只有最下方的建议列表向下增长——这是列表变长该有的行为。 */
  margin: 0;
  padding-top: var(--space-2);
  width: 100%;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 28px;
  align-items: start;
}

.nx-wl-eyebrow {
  display: flex;
  align-items: center;
  gap: 7px;
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: 0.1em;
  color: var(--text-muted);
  text-transform: uppercase;
}

.nx-wl-mark {
  width: 6px;
  height: 6px;
  background: var(--ink-900);
  flex-shrink: 0;
}

.nx-wl-title {
  margin-top: 12px;
  font-size: 27px;
  font-weight: 650;
  line-height: 1.32;
  letter-spacing: -0.01em;
  color: var(--ink-900);
}

.nx-wl-lede {
  margin-top: 8px;
  max-width: 34em;
  /* min-height = 2 行：两种模式的引导句长短不同（34 字 / 25 字），
     不锁下限会出现 2 行↔1 行的抖动。 */
  min-height: calc(13.5px * 1.8 * 2);
  font-size: 13.5px;
  line-height: 1.8;
  color: var(--text-secondary);
}

/* 模式分段控件：与右上「研究对话／实验工作台」同一控件语汇 */
.nx-wl-modeset {
  margin-top: 18px;
  display: flex;
  align-items: center;
  gap: 10px;
  /* nowrap：工具行在窄屏若换行，整行高度 18→36，切换模式时下方全部位移 */
  flex-wrap: nowrap;
  min-width: 0;
}

.nx-seg {
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  background: var(--surface-soft);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-full);
}

.nx-seg-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 26px;
  padding: 0 12px;
  border-radius: var(--radius-full);
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
  transition:
    background var(--duration-fast) var(--ease-out),
    color var(--duration-fast) var(--ease-out);
}

.nx-seg-btn:hover { color: var(--text-primary); }
.nx-seg-btn:focus-visible { outline: 2px solid var(--color-focus); outline-offset: 1px; }

.nx-seg-btn.is-on {
  background: var(--surface-panel);
  color: var(--text-primary);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(20, 33, 61, 0.08);
}

.nx-seg-no {
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-style: normal;
  color: var(--text-disabled);
  font-variant-numeric: tabular-nums;
}

.nx-seg-btn.is-on .nx-seg-no { color: var(--nexus-accent); }

/* T5 Ask/Auto：输入框工具栏内的同一分段控件语汇（26px 高对齐 SfxButton sm）。 */

/* 工具白名单：mono 一行，不用绿色药丸（绿色会被读成"成功态"） */
.nx-wl-tools {
  /* 恒为一行：可伸缩 + 溢出省略，全量工具名挂 title。
     Research 10 项比 General 5 项长得多，不锁一行就会换行导致高度抖动。 */
  flex: 1 1 auto;
  min-width: 0;
  height: 18px;
  line-height: 18px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-muted);
}

.nx-wl-tools em {
  font-style: normal;
  color: var(--border-strong);
  padding: 0 3px;
}

.nx-wl-tools b {
  color: var(--text-secondary);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.nx-wl-more { color: var(--text-disabled); }

/* 分区小标：12.5px 标题 + mono 大写注，全站统一 */
.nx-wl-sect {
  margin-top: 26px;
  max-width: 640px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-default);
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}

.nx-wl-sect-t { font-size: 12.5px; font-weight: 600; color: var(--ink-900); }

.nx-wl-sect-c {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.1em;
  color: var(--text-muted);
  text-transform: uppercase;
}

/* 起点建议：行式清单，发丝线分隔，不做卡片 */
.nx-starters {
  max-width: 640px;
  display: flex;
  flex-direction: column;
}

.nx-starter {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  padding: 11px 8px 11px 0;
  border-bottom: 1px solid var(--border-default);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
}

.nx-starter:hover { background: var(--surface-panel); }
.nx-starter:focus-visible { outline: 2px solid var(--color-focus); outline-offset: -2px; }

.nx-starter-no {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-disabled);
  font-variant-numeric: tabular-nums;
}

.nx-starter-tx { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.nx-starter-tx b { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.nx-starter-tx span { font-size: 11.5px; line-height: 1.6; color: var(--text-secondary); }

.nx-starter-ar {
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--text-disabled);
  transition:
    transform var(--duration-slow) var(--ease-out),
    color var(--duration-fast) var(--ease-out);
}

/* accent 全屏唯一落点：悬停时箭头右移并着色 */
.nx-starter:hover .nx-starter-ar {
  transform: translateX(3px);
  color: var(--nexus-accent);
}

/* ── 右侧上下文面板：回答"这次回答会用到什么" ── */
.nx-ctx {
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-panel);
  overflow: hidden;
}

.nx-ctx-h {
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-default);
  background: var(--surface-canvas);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.1em;
  color: var(--text-muted);
  text-transform: uppercase;
}

.nx-ctx-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-subtle);
}

.nx-ctx-k { flex: 0 0 68px; font-size: 12px; color: var(--text-secondary); }
.nx-ctx-v { margin-left: auto; font-size: 12px; color: var(--text-primary); text-align: right; }
.nx-ctx-v.is-off { color: var(--text-muted); }
.nx-ctx-bind { flex-shrink: 0; height: 26px; min-height: 26px; padding: 0 10px; }

.nx-ctx-tag {
  display: inline-block;
  font-family: var(--font-mono);
  font-size: 9.5px;
  letter-spacing: 0.04em;
  padding: 1px 6px;
  border-radius: var(--radius-xs);
}

.nx-ctx-tag.ok { color: var(--green-700); background: var(--green-100); }

.nx-ctx-tag.half {
  color: #8a6a1f;
  background: #fdf6e3;
  box-shadow: inset 0 0 0 1px #ecd9a4;
}

.nx-ctx-tag.no { color: var(--text-muted); background: var(--surface-soft); }

.nx-ctx-note {
  padding: 10px 14px;
  font-size: 11px;
  line-height: 1.7;
  color: var(--text-muted);
  background: var(--surface-canvas);
  border-top: 1px solid var(--border-default);
}


/* ── 对话 Turn ── */
.nx-chat-turn {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.nx-turn-user {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  align-self: flex-end;
  max-width: 80%;
}

.nx-user-avatar {
  width: 26px;
  height: 26px;
  border-radius: var(--radius-full);
  background: var(--surface-soft);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
  flex-shrink: 0;
}

.nx-user-content {
  padding: 10px 14px;
  background: var(--color-brand-soft);
  color: var(--text-primary);
  border-radius: var(--radius-md);
  font-size: var(--body-md-size);
  line-height: 1.6;
}

.nx-turn-agent {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  max-width: 90%;
}

.nx-agent-avatar {
  width: 26px;
  height: 26px;
  border-radius: var(--radius-full);
  background: var(--surface-cool);
  border: 1px solid var(--border-default);
  color: var(--ink-700);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

/* live 态是 #007AF4 的三个法定职责之一：进行中 */
.nx-chat-turn.is-live .nx-agent-avatar {
  background: var(--nexus-accent);
  border-color: var(--nexus-accent);
  color: var(--text-inverse);
}

.nx-agent-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

/* ── 实验记录轨（Signature）：过程层统一视觉 ── */
.nx-process-summary-card {
  border: 1px solid var(--border-subtle);
  border-left: 2px solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--surface-cool);
  overflow: hidden;
}

/* 失败 turn 的过程折叠行进告警态（UX 评审 P2-9）：
   收起时也必须能看出这一轮出了问题，否则用户只看到一张灰色过程卡。 */
.nx-process-summary-card.is-failed {
  border-left-color: var(--amber-500);
  background: var(--amber-100);
}

.nx-process-summary-card.is-failed .nx-process-badge {
  color: var(--amber-700);
  font-weight: 500;
}

.nx-process-header {
  padding: 8px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  font-size: var(--caption-size);
}

.nx-process-header:hover {
  background: var(--surface-soft);
}

.nx-process-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-secondary);
}

.nx-process-chevron {
  color: var(--text-muted);
  transition: transform var(--duration-fast) var(--ease-out);
}

.nx-process-chevron.is-open {
  transform: rotate(180deg);
}

.nx-process-steps {
  padding: var(--space-2) 12px;
  border-top: 1px solid var(--border-subtle);
  background: var(--surface-panel);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.nx-process-step {
  font-size: var(--caption-size);
}

.nx-step-head {
  display: flex;
  justify-content: space-between;
  gap: var(--space-2);
  color: var(--text-secondary);
  margin-bottom: 3px;
}

.nx-step-name {
  font-weight: 500;
}

.nx-step-time {
  font-family: var(--font-mono);
  color: var(--text-muted);
  flex-shrink: 0;
}

.nx-step-json {
  margin: 0;
  padding: 6px 8px;
  background: var(--code-bg);
  color: var(--code-text);
  border-radius: var(--radius-xs);
  font-family: var(--font-mono);
  font-size: var(--caption-size);
  line-height: 1.5;
  max-height: 140px;
  overflow: auto;
}

/* 运行状态行 */
.nx-live-line {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--surface-cool);
  border: 1px solid var(--border-subtle);
  border-left: 2px solid var(--nexus-accent);
  border-radius: var(--radius-sm);
  font-size: var(--caption-size);
  color: var(--text-secondary);
  width: fit-content;
}

.nx-live-dot {
  width: 7px;
  height: 7px;
  border-radius: var(--radius-full);
  background: var(--nexus-accent);
  animation: nx-live-pulse 1.2s var(--ease-out) infinite;
}

@keyframes nx-live-pulse {
  0%,
  100% {
    opacity: 0.4;
  }
  50% {
    opacity: 1;
  }
}

.nx-live-timer {
  font-family: var(--font-mono);
  color: var(--text-muted);
}

/* ── 论文行式列表 ── */
.nx-paper-list {
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-panel);
  overflow: hidden;
}

.nx-paper-row {
  padding: var(--space-3) var(--space-4);
  border-top: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.nx-paper-row:first-child {
  border-top: none;
}

.nx-pr-meta {
  display: flex;
  gap: var(--space-3);
  font-family: var(--font-mono);
  font-size: var(--caption-size);
  color: var(--text-muted);
}

.nx-pr-title {
  margin: 0;
  font-size: var(--ui-md-size);
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.45;
}

.nx-pr-authors {
  margin: 0;
  font-size: var(--caption-size);
  color: var(--text-secondary);
  line-height: var(--caption-line);
}

.nx-pr-abstract {
  margin: 0;
  font-size: var(--caption-size);
  color: var(--text-muted);
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.nx-pr-link {
  font-size: var(--caption-size);
  color: var(--nexus-accent);
  display: inline-flex;
  align-items: center;
  gap: 3px;
  text-decoration: none;
}

.nx-pr-link:hover {
  text-decoration: underline;
}

/* ── 复现规划卡 + 未执行状态卡 ── */
.nx-repro-card {
  border: 1px solid var(--nexus-accent-line);
  background: var(--nexus-accent-soft);
  border-radius: var(--radius-md);
  padding: var(--space-4);
}

/* M3 产物卡：write_artifact 真实文件的下载入口（沿用回应区卡片体系） */
.nx-artifact-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.nx-artifact-card {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  border: 1px solid var(--border-secondary);
  background: var(--surface-2);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
}

.nx-art-icon {
  color: var(--nexus-accent-strong);
  flex-shrink: 0;
}

.nx-art-meta {
  flex: 1;
  min-width: 0;
}

.nx-art-title {
  font-size: var(--ui-md-size);
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nx-art-sub {
  font-size: var(--caption-size);
  color: var(--text-secondary);
}

.nx-dv-artifact-title {
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* M4 复现运行状态卡：阶段流水 + 确定性判定（沿用回应区卡片体系） */
.nx-repro-live {
  border: 1px solid var(--nexus-accent-line);
  background: var(--nexus-accent-soft);
  border-radius: var(--radius-md);
  padding: var(--space-4);
  margin-top: var(--space-2);
}

.nx-rl-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}

.nx-rl-icon {
  color: var(--nexus-accent-strong);
  flex-shrink: 0;
}

.nx-rl-title {
  font-weight: 600;
  font-size: var(--ui-md-size);
  color: var(--text-primary);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nx-rl-status {
  font-size: var(--caption-size);
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--surface-3, var(--surface-2));
  color: var(--text-secondary);
}

.nx-rl-status.succeeded {
  color: var(--success);
}

.nx-rl-status.failed,
.nx-rl-status.rejected {
  color: var(--danger, var(--text-secondary));
}

.nx-rl-stages {
  margin: var(--space-2) 0;
  padding-left: var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.nx-rl-stages li {
  font-size: var(--caption-size);
  color: var(--text-secondary);
  display: flex;
  justify-content: space-between;
  gap: var(--space-2);
}

.nx-rl-stages li.is-ok .nx-rl-step-meta {
  color: var(--success);
}

.nx-rl-stages li.is-bad .nx-rl-step-meta {
  color: var(--danger, #c0392b);
}

.nx-rl-step-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nx-rl-step-meta {
  flex-shrink: 0;
}

.nx-rl-note {
  font-size: var(--caption-size);
  color: var(--text-secondary);
  margin-top: var(--space-1);
}

/* ── NX-E2/E3 实验控制台（设计板 2026-09-06 v1）：阶段条/步骤表/日志尾 ── */
.nx-cs-head {
  cursor: pointer;
  user-select: none;
  margin-bottom: 0;
}

.nx-repro-live.is-collapsed {
  padding: var(--space-3) var(--space-4);
}

.nx-cs-spacer {
  flex: 1;
}

.nx-cs-elapsed {
  font-size: var(--caption-size);
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
}

.nx-cs-toggle {
  color: var(--text-secondary);
  font-size: var(--caption-size);
  flex-shrink: 0;
}

.nx-cs-stagebar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-3);
  flex-wrap: wrap;
}

.nx-cs-stg {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--caption-size);
  color: var(--text-secondary);
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--surface-3, var(--surface-2));
  white-space: nowrap;
}

.nx-cs-stgn {
  font-variant-numeric: tabular-nums;
}

.nx-cs-stg.is-done {
  color: var(--success);
}

.nx-cs-stg.is-current {
  color: var(--nexus-accent-strong);
  background: var(--nexus-accent-soft);
  border: 1px solid var(--nexus-accent-line);
}

.nx-cs-stg.is-skipped {
  color: var(--text-secondary);
  opacity: 0.65;
}

.nx-cs-stg.is-failed {
  color: var(--danger, #c0392b);
}

.nx-cs-stg.is-pending {
  opacity: 0.6;
}

.nx-cs-stgline {
  flex: 0 0 14px;
  height: 1px;
  background: var(--border-secondary);
}

.nx-cs-stgline.is-done {
  background: var(--success);
}

.nx-cs-sec {
  margin-top: var(--space-3);
}

.nx-cs-sech {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-2);
  font-size: var(--ui-sm-size, var(--caption-size));
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: var(--space-1);
}

.nx-cs-secn {
  font-weight: 400;
  font-size: var(--caption-size);
  color: var(--text-secondary);
}

.nx-cs-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--caption-size);
}

.nx-cs-table th {
  text-align: left;
  font-weight: 500;
  color: var(--text-secondary);
  padding: var(--space-1) var(--space-2);
  border-bottom: 1px solid var(--border-secondary);
}

.nx-cs-table td {
  padding: var(--space-1) var(--space-2);
  border-bottom: 1px solid var(--border-secondary);
  color: var(--text-secondary);
}

.nx-cs-table tr.is-cur td {
  color: var(--text-primary);
  background: var(--nexus-accent-soft);
}

.nx-cs-table tr.is-bad td.nx-cs-cmd {
  color: var(--danger, #c0392b);
}

.nx-cs-cmd {
  font-family: var(--font-mono, monospace);
  font-size: var(--caption-size);
  max-width: 46%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nx-cs-mono {
  font-family: var(--font-mono, monospace);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.nx-cs-chip {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--surface-3, var(--surface-2));
  color: var(--text-secondary);
  white-space: nowrap;
}

.nx-cs-chip.is-ok {
  color: var(--success);
}

.nx-cs-chip.is-err {
  color: var(--danger, #c0392b);
}

.nx-cs-chip.is-run {
  color: var(--nexus-accent-strong);
}

.nx-cs-chip.is-pend {
  opacity: 0.65;
}

.nx-cs-log {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border-secondary);
  border-radius: var(--radius-sm, var(--radius-md));
  background: var(--surface-3, var(--surface-2));
  color: var(--text-secondary);
  font-family: var(--font-mono, monospace);
  font-size: var(--caption-size);
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 260px;
  overflow-y: auto;
}

.nx-rl-verdict {
  margin-top: var(--space-2);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  border-top: 1px solid var(--border-secondary);
  padding-top: var(--space-2);
}

.nx-rl-verdict.is-pass .nx-rl-verdict-label {
  color: var(--success);
  font-weight: 600;
}

.nx-rl-verdict.is-fail .nx-rl-verdict-label {
  color: var(--danger, #c0392b);
  font-weight: 600;
}

.nx-rl-metric {
  font-size: var(--caption-size);
  color: var(--text-secondary);
}

.nx-rc-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}

.nx-rc-icon {
  color: var(--nexus-accent-strong);
  flex-shrink: 0;
}

.nx-rc-title {
  font-weight: 600;
  font-size: var(--ui-md-size);
  color: var(--text-primary);
}

.nx-rc-meta {
  font-size: var(--caption-size);
  color: var(--text-secondary);
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  margin-bottom: var(--space-3);
  line-height: var(--caption-line);
}

.nx-rc-meta a {
  color: var(--nexus-accent-strong);
}

.nx-rc-steps {
  background: var(--surface-panel);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  padding: var(--space-3);
  font-size: var(--caption-size);
}

.nx-rc-steps-title {
  color: var(--text-muted);
  margin-bottom: var(--space-1);
}

.nx-rc-steps ol {
  margin: 0;
  padding-left: 20px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.nx-rc-steps code {
  font-family: var(--font-mono);
  font-size: var(--caption-size);
  color: var(--text-primary);
}

.nx-rc-footer {
  margin-top: var(--space-3);
}

.nx-repro-status {
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--border-subtle);
  border-left: 2px solid var(--amber-500);
  border-radius: var(--radius-sm);
  background: var(--surface-cool);
}

.nx-rs-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

.nx-rs-icon {
  color: var(--amber-700);
  flex-shrink: 0;
}

.nx-rs-title {
  font-size: var(--ui-sm-size);
  font-weight: 600;
  color: var(--text-primary);
  font-family: var(--font-mono);
}

.nx-rs-desc {
  margin: 0;
  font-size: var(--caption-size);
  line-height: 1.7;
  color: var(--text-secondary);
}

.nx-rs-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  margin-top: 6px;
  font-size: var(--caption-size);
  color: var(--text-muted);
  font-family: var(--font-mono);
}

/* Markdown 正文 */
.nx-markdown-body {
  font-size: var(--body-md-size);
  line-height: 1.75;
  color: var(--text-primary);
  min-width: 0;
}

.nx-markdown-body :deep(h1),
.nx-markdown-body :deep(h2),
.nx-markdown-body :deep(h3) {
  color: var(--ink-900);
  line-height: 1.4;
  margin: 1.2em 0 0.5em;
}

.nx-markdown-body :deep(h1) {
  font-size: var(--title-3-size);
}

.nx-markdown-body :deep(h2),
.nx-markdown-body :deep(h3) {
  font-size: var(--ui-lg-size, var(--body-lg-size, 18px));
}

.nx-markdown-body :deep(p) {
  margin: 0.6em 0;
}

.nx-markdown-body :deep(ul),
.nx-markdown-body :deep(ol) {
  margin: 0.6em 0;
  padding-left: 1.4em;
}

.nx-markdown-body :deep(code) {
  font-family: var(--font-mono);
  font-size: var(--caption-size);
  background: var(--surface-cool);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-xs);
  padding: 1px 5px;
}

.nx-markdown-body :deep(pre) {
  background: var(--code-bg);
  color: var(--code-text);
  border-radius: var(--radius-sm);
  padding: var(--space-3);
  overflow-x: auto;
}

.nx-markdown-body :deep(pre code) {
  background: transparent;
  border: none;
  padding: 0;
  color: inherit;
}

.nx-markdown-body :deep(table) {
  border-collapse: collapse;
  width: 100%;
  font-size: var(--ui-sm-size);
  margin: 0.8em 0;
}

.nx-markdown-body :deep(th),
.nx-markdown-body :deep(td) {
  border: 1px solid var(--border-default);
  padding: 6px 10px;
  text-align: left;
}

.nx-markdown-body :deep(th) {
  background: var(--surface-cool);
}

.nx-markdown-body :deep(a) {
  color: var(--nexus-accent);
}

.nx-markdown-body :deep(blockquote) {
  margin: 0.6em 0;
  padding: var(--space-2) var(--space-4);
  border-left: 3px solid var(--color-focus);
  background: var(--surface-cool);
  color: var(--text-secondary);
}

.nx-turn-failure {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--red-700);
  background: var(--red-100);
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  font-size: var(--ui-sm-size);
}

/* 回答操作条：左侧图标组 + 右侧"由 AI 生成" */
.nx-answer-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  margin-top: 2px;
}

.nx-answer-actions-left {
  display: flex;
  align-items: center;
  gap: 2px;
}

.nx-answer-actions .nx-act-btn {
  min-height: 28px;
  padding: 0 7px;
  color: var(--text-muted);
}

.nx-answer-actions .nx-act-btn:hover:not(:disabled) {
  color: var(--ink-900);
  background: var(--surface-soft);
}

.nx-answer-actions-right {
  font-size: var(--caption-size);
  color: var(--text-muted);
  flex-shrink: 0;
}

/* ── 底部 Composer：外层透明，仅保留一张带阴影的白色卡片悬浮在消息区下缘 ── */
.nx-composer-box {
  padding: 0 var(--space-6) var(--space-5);
  background: transparent;
  flex-shrink: 0;

}

.nx-composer-inner {
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  background: transparent;
  box-shadow: var(--shadow-sm);
  overflow: hidden;
  transition: border-color var(--duration-fast) var(--ease-out),
    box-shadow var(--duration-fast) var(--ease-out);
}

.nx-composer-inner:focus-within {
  border-color: var(--color-focus);
  box-shadow: 0 0 0 2px var(--ink-100);
}

.nx-composer-textarea {
  display: block;
  width: 100%;
  border: none;
  outline: none;
  padding: 12px 14px;
  resize: none;
  font-family: var(--font-sans);
  font-size: var(--body-md-size);
  color: var(--text-primary);
  min-height: 72px;
  max-height: 200px;
  background: transparent;
}

.nx-composer-textarea::placeholder {
  color: var(--text-muted);
}

.nx-composer-toolbar {
  padding: 8px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  border-top: 1px solid var(--border-subtle);
  background: transparent;
}

.nx-engine-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: var(--caption-size);
  color: var(--text-muted);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 模型网关 P0：原生 select，只做最小外观收敛（令牌纪律，不引入新色板）。 */
.nx-model-select {
  max-width: 220px;
  font-size: var(--caption-size);
  color: var(--text-secondary);
  background: transparent;
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  padding: 2px 6px;
}

/* NX-A1 附件 chips：状态即文本，不引入新色板；失败态用现有 danger 文案色。 */
.nx-toolbar-left {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}

.nx-file-hidden {
  display: none;
}

.nx-attach-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 6px 2px 0;
}

.nx-attach-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  max-width: 100%;
  font-size: var(--caption-size);
  color: var(--text-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  padding: 2px 6px;
}

.nx-attach-chip .nx-attach-name {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nx-attach-chip.failed .nx-attach-state {
  color: var(--text-danger, #c0392b);
}

.nx-attach-remove {
  cursor: pointer;
  flex-shrink: 0;
}

.nx-toolbar-right {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}

/* ── 3. 右侧回应区：图标轨 + overlay 抽屉（UX 评审 P0-1） ── */
.nx-detail-zone {
  position: relative;
  display: flex;
  height: 100%;
  flex-shrink: 0;
}

/* 3.1 overlay 抽屉：绝对定位在图标轨左侧，覆盖主工作区，不改变主内容宽度 */
.nx-detail-drawer {
  position: absolute;
  top: 0;
  bottom: 0;
  right: var(--nexus-detail-rail);
  width: var(--nexus-detail-width);
  z-index: 30;
  display: flex;
  flex-direction: column;
  background: var(--surface-page);
  border: 1px solid var(--border-default);
  /* 对齐设计板 Board B：14px 圆角 + shadow-md 级投影，浮层感要出来 */
  border-radius: 14px 0 0 14px;
  box-shadow: -12px 0 32px rgba(16, 26, 49, 0.1);
}

/* 抽屉进出场：--duration-normal（design.md §4 抽屉/面板）。
   进场同时补退场——此前只有 keyframes 进场，关掉是瞬间消失。 */
.nx-drawer-enter-active,
.nx-drawer-leave-active {
  transition:
    opacity var(--duration-normal) var(--ease-out),
    transform var(--duration-normal) var(--ease-out);
}
.nx-drawer-enter-from,
.nx-drawer-leave-to {
  opacity: 0;
  transform: translateX(16px);
}

.nx-dd-head {
  flex-shrink: 0;
  background: var(--surface-panel);
  border-bottom: 1px solid var(--border-subtle);
  border-radius: 14px 0 0 0;
}

/* 标题行：46px（设计板 .drawer-head） */
.nx-dd-bar {
  height: 46px;
  min-height: 46px;
  padding: 0 var(--space-2) 0 var(--space-4);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.nx-dd-title {
  font-size: var(--ui-sm-size);
  font-weight: 650;
  color: var(--ink-900);
}

/* tab 条（设计板 .drawer-tabs / .dt / .dt.active） */
.nx-drawer-tabs {
  display: flex;
  padding: 0 var(--space-2);
  flex-shrink: 0;
}

.nx-dt {
  height: 38px;
  min-height: 38px;
  padding: 0 var(--space-3);
  border-radius: 0;
  gap: 5px;
  font-size: var(--ui-sm-size);
  color: var(--text-secondary);
  position: relative;
}

.nx-dt:hover {
  background: var(--ink-100);
  color: var(--ink-900);
}

.nx-dt.is-active {
  color: var(--nexus-accent-strong);
  font-weight: 650;
}

.nx-dt.is-active::after {
  content: '';
  position: absolute;
  left: 10px;
  right: 10px;
  bottom: -1px;
  height: 2px;
  border-radius: 2px;
  background: var(--nexus-accent);
}

.nx-dt-label {
  white-space: nowrap;
}

.nx-dt-n {
  min-width: 15px;
  height: 15px;
  padding: 0 4px;
  border-radius: var(--radius-full);
  background: var(--nexus-accent-soft);
  color: var(--nexus-accent-strong);
  font-size: 9.5px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.nx-dt-dot {
  width: 7px;
  height: 7px;
  border-radius: var(--radius-full);
  background: var(--amber-500);
}

.nx-dd-hint {
  flex: 1;
  min-width: 0;
  font-size: var(--caption-size);
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.nx-dd-close {
  width: 28px;
  min-width: 28px;
  min-height: 28px;
  padding: 0;
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  flex-shrink: 0;
  transition:
    background var(--duration-fast) var(--ease-out),
    color var(--duration-fast) var(--ease-out);
}

/* 3.2 图标轨 */
.nx-detail-rail {
  width: var(--nexus-detail-rail);
  height: 100%;
  border-left: 1px solid var(--border-default);
  background: var(--surface-page);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-1);
  padding-top: var(--space-3);
  flex-shrink: 0;
}

.nx-dr-item {
  width: 34px;
  min-width: 34px;
  height: 34px;
  min-height: 34px;
  padding: 0;
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  position: relative;
  transition:
    background var(--duration-fast) var(--ease-out),
    color var(--duration-fast) var(--ease-out);
}

.nx-dr-item:hover {
  background: var(--ink-100);
  color: var(--ink-900);
}

.nx-dr-item.is-active {
  background: var(--nexus-accent-soft);
  color: var(--nexus-accent-strong);
}

.nx-dr-item .sfx-btn-label {
  display: none;
}

.nx-dr-icon-wrap {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.nx-dr-badge {
  position: absolute;
  top: -5px;
  right: -8px;
  min-width: 15px;
  padding: 0 3px;
  background: var(--nexus-accent);
  color: #fff;
  border: 1.5px solid var(--surface-page);
  border-radius: var(--radius-full);
  font-size: 10px;
  line-height: 12px;
  font-weight: 600;
  text-align: center;
}

/* 抽屉收起时，新到达的执行记录用琥珀点提示，过程信息不丢失可见性 */
.nx-dr-dot {
  position: absolute;
  top: -3px;
  right: -5px;
  width: 7px;
  height: 7px;
  border-radius: var(--radius-full);
  background: var(--amber-500);
  border: 1.5px solid var(--surface-page);
  animation: nx-dot-pulse 1.6s var(--ease-out) infinite;
}

@keyframes nx-dot-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.35;
  }
}

.nx-dr-foot {
  margin-top: auto;
  padding-bottom: var(--space-3);
}

.nx-dr-foot-line {
  display: block;
  width: 18px;
  height: 1px;
  background: var(--border-default);
}

.nx-detail-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-4);
}

.nx-tab-pane {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.nx-pane-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.nx-section-eyebrow {
  margin: 0;
  font-size: var(--caption-size);
  font-weight: 600;
  color: var(--text-muted);
  letter-spacing: 0.04em;
}

.nx-context-card {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-3);
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
}

.nx-cc-icon {
  color: var(--ink-700);
  margin-top: 2px;
  flex-shrink: 0;
}

.nx-cc-meta {
  flex: 1;
  min-width: 0;
}

.nx-cc-title {
  font-weight: 600;
  font-size: var(--ui-sm-size);
  color: var(--text-primary);
  word-break: break-word;
}

.nx-cc-desc {
  font-size: var(--caption-size);
  color: var(--text-muted);
  line-height: var(--caption-line);
  margin-top: 2px;
}

.nx-cc-change {
  width: 100%;
}

/* 能力状态列表：对齐设计板 Board B（.cap-row / .state-tag）
   —— 每项一张白卡：图标 + 名称（带说明小字）+ 彩色状态胶囊 */
.nx-cap-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.nx-cap-row {
  display: flex;
  align-items: center;
  gap: 9px;
  background: var(--surface-panel);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  padding: 8px 11px;
}

.nx-cap-icon {
  color: var(--text-muted);
  flex-shrink: 0;
}

.nx-cap-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.nx-cap-name {
  font-size: var(--ui-sm-size);
  font-weight: 550;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nx-cap-hint {
  font-size: 10.5px;
  line-height: 1.45;
  color: var(--text-disabled);
}

/* 三态胶囊：绿=已生效 / 琥珀=已连接·未生效 / 灰=未建立（P2-8 同一语义） */
.nx-cap-tag {
  flex-shrink: 0;
  padding: 2.5px 9px;
  border-radius: var(--radius-full);
  font-size: 10.5px;
  font-weight: 650;
  white-space: nowrap;
}

.nx-cap-tag.ready {
  background: var(--green-100);
  color: var(--green-700);
}

.nx-cap-tag.wired {
  background: var(--amber-100);
  color: var(--amber-700);
}

.nx-cap-tag.unwired {
  background: var(--ink-100);
  color: var(--text-muted);
}

/* 执行轨迹（实验记录轨） */
.nx-log-stream {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.nx-log-turn {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.nx-log-turn-label {
  font-size: var(--caption-size);
  color: var(--text-muted);
}

.nx-log-empty {
  font-size: var(--caption-size);
  color: var(--text-muted);
}

.nx-log-item {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: 4px 0 4px var(--space-4);
  border-left: 1px solid var(--border-default);
  margin-left: 3px;
}

.nx-log-dot {
  position: absolute;
  left: -4.5px;
  top: 9px;
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  background: var(--surface-page);
  border: 2px solid var(--ink-500);
}

.nx-log-item.result .nx-log-dot {
  border-color: var(--green-500);
}

.nx-log-title {
  font-size: var(--ui-sm-size);
  color: var(--text-primary);
  line-height: var(--ui-sm-line);
}

.nx-log-time {
  font-family: var(--font-mono);
  font-size: var(--caption-size);
  color: var(--text-muted);
}

.nx-pane-empty {
  font-size: var(--ui-sm-size);
  color: var(--text-muted);
  line-height: 1.7;
  padding: var(--space-4);
  background: var(--surface-cool);
  border: 1px dashed var(--border-default);
  border-radius: var(--radius-md);
}

/* 信息源（行式去盒） */
.nx-src-groups {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.nx-src-head {
  font-size: var(--caption-size);
  font-weight: 600;
  color: var(--text-muted);
  margin-bottom: var(--space-1);
}

.nx-src-row {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 9px 2px;
  border-top: 1px solid var(--border-subtle);
  text-decoration: none;
}

.nx-src-title {
  font-size: var(--ui-sm-size);
  font-weight: 500;
  color: var(--text-primary);
  line-height: 1.5;
}

.nx-src-row:hover .nx-src-title {
  color: var(--nexus-accent);
}

.nx-src-meta {
  font-size: var(--caption-size);
  color: var(--text-muted);
  line-height: var(--caption-line);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.nx-src-note {
  margin: 0;
  padding: 8px 10px;
  border-left: 2px solid var(--amber-500);
  background: var(--surface-cool);
  color: var(--text-secondary);
  font-size: var(--caption-size);
  line-height: 1.6;
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}

/* ── 课程选择 ── */
.nx-course-picker-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.nx-course-picker-item {
  padding: var(--space-3);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition:
    background var(--duration-fast) var(--ease-out),
    border-color var(--duration-fast) var(--ease-out);
}

.nx-course-picker-item:hover {
  background: var(--surface-soft);
}

.nx-course-picker-item.is-selected {
  border-color: var(--color-brand);
  background: var(--color-brand-soft);
}

.nx-cpi-title {
  font-weight: 600;
  font-size: var(--ui-sm-size);
  color: var(--text-primary);
}

.nx-cpi-desc {
  font-size: var(--caption-size);
  color: var(--text-muted);
  margin-top: 2px;
}

/* ── 复现确认（Approval Gate） ── */
.nx-repro-confirm-pane {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.nx-rcp-warn {
  display: flex;
  gap: var(--space-2);
  padding: var(--space-3);
  background: var(--amber-100);
  color: var(--amber-700);
  border-radius: var(--radius-sm);
  font-size: var(--caption-size);
  line-height: var(--caption-line);
}

.nx-rcp-grid {
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  padding: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.nx-rcp-row {
  display: flex;
  justify-content: space-between;
  gap: var(--space-3);
  font-size: var(--ui-sm-size);
}

.nx-rcp-label {
  color: var(--text-muted);
  flex-shrink: 0;
}

.nx-rcp-val {
  color: var(--text-primary);
  text-align: right;
  word-break: break-all;
}

.nx-rcp-confirm-note {
  margin: 0;
  font-size: var(--caption-size);
  color: var(--text-secondary);
  line-height: 1.7;
}

.nx-rcp-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}

/* ══════════ NX-LB2 提案编辑器（调整方案再运行） ══════════ */
.nx-prop-backdrop {
  position: fixed;
  inset: 0;
  z-index: 90;
  background: rgba(18, 24, 38, 0.44);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-6);
}
.nx-prop {
  width: 560px;
  max-width: 100%;
  max-height: min(72vh, 640px);
  display: flex;
  flex-direction: column;
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
  overflow: hidden;
}
.nx-prop-head {
  padding: 14px 18px 12px;
  border-bottom: 1px solid var(--border-default);
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.nx-prop-title { font-size: 14px; font-weight: 600; color: var(--ink-900); }
.nx-prop-sub { font-size: var(--caption-size); color: var(--text-muted); }
.nx-prop-body { flex: 1; overflow-y: auto; padding: 6px 18px 12px; }
.nx-prop-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 12px;
  padding: 9px 0;
  border-bottom: 1px solid var(--border-subtle);
}
.nx-prop-row:last-of-type { border-bottom: 0; }
.nx-prop-k { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.nx-prop-name { font-family: var(--font-mono); font-size: 12px; font-weight: 600; color: var(--text-primary); }
.nx-prop-help { font-size: var(--caption-size); color: var(--text-muted); }
.nx-prop-ctl { display: flex; align-items: center; gap: 8px; }
.nx-prop-input {
  width: 88px;
  height: 28px;
  padding: 0 8px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-xs);
  background: var(--surface-canvas);
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-primary);
}
.nx-prop-input:focus { outline: none; border-color: var(--border-strong); }
.nx-prop-base {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}
.nx-prop-changed {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--ink-900);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-xs);
  padding: 1px 5px;
}
.nx-prop-warn,
.nx-prop-error { margin-top: 10px; font-size: 11.5px; line-height: 1.7; }
.nx-prop-warn { color: var(--text-secondary); }
.nx-prop-error { color: var(--red-700); }
.nx-prop-foot {
  padding: 12px 18px 14px;
  border-top: 1px solid var(--border-default);
  display: flex;
  align-items: center;
  gap: 10px;
}
.nx-prop-count {
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: 0.06em;
  color: var(--text-secondary);
}
.nx-prop-spacer { flex: 1; }
/* ══════════ 切换动画 ══════════
 * 全部只动 opacity / transform，不碰布局属性（避免重排引起的位置抖动）。
 * 时长与缓动一律取 design.md §4 令牌：菜单 120ms、模态与抽屉 200ms。 */

/* 执行模式菜单：向上淡入，--duration-fast */
.nx-exec-fade-enter-active,
.nx-exec-fade-leave-active {
  transition:
    opacity var(--duration-fast) var(--ease-out),
    transform var(--duration-fast) var(--ease-out);
}
.nx-exec-fade-enter-from,
.nx-exec-fade-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

/* 提案编辑器：--duration-normal；面板轻微上浮，遮罩纯淡入 */
.nx-prop-fade-enter-active,
.nx-prop-fade-leave-active {
  transition: opacity var(--duration-normal) var(--ease-out);
}
.nx-prop-fade-enter-from,
.nx-prop-fade-leave-to { opacity: 0; }
.nx-prop-fade-enter-active .nx-prop,
.nx-prop-fade-leave-active .nx-prop {
  transition: transform var(--duration-normal) var(--ease-out);
}
.nx-prop-fade-enter-from .nx-prop,
.nx-prop-fade-leave-to .nx-prop { transform: translateY(8px); }
</style>
