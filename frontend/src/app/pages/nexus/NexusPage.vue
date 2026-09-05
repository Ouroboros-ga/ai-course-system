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
 * - 首屏 Chips 只保留 ready 能力 + 课程绑定；wired/unwired 收进「◇ N 项待接入」popover
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
import { getNexusHealth, getNexusSessionMessages, listNexusSessions, listNexusArtifacts, downloadNexusArtifact } from '@/api/nexus.js'
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
  capabilitiesForMode,
  isReproductionExecutable
} from '@/api/nexusCapabilities.js'

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

function initSessions() {
  sessions.value = loadLocalSessions()
  if (sessions.value.length > 0) {
    activeSessionId.value = sessions.value[0].id
  } else {
    createNewSession()
  }
  // P1-C2/C3：real 模式下拉取服务端持久化会话（best-effort，失败保持本地列表）。
  refreshRemoteSessions()
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
 * ready 能力常驻首屏 Chips；wired / unwired 收进「待接入」popover，
 * 诚实性不丢（状态单一真相源不变），但首屏不再被负面标签刷屏。
 */
const readyCapabilities = computed(() =>
  capabilitiesForMode(activeMode.value).filter((c) => c.state === CAPABILITY_STATE.READY)
)

const pendingCapabilities = computed(() =>
  capabilitiesForMode(activeMode.value).filter((c) => c.state !== CAPABILITY_STATE.READY)
)

function chipLabel(cap) {
  return cap.id === 'web_search' ? 'Web 搜索 · 自动' : cap.label
}

function capHint(id) {
  const cap = capabilitiesForMode(activeMode.value).find((c) => c.id === id)
  if (!cap) return ''
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
  if (cap.state === CAPABILITY_STATE.READY) return '已生效'
  if (cap.state === CAPABILITY_STATE.WIRED) return '已连接 · 未生效'
  return '未建立'
}

function capStateTagText(cap) {
  if (cap.state === CAPABILITY_STATE.READY) return '已生效'
  if (cap.state === CAPABILITY_STATE.WIRED) return '已连接 · 未生效'
  return '未建立'
}

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

function noteActivityArrived() {
  if (!detailDrawerOpen.value || activeDetailTab.value !== 'activity') {
    unseenActivity.value += 1
  }
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

function handleEvent(turn, { event, data }) {
  if (event === 'token') {
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

    // M3：write_artifact 成功 → turn.artifacts（消息流产物卡 + 本机资料计数）
    if (data?.name === 'write_artifact' && data?.status !== 'error') {
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
      message: msg,
      sessionId: currentSession.value.id,
      mode: activeMode.value,
      courseId: currentSession.value.courseId ?? null,
      signal: abortController.signal,
      onEvent: (evt) => handleEvent(turn, evt),
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
              <span class="nx-dv-label">数据源</span>
              <span class="nx-dv-value">
                {{ nexusDataSourceMode === 'demo' ? '演示数据' : '真实' }}
              </span>
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
            <span class="nx-dv-label">本机资料</span>
            <span class="nx-dv-value">{{ localResourcesSummary }}</span>
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

          <!-- 模式即工具白名单：切换在菜单里直接可见"能做什么"的变化 -->
          <div v-if="modeDropdownOpen" class="nx-dropdown-menu">
            <div class="nx-dropdown-head">切换工作模式</div>
            <div
              v-for="(cfg, key) in NEXUS_MODE_CONFIG"
              :key="key"
              class="nx-dropdown-item"
              :class="{ 'is-active': activeMode === key }"
              role="button"
              tabindex="0"
              @click="switchMode(key)"
              @keydown.enter.prevent="switchMode(key)"
              @keydown.space.prevent="switchMode(key)"
            >
              <div class="nx-dropdown-item-icon">
                <component :is="key === NEXUS_MODES.RESEARCH ? Microscope : Sparkles" :size="17" />
              </div>
              <div class="nx-dropdown-item-content">
                <div class="nx-dropdown-item-title">
                  {{ cfg.label }}
                  <Check v-if="activeMode === key" :size="14" class="nx-check" />
                </div>
                <div class="nx-dropdown-item-desc">{{ cfg.desc }}</div>
                <div class="nx-dropdown-tools">
                  <span class="nx-tools-label">可用工具</span>
                  <span v-for="t in cfg.tools" :key="t" class="nx-tool-pill">
                    {{ formatToolDisplayName(t) }}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </header>

      <!-- Context Chips：首屏只保留 ready 能力 + 课程；其余收进「待接入」popover -->
      <!-- Context Chips：只放「本轮回答真正会用到的能力」。
           课程绑定入口已下沉——首屏在启动页引导条，对话中在右栏「上下文」面板
           （UX 评审 P1-4）。它属于低频设置，不该在每轮对话的顶部占一个 chip。 -->
      <div class="nx-context-bar">
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

          <div
            class="nx-chip is-pending nx-flyout"
            role="button"
            tabindex="0"
            :aria-expanded="pendingOpen"
            title="查看未接入能力"
            @click.stop="pendingOpen = !pendingOpen"
            @keydown.enter.stop.prevent="pendingOpen = !pendingOpen"
            @keydown.space.stop.prevent="pendingOpen = !pendingOpen"
          >
            <span class="nx-chip-pending-mark" aria-hidden="true">◇</span>
            <span>{{ pendingCapabilities.length }} 项待接入</span>
            <ChevronDown :size="12" class="nx-chip-caret" :class="{ 'is-open': pendingOpen }" />
            <div v-if="pendingOpen" class="nx-popover">
              <div class="nx-popover-head">以下能力尚未接入运行时，接线后此界面自动生效</div>
              <div v-for="cap in pendingCapabilities" :key="cap.id" class="nx-popover-cap">
                <component :is="capIconMap[cap.icon]" :size="14" class="nx-popover-cap-icon" />
                <div class="nx-popover-cap-body">
                  <div class="nx-popover-cap-name">
                    {{ cap.label }}
                    <span class="nx-cap-tag" :class="cap.state">{{ capStateTagText(cap) }}</span>
                  </div>
                  <div class="nx-popover-cap-hint">{{ capHint(cap.id) }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 状态条：演示说明 / 真实模式健康错误（互斥，同一位置） -->
      <div v-if="nexusDataSourceMode === 'demo'" class="nx-status-strip is-demo" role="status">
        <TriangleAlert :size="13" class="nx-strip-icon" />
        <span>演示数据：由浏览器本地模拟，不会发送到服务器；会话仅保存在本机。</span>
      </div>
      <div v-else-if="healthError" class="nx-status-strip is-error" role="alert">
        <AlertCircle :size="13" class="nx-strip-icon" />
        <span>Nexus 运行时不可达（{{ healthError }}）。可在左栏底部切换回演示数据预览界面。</span>
      </div>

      <!-- 消息流主滚动区 -->
      <div ref="scrollArea" class="nx-chat-scroll">
        <!-- 空状态 -->
        <div v-if="!currentSession?.turns?.length" class="nx-empty-workspace">
          <div class="nx-empty-eyebrow">
            {{ activeMode === NEXUS_MODES.RESEARCH ? 'NEXUS RESEARCH' : 'NEXUS' }}
          </div>
          <h2 class="nx-empty-title">
            {{ activeMode === NEXUS_MODES.RESEARCH ? '从一个研究问题开始' : '从一个问题开始' }}
          </h2>
          <p class="nx-empty-subtitle">
            {{ activeMode === NEXUS_MODES.RESEARCH
              ? '搜索论文、整理证据、比较方法；需要验证时进入实验复现。'
              : 'Nexus 会拆解复杂任务，检索课程资料与 Web，给出可核对的过程与答案。' }}
          </p>

          <!-- 模式预设卡（UX 评审 P1-5）：Mode 切换即工具白名单，
               这个决定必须在打字之前就看得见，而不是藏在顶部的下拉里。 -->
          <div class="nx-mode-cards">
            <div
              v-for="(cfg, key) in NEXUS_MODE_CONFIG"
              :key="key"
              class="nx-mode-card"
              :class="{ 'is-active': activeMode === key }"
              role="button"
              tabindex="0"
              :aria-pressed="activeMode === key"
              @click="switchMode(key)"
              @keydown.enter.prevent="switchMode(key)"
              @keydown.space.prevent="switchMode(key)"
            >
              <div class="nx-mc-head">
                <component
                  :is="key === NEXUS_MODES.RESEARCH ? Microscope : Sparkles"
                  :size="16"
                  class="nx-mc-icon"
                />
                <span class="nx-mc-title">{{ cfg.label }}</span>
                <Check v-if="activeMode === key" :size="14" class="nx-mc-check" />
              </div>
              <p class="nx-mc-desc">{{ cfg.desc }}</p>
              <div class="nx-mc-tools">
                <span v-for="t in cfg.tools" :key="t" class="nx-tool-pill">
                  {{ formatToolDisplayName(t) }}
                </span>
              </div>
            </div>
          </div>

          <!-- 课程绑定引导条（UX 评审 P1-4）：课程入口从顶部 chips 收敛到这里 -->
          <div class="nx-start-course">
            <BookOpen :size="14" class="nx-sc-icon" />
            <span class="nx-sc-text">
              {{
                currentSession?.courseName
                  ? `已绑定课程：${currentSession.courseName}`
                  : '未绑定课程 · 回答只会用到 Web 与通用知识'
              }}
            </span>
            <SfxButton
              variant="secondary"
              size="sm"
              class="nx-sc-btn"
              @click="coursePickerOpen = true"
            >
              {{ currentSession?.courseId ? '更换' : '绑定课程' }}
            </SfxButton>
          </div>

          <div
            class="nx-quick-cards"
            :class="{ 'is-research': activeMode === NEXUS_MODES.RESEARCH }"
          >
            <div
              v-for="sg in emptySuggestions"
              :key="sg.title"
              class="nx-quick-card"
              role="button"
              tabindex="0"
              @click="applySuggestion(sg.prompt)"
              @keydown.enter.prevent="applySuggestion(sg.prompt)"
              @keydown.space.prevent="applySuggestion(sg.prompt)"
            >
              <component :is="capIconMap[sg.icon]" :size="15" class="nx-qc-icon" />
              <div class="nx-qc-text">
                <span class="nx-qc-title">{{ sg.title }}</span>
                <span class="nx-qc-desc">{{ sg.desc }}</span>
              </div>
            </div>
          </div>
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
                <div class="nx-rc-footer">
                  <SfxButton variant="secondary" size="sm" @click="openReproductionModal(turn.reproductionPreset)">
                    <template #icon><FlaskConical :size="13" /></template>
                    尝试复现
                  </SfxButton>
                </div>
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

      <!-- 底部 Composer -->
      <footer class="nx-composer-box">
        <div class="nx-composer-inner">
          <textarea
            v-model="draft"
            class="nx-composer-textarea"
            rows="3"
            placeholder="输入你的问题…"
            :disabled="streaming"
            @keydown.enter.exact.prevent="send"
          />

          <div class="nx-composer-toolbar">
            <span
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

    <!-- ── 3. 右侧回应区：48px 图标轨（常驻）+ 320px overlay 抽屉（按需展开） ──
         图标轨保证「过程与来源始终一键可达」，抽屉默认收起，把 272px 还回主工作区；
         开合状态按设备持久化（page-design.md §3.4）。 -->
    <div v-if="!isTablet && !isMobileOrSmall" class="nx-detail-zone">
      <!-- 3.1 overlay 抽屉：覆盖主工作区右侧，不挤压主内容宽度 -->
      <section v-if="detailDrawerOpen" class="nx-detail-drawer">
        <header class="nx-dd-head">
          <div class="nx-dd-title">
            <component :is="activeDetailMeta.icon" :size="15" class="nx-dd-icon" />
            <span>{{ activeDetailMeta.label }}</span>
          </div>
          <span class="nx-dd-hint">{{ activeDetailMeta.hint }}</span>
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
                <div
                  v-for="cap in capabilitiesForMode(activeMode)"
                  :key="cap.id"
                  class="nx-cap-row"
                  :class="cap.state"
                  :title="capHint(cap.id)"
                >
                  <span class="nx-cap-dot" aria-hidden="true" />
                  <span class="nx-cap-name">{{ cap.label }}</span>
                  <span class="nx-cap-state">{{ capStateText(cap) }}</span>
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
.nx-quick-card:focus-visible,
.nx-chip:focus-visible,
.nx-dv-row:focus-visible,
.nx-dv-subrow:focus-visible,
.nx-process-header:focus-visible,
.nx-dropdown-item:focus-visible,
.nx-session-item:focus-visible,
.nx-course-picker-item:focus-visible,
.nx-dr-item:focus-visible,
.nx-dd-close:focus-visible,
.nx-mode-card:focus-visible {
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

.nx-device-status {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-2);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--surface-soft);
}

.nx-dv-title {
  padding: 0 6px 2px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--text-muted);
}

.nx-dv-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 6px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: var(--caption-size);
  color: var(--text-secondary);
}

.nx-dv-row:hover {
  background: var(--surface-page);
  color: var(--text-primary);
}

/* 无数据时不给「可展开」的错觉：光标与配色都降级 */
.nx-dv-row.is-static {
  cursor: default;
  color: var(--text-muted);
}

.nx-dv-row.is-static:hover {
  background: transparent;
  color: var(--text-muted);
}

.nx-dv-label {
  flex-shrink: 0;
  color: var(--text-muted);
}

.nx-dv-value {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
  color: inherit;
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
  width: 320px;
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
  padding: var(--space-2);
  z-index: 60;
}

.nx-dropdown-head {
  font-size: var(--caption-size);
  color: var(--text-muted);
  padding: var(--space-1) var(--space-2) var(--space-2);
}

.nx-dropdown-item {
  display: flex;
  gap: var(--space-3);
  padding: var(--space-3);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
}

.nx-dropdown-item:hover {
  background: var(--surface-cool);
}

.nx-dropdown-item.is-active {
  background: var(--nexus-accent-soft);
}

.nx-dropdown-item-icon {
  color: var(--ink-700);
  flex-shrink: 0;
  margin-top: 1px;
}

.nx-dropdown-item-content {
  flex: 1;
  min-width: 0;
}

.nx-dropdown-item-title {
  font-weight: 600;
  font-size: var(--ui-md-size);
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

.nx-dropdown-tools {
  margin-top: 6px;
  font-size: var(--caption-size);
  color: var(--text-muted);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
}

.nx-tools-label {
  margin-right: 2px;
}

.nx-tool-pill {
  background: var(--surface-soft);
  padding: 1px 6px;
  border-radius: var(--radius-xs);
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
}

/* ready：唯一允许"激活观感"的能力状态 */
.nx-chip.is-ready {
  border-color: var(--border-strong);
  color: var(--text-primary);
}

/* 待接入聚合入口：虚线 + 菱形标记，中性不报警 */
.nx-chip.is-pending {
  border-style: dashed;
  color: var(--text-secondary);
  cursor: pointer;
  background: transparent;
}

.nx-chip.is-pending:hover {
  border-color: var(--border-strong);
  color: var(--text-primary);
}

.nx-chip-pending-mark {
  color: var(--text-muted);
  font-size: var(--caption-size);
}

.nx-chip-caret {
  color: var(--text-muted);
  transition: transform var(--duration-fast) var(--ease-out);
}

.nx-chip-caret.is-open {
  transform: rotate(180deg);
}

.nx-chip-icon {
  color: var(--text-muted);
}

/* 待接入 popover */
.nx-popover {
  position: absolute;
  top: calc(100% + 8px);
  left: 0;
  width: 312px;
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
  padding: var(--space-2);
  z-index: 60;
}

.nx-popover-head {
  font-size: var(--caption-size);
  color: var(--text-muted);
  padding: var(--space-1) var(--space-2) var(--space-2);
  line-height: var(--caption-line);
}

.nx-popover-cap {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-2);
  border-radius: var(--radius-sm);
}

.nx-popover-cap:hover {
  background: var(--surface-cool);
}

.nx-popover-cap-icon {
  color: var(--text-muted);
  flex-shrink: 0;
  margin-top: 2px;
}

.nx-popover-cap-body {
  flex: 1;
  min-width: 0;
}

.nx-popover-cap-name {
  font-size: var(--ui-sm-size);
  font-weight: 500;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 6px;
}

.nx-cap-tag {
  font-size: var(--caption-size);
  font-weight: 450;
  padding: 0 6px;
  height: 18px;
  line-height: 18px;
  border-radius: var(--radius-xs);
}

.nx-cap-tag.wired {
  background: var(--amber-100);
  color: var(--amber-700);
}

.nx-cap-tag.unwired {
  background: var(--surface-soft);
  color: var(--text-muted);
}

.nx-popover-cap-hint {
  font-size: var(--caption-size);
  color: var(--text-muted);
  margin-top: 2px;
  line-height: var(--caption-line);
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
  padding: var(--space-6);
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

.nx-empty-workspace {
  margin: auto;
  max-width: 640px;
  text-align: center;
  padding: var(--space-8) 0;
}

.nx-empty-eyebrow {
  font-family: var(--font-mono);
  font-size: var(--caption-size);
  letter-spacing: 0.16em;
  color: var(--nexus-accent);
  font-weight: 500;
  margin-bottom: var(--space-3);
}

.nx-empty-title {
  font-size: var(--title-2-size);
  font-weight: 600;
  color: var(--ink-900);
  margin-bottom: var(--space-2);
}

.nx-empty-subtitle {
  font-size: var(--body-md-size);
  color: var(--text-secondary);
  line-height: 1.6;
  margin: 0 auto;
  max-width: 460px;
}

/* 启动页：模式预设卡（UX 评审 P1-5） */
.nx-mode-cards {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
  margin-top: var(--space-6);
  text-align: left;
}

.nx-mode-card {
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--border-default);
  background: var(--surface-panel);
  border-radius: var(--radius-md);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 6px;
  transition:
    border-color var(--duration-fast) var(--ease-out),
    box-shadow var(--duration-fast) var(--ease-out);
}

.nx-mode-card:hover {
  border-color: var(--nexus-accent-line);
}

.nx-mode-card.is-active {
  border-color: var(--nexus-accent);
  box-shadow: inset 0 0 0 1px var(--nexus-accent);
  background: var(--nexus-accent-soft);
}

.nx-mc-head {
  display: flex;
  align-items: center;
  gap: 6px;
}

.nx-mc-icon {
  color: var(--nexus-accent-strong);
  flex-shrink: 0;
}

.nx-mc-title {
  flex: 1;
  min-width: 0;
  font-size: var(--ui-sm-size);
  font-weight: 600;
  color: var(--ink-900);
}

.nx-mc-check {
  color: var(--nexus-accent-strong);
  flex-shrink: 0;
}

.nx-mc-desc {
  margin: 0;
  font-size: var(--caption-size);
  line-height: var(--caption-line);
  color: var(--text-secondary);
}

.nx-mc-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 2px;
}

/* 启动页：课程绑定引导条（UX 评审 P1-4） */
.nx-start-course {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-4);
  padding: var(--space-2) var(--space-3);
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-md);
  background: var(--surface-cool);
  text-align: left;
}

.nx-sc-icon {
  color: var(--text-secondary);
  flex-shrink: 0;
}

.nx-sc-text {
  flex: 1;
  min-width: 0;
  font-size: var(--caption-size);
  color: var(--text-secondary);
}

.nx-sc-btn {
  flex-shrink: 0;
}

.nx-quick-cards {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-3);
  margin-top: var(--space-8);
  text-align: left;
}

.nx-quick-cards.is-research {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.nx-quick-card {
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--border-default);
  background: var(--surface-panel);
  border-radius: var(--radius-md);
  cursor: pointer;
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  transition: border-color var(--duration-fast) var(--ease-out);
}

.nx-quick-card:hover {
  border-color: var(--color-focus);
}

.nx-qc-icon {
  color: var(--text-secondary);
  margin-top: 2px;
  flex-shrink: 0;
}

.nx-qc-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.nx-qc-title {
  font-weight: 600;
  font-size: var(--ui-sm-size);
  color: var(--text-primary);
}

.nx-qc-desc {
  font-size: var(--caption-size);
  color: var(--text-muted);
  line-height: var(--caption-line);
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
  border-left: 1px solid var(--border-default);
  border-right: 1px solid var(--border-default);
  box-shadow: -12px 0 28px rgba(20, 33, 61, 0.07);
  animation: nx-drawer-in var(--duration-normal) var(--ease-out);
}

@keyframes nx-drawer-in {
  from {
    opacity: 0;
    transform: translateX(16px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

.nx-dd-head {
  height: 44px;
  min-height: 44px;
  padding: 0 var(--space-2) 0 var(--space-4);
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}

.nx-dd-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--ui-sm-size);
  font-weight: 600;
  color: var(--ink-900);
  flex-shrink: 0;
}

.nx-dd-icon {
  color: var(--text-secondary);
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

/* 能力状态列表（实验记录轨同语言，取代大数字统计块） */
.nx-cap-list {
  background: var(--surface-cool);
  border: 1px solid var(--border-subtle);
  border-left: 2px solid var(--border-strong);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.nx-cap-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 9px var(--space-3);
  border-top: 1px solid var(--border-subtle);
}

.nx-cap-row:first-child {
  border-top: none;
}

.nx-cap-dot {
  width: 7px;
  height: 7px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

.nx-cap-row.ready .nx-cap-dot {
  background: var(--green-500);
}

.nx-cap-row.wired .nx-cap-dot {
  background: var(--amber-500);
}

.nx-cap-row.unwired .nx-cap-dot {
  background: var(--border-strong);
}

.nx-cap-name {
  flex: 1;
  min-width: 0;
  font-size: var(--ui-sm-size);
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nx-cap-state {
  font-size: var(--caption-size);
  color: var(--text-muted);
  text-align: right;
  flex-shrink: 0;
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
</style>
