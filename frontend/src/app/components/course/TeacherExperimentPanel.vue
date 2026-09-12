<script setup>
/**
 * 教师实验任务设定工作台（v2，2026-09-11 重置版）。
 *
 * 与旧六步向导的差别（用户反馈：题目设置繁琐 + 内容显示不全）：
 * 1) 结构：左侧任务列表 + 右侧编辑器，两列各自滚动。旧版整页 overflow:hidden
 *    而面板没有滚动容器，编辑区一旦超过一屏就被裁掉，题目内容看不到（P0）。
 * 2) 分段：六步线性向导 → 四段（基本信息 / 测试用例 / 运行限制 / 发布检查），
 *    任意跳转，不强制"下一步"。参考解预览、锁定、发布合并成一张检查清单，
 *    它是服务端 ExperimentPublishValidator 的前置条件的客户端镜像。
 * 3) 语言：逗号分隔字符串 → 沙箱语言多选 chip（数据源复用页面已取的
 *    /sandbox/languages，旧版完全没用上）。
 * 4) 知识点：112 个 checkbox 平铺 → 可搜索 + 已选置顶。
 * 5) 测试用例：卡片纵排大表单 → 紧凑行 + 点击展开编辑，权重自动均分，
 *    支持 JSON 批量导入 —— 旧版每加一条要手凑权重到 1.00，凑不齐按钮即禁用。
 * 6) 恢复现场：继续配置时从服务端读回该版本的既有测试集与起始代码，
 *    旧版会把 testCases 重置为两条空默认用例（等于静默清空已填内容）。
 *
 * 版本不可变是服务端事实（PUT /versions/{id} 只改 label / passing_score /
 * writes_formal_evidence，测试集改不了），所以此处把编辑区语义明确为
 * "下一个待创建的版本"，并用脏检查阻止重复创建同内容版本。
 */
import { computed, inject, onMounted, ref, watch } from 'vue'
import {
  Check, Copy, Lock, Play, Plus, Rocket, Search, Trash2, TriangleAlert, Upload,
} from 'lucide-vue-next'
import {
  archiveExperimentDefinition,
  createExperimentDefinition,
  createExperimentVersion,
  getExperimentVersion,
  listExperimentDefinitions,
  listExperimentVersions,
  lockExperimentVersion,
  previewExperimentReferenceSolution,
  publishExperimentDefinition,
  updateExperimentDefinition,
} from '@/api/experiments.js'
import {
  EXPERIMENT_SECTIONS,
  EXPERIMENT_SECTION_LABELS,
  distributeWeights,
  isWeightTotalValid,
  pickTargetVersion,
  resolveExperimentSection,
} from '@/api/experimentPublishWorkflow.js'
import { getActiveKnowledgeGraph } from '@/api/graph.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

const props = defineProps({
  // 沙箱真实支持的语言（页面已从 /sandbox/languages 取回）。
  languages: { type: Array, default: () => [] },
  sandboxAvailable: { type: Boolean, default: false },
})

const courseContext = inject('courseContext')
const courseId = computed(() => courseContext.courseId.value)

// ── 常量（服务端镜像） ────────────────────────────────────────────────
// 与 backend/app/services/sandbox_client.py ALLOWED_LANGUAGES 对齐，仅用于显示名。
const LANGUAGE_LABELS = {
  python3: 'Python 3',
  c: 'C',
  cpp: 'C++',
  java: 'Java',
  javascript: 'JavaScript',
  go: 'Go',
  rust: 'Rust',
  csharp: 'C#',
  ruby: 'Ruby',
  php: 'PHP',
}

const PUBLISH_META = {
  draft: { label: '草稿', tone: 'amber' },
  published: { label: '已发布', tone: 'green' },
  archived: { label: '已归档', tone: 'neutral' },
}

const GROUP_ORDER = [
  { key: 'draft', label: '草稿' },
  { key: 'published', label: '已发布' },
  { key: 'archived', label: '已归档' },
]

// 资源预设的取值都落在服务端边界内（cpu 1–30 / mem 16000–512000 / wall 1–60 /
// process 1–120 / file 1–8192，见 experiments.py VersionCreateRequest）。
const LIMIT_PRESETS = [
  {
    key: 'strict',
    label: '严格',
    note: '小规模算法题',
    values: { cpuTimeLimit: 2, memoryLimit: 64000, wallTimeLimit: 5, maxProcesses: 16, maxFileSize: 512 },
  },
  {
    key: 'standard',
    label: '标准',
    note: '默认，与 Judge0 课程默认一致',
    values: { cpuTimeLimit: 5, memoryLimit: 128000, wallTimeLimit: 10, maxProcesses: 30, maxFileSize: 1024 },
  },
  {
    key: 'loose',
    label: '宽松',
    note: '含较大输入或解释型语言',
    values: { cpuTimeLimit: 10, memoryLimit: 256000, wallTimeLimit: 20, maxProcesses: 60, maxFileSize: 2048 },
  },
]

const LIMIT_FIELDS = [
  { key: 'cpuTimeLimit', label: 'CPU 秒数', min: 1, max: 30, unit: 's' },
  { key: 'memoryLimit', label: '内存', min: 16000, max: 512000, unit: 'KB' },
  { key: 'wallTimeLimit', label: '墙钟秒数', min: 1, max: 60, unit: 's' },
  { key: 'maxProcesses', label: '最大进程数', min: 1, max: 120, unit: '' },
  { key: 'maxFileSize', label: '最大文件', min: 1, max: 8192, unit: 'KB' },
]

// ── 任务列表 ─────────────────────────────────────────────────────────
const listState = ref('loading')
const listError = ref('')
const tasks = ref([])
const keyword = ref('')

const taskGroups = computed(() => {
  const needle = keyword.value.trim().toLowerCase()
  const matched = tasks.value.filter((task) => {
    if (!needle) return true
    return String(task.title || '').toLowerCase().includes(needle)
      || String(task.description || '').toLowerCase().includes(needle)
  })
  return GROUP_ORDER
    .map((group) => ({
      ...group,
      items: matched.filter((task) => (task.publish_status || 'draft') === group.key),
    }))
    .filter((group) => group.items.length > 0)
})

const taskCount = computed(() => taskGroups.value.reduce((sum, group) => sum + group.items.length, 0))

// ── 编辑器状态 ───────────────────────────────────────────────────────
const creating = ref(false)
const currentId = ref('')
const section = ref('basics')
const error = ref('')
const saving = ref(false)
const busyAction = ref('')

const current = computed(() => tasks.value.find((task) => task.experiment_id === currentId.value) ?? null)
const editorOpen = computed(() => creating.value || Boolean(current.value))

const basicsForm = ref({ title: '', description: '', max_attempts: 3, cooldown_minutes: 30 })
const selectedLanguages = ref([])
const selectedKnowledgeIds = ref([])

const testsForm = ref({
  label: 'v1',
  writesFormalEvidence: true,
  autoWeight: true,
  cases: [],
})
const limitsForm = ref({
  cpuTimeLimit: 5,
  memoryLimit: 128000,
  wallTimeLimit: 10,
  maxProcesses: 30,
  maxFileSize: 1024,
})
const starterCode = ref({})
const starterLanguage = ref('')
const referenceForm = ref({ language: '', source_code: '' })
const preview = ref(null)
const expandedCaseIds = ref([])
const showImport = ref(false)
const importText = ref('')
const importError = ref('')

const versions = ref([])
const versionDetail = ref(null)
const loadedSnapshot = ref('')

// ── 语言 ─────────────────────────────────────────────────────────────
const languageOptions = computed(() => {
  const set = new Set([...props.languages, ...selectedLanguages.value])
  return [...set].filter(Boolean)
})

function languageLabel(language) {
  return LANGUAGE_LABELS[language] ?? language
}

function toggleLanguage(language) {
  const list = selectedLanguages.value
  const index = list.indexOf(language)
  if (index >= 0) {
    if (list.length === 1) return // 至少保留一种语言，否则无法进入版本创建
    list.splice(index, 1)
  } else {
    list.push(language)
  }
  if (!list.includes(starterLanguage.value)) starterLanguage.value = list[0] ?? ''
  if (!list.includes(referenceForm.value.language)) referenceForm.value.language = list[0] ?? ''
}

// ── 知识点 ───────────────────────────────────────────────────────────
const knowledgeNodes = ref([])
const knowledgeState = ref('idle')
const knowledgeKeyword = ref('')

const filteredKnowledge = computed(() => {
  const needle = knowledgeKeyword.value.trim().toLowerCase()
  const selected = new Set(selectedKnowledgeIds.value)
  const nodes = needle
    ? knowledgeNodes.value.filter((node) => node.title.toLowerCase().includes(needle))
    : knowledgeNodes.value
  // 已选置顶：勾完后立刻能看见自己选了什么，不必在 112 个节点里回找。
  return [...nodes].sort((a, b) => {
    const sa = selected.has(a.id) ? 0 : 1
    const sb = selected.has(b.id) ? 0 : 1
    return sa - sb || a.title.localeCompare(b.title, 'zh-Hans-CN')
  })
})

const selectedKnowledgeTitles = computed(() => selectedKnowledgeIds.value
  .map((id) => knowledgeNodes.value.find((node) => node.id === id)?.title ?? `#${id}`))

function toggleKnowledgeNode(id) {
  const list = selectedKnowledgeIds.value
  const index = list.indexOf(id)
  if (index >= 0) list.splice(index, 1)
  else list.push(id)
}

async function loadKnowledgeNodes() {
  knowledgeState.value = 'loading'
  try {
    const data = await getActiveKnowledgeGraph(courseId.value)
    const raw = data?.nodes ?? data?.items ?? []
    knowledgeNodes.value = (Array.isArray(raw) ? raw : [])
      .map((node) => ({
        id: Number(node?.id ?? node?.node_id),
        title: String(node?.title ?? node?.label ?? node?.node_key ?? ''),
      }))
      .filter((node) => Number.isInteger(node.id) && node.title)
    knowledgeState.value = knowledgeNodes.value.length ? 'ready' : 'empty'
  } catch {
    knowledgeNodes.value = []
    knowledgeState.value = 'error'
  }
}

// ── 测试用例 ─────────────────────────────────────────────────────────
// 用例身份用自增 id，不用数组下标：删一行不会让后续行的 key 位移（旧版以 index
// 作 key，删除时整段 DOM 重建，中文输入法的候选状态会被打断）。
let caseSeq = 0
function newCase({ name = '公开样例', hidden = false } = {}) {
  caseSeq += 1
  return { id: `c${caseSeq}`, case_name: name, stdin: '', expected_stdout: '', is_hidden: hidden, weight: 0 }
}

function defaultCases() {
  return [newCase({ name: '公开样例', hidden: false }), newCase({ name: '隐藏用例', hidden: true })]
}

const caseCount = computed(() => testsForm.value.cases.length)
const weightTotal = computed(() => testsForm.value.cases
  .reduce((sum, item) => sum + Number(item.weight || 0), 0))
const weightValid = computed(() => isWeightTotalValid(testsForm.value.cases))
const weightDelta = computed(() => Number((1 - weightTotal.value).toFixed(2)))
// 服务端只校验权重总和为 1，不校验单条 > 0；而在"全量通过"规则下，权重为 0 的
// 用例就算失败也不影响判定 —— 等于一条静默失效的用例。这里只提示、不拦截，
// 避免客户端的规则比服务端更严。
const zeroWeightCount = computed(() => testsForm.value.cases
  .filter((item) => Number(item.weight || 0) <= 0).length)

function applyAutoWeights() {
  if (!testsForm.value.autoWeight) return
  const weights = distributeWeights(testsForm.value.cases.length)
  testsForm.value.cases.forEach((item, index) => { item.weight = weights[index] ?? 0 })
}

function addCase(hidden) {
  testsForm.value.cases.push(newCase({ name: hidden ? '隐藏用例' : '公开样例', hidden }))
  applyAutoWeights()
}

function duplicateCase(index) {
  const source = testsForm.value.cases[index]
  const copy = newCase({ name: `${source.case_name} 副本`, hidden: source.is_hidden })
  copy.stdin = source.stdin
  copy.expected_stdout = source.expected_stdout
  testsForm.value.cases.splice(index + 1, 0, copy)
  applyAutoWeights()
}

function removeCase(index) {
  if (testsForm.value.cases.length <= 1) return
  const [removed] = testsForm.value.cases.splice(index, 1)
  expandedCaseIds.value = expandedCaseIds.value.filter((id) => id !== removed.id)
  applyAutoWeights()
}

function isExpanded(testCase) {
  return expandedCaseIds.value.includes(testCase.id)
}

function toggleExpanded(testCase) {
  const list = expandedCaseIds.value
  const index = list.indexOf(testCase.id)
  if (index >= 0) list.splice(index, 1)
  else list.push(testCase.id)
}

function previewText(value) {
  const text = String(value ?? '')
  if (!text) return ''
  const lines = text.split('\n')
  return lines.length > 1 ? `${lines[0]} ⋯+${lines.length - 1} 行` : lines[0]
}

function importCases() {
  importError.value = ''
  let parsed
  try {
    parsed = JSON.parse(importText.value)
  } catch {
    importError.value = '不是合法 JSON。请粘贴数组，例如 [{"case_name":"样例 1","stdin":"1 2","expected_stdout":"3"}]。'
    return
  }
  const raw = Array.isArray(parsed) ? parsed : parsed?.cases
  if (!Array.isArray(raw) || raw.length === 0) {
    importError.value = '未解析到用例数组。'
    return
  }
  const imported = raw.slice(0, 50).map((item, index) => {
    const testCase = newCase({
      name: String(item?.case_name ?? item?.name ?? `导入用例 ${index + 1}`).slice(0, 200),
      hidden: Boolean(item?.is_hidden ?? item?.hidden ?? false),
    })
    testCase.stdin = String(item?.stdin ?? item?.input ?? '')
    testCase.expected_stdout = String(item?.expected_stdout ?? item?.output ?? '')
    testCase.weight = Number(item?.weight ?? 0)
    return testCase
  })
  testsForm.value.cases = imported
  expandedCaseIds.value = []
  applyAutoWeights()
  if (raw.length > 50) {
    importError.value = `一次最多导入 50 条，已截取前 50 条（原 ${raw.length} 条）。`
  } else {
    showImport.value = false
    importText.value = ''
  }
}

// ── 版本 ─────────────────────────────────────────────────────────────
const targetVersion = computed(() => pickTargetVersion(versions.value))
const nextVersionNumber = computed(() => versions.value
  .reduce((max, version) => Math.max(max, Number(version.version_number ?? 0)), 0) + 1)

const activeVersion = computed(() => versions.value.find((version) => version.is_active === true) ?? null)
const previewVerified = computed(() => Boolean(targetVersion.value?.reference_preview_verified_at)
  || preview.value?.accepted === true)
const targetLocked = computed(() => Boolean(targetVersion.value?.is_locked))

function cleanStarterCode() {
  const out = {}
  for (const language of selectedLanguages.value) {
    const code = String(starterCode.value[language] ?? '')
    if (code.trim()) out[language] = code
  }
  return out
}

/** 当前编辑区的规范化快照：用于判断"再创建版本是否会产出同内容版本"。 */
function snapshot() {
  return JSON.stringify({
    label: testsForm.value.label,
    evidence: testsForm.value.writesFormalEvidence,
    limits: { ...limitsForm.value },
    starter: cleanStarterCode(),
    cases: testsForm.value.cases.map((item) => ({
      case_name: item.case_name,
      stdin: item.stdin,
      expected_stdout: item.expected_stdout,
      is_hidden: Boolean(item.is_hidden),
      weight: Number(item.weight),
    })),
  })
}

const isDirty = computed(() => snapshot() !== loadedSnapshot.value)

const canCreateVersion = computed(() => Boolean(
  caseCount.value
  && weightValid.value
  && selectedLanguages.value.length
  && (!targetVersion.value || isDirty.value),
))

const createVersionHint = computed(() => {
  if (!selectedLanguages.value.length) return '先在「基本信息」中选择至少一种允许语言。'
  if (!caseCount.value) return '至少需要一条测试用例。'
  if (!weightValid.value) return `权重合计 ${weightTotal.value.toFixed(2)}，服务端要求精确等于 1.00。`
  if (targetVersion.value && !isDirty.value) {
    return `${targetVersion.value.label} 内容未改动，无需重复创建版本。改动测试集或资源限制后即可创建 v${nextVersionNumber.value}。`
  }
  return `将以 v${nextVersionNumber.value} 固化当前测试集与资源限制；创建后测试集不可修改。`
})

// ── 发布检查清单（服务端 ExperimentPublishValidator 的镜像） ───────────
const checklist = computed(() => {
  const task = current.value
  const version = targetVersion.value
  return [
    {
      key: 'definition',
      label: '任务定义已保存',
      detail: task ? `${task.title}｜尝试 ${task.max_attempts} 次｜冷却 ${task.cooldown_minutes} 分钟` : '尚未创建',
      state: task ? 'done' : 'blocked',
      action: { label: '编辑基本信息', section: 'basics' },
    },
    {
      key: 'languages',
      label: '语言白名单非空且被沙箱支持',
      detail: selectedLanguages.value.length
        ? selectedLanguages.value.map(languageLabel).join('、')
        : '尚未选择语言',
      state: selectedLanguages.value.length ? 'done' : 'blocked',
      action: { label: '选择语言', section: 'basics' },
    },
    {
      key: 'tests',
      label: '测试用例权重合计 1.00',
      detail: version
        ? `${version.label} 已固化测试集`
        : `当前草稿 ${caseCount.value} 条，合计 ${weightTotal.value.toFixed(2)}`,
      state: version ? 'done' : (weightValid.value && caseCount.value ? 'ready' : 'blocked'),
      action: { label: '编辑测试用例', section: 'tests' },
    },
    {
      key: 'version',
      label: '已创建版本',
      detail: version ? `${version.label}（v${version.version_number}）` : '尚未创建版本',
      state: version ? 'done' : 'blocked',
      action: { label: '去创建版本', section: 'tests' },
    },
    {
      key: 'preview',
      label: '参考解预览全量通过',
      detail: previewVerified.value
        ? `已通过${preview.value ? ` ${preview.value.passed_count}/${preview.value.total_count}` : ''}`
        : '未通过，锁定的前提条件',
      state: previewVerified.value ? 'done' : (version ? 'ready' : 'blocked'),
      action: { label: '运行参考解预览', section: 'publish' },
    },
    {
      key: 'lock',
      label: '版本已锁定并生效',
      detail: targetLocked.value
        ? '锁定后测试集不可修改'
        : '锁定同时会把该版本设为学生使用的默认版本',
      state: targetLocked.value ? 'done' : (previewVerified.value ? 'ready' : 'blocked'),
      action: { label: '锁定版本', section: 'publish' },
    },
    {
      key: 'sandbox',
      label: '评测机健康检查通过',
      detail: props.sandboxAvailable ? `沙箱可用，支持 ${props.languages.length} 种语言` : '沙箱当前不可用，发布将被服务端拒绝',
      state: props.sandboxAvailable ? 'done' : 'blocked',
      action: null,
    },
    {
      key: 'publish',
      label: '发布给学生',
      detail: task?.publish_status === 'published' ? '已发布，可继续创建新版本' : '发布时服务端会复校以上全部条件',
      state: task?.publish_status === 'published' ? 'done' : (targetLocked.value && previewVerified.value ? 'ready' : 'blocked'),
      action: null,
    },
  ]
})

const canLock = computed(() => Boolean(targetVersion.value && !targetLocked.value && previewVerified.value))
const canPublish = computed(() => Boolean(
  current.value
  && current.value.publish_status !== 'published'
  && targetVersion.value?.is_active
  && targetLocked.value
  && previewVerified.value,
))

// ── 数据加载 ─────────────────────────────────────────────────────────
async function loadTasks() {
  listState.value = 'loading'
  listError.value = ''
  try {
    const data = await listExperimentDefinitions(courseId.value)
    tasks.value = data?.items ?? []
    listState.value = tasks.value.length ? 'ready' : 'empty'
  } catch (requestError) {
    listError.value = requestError?.message || '实验任务读取失败'
    listState.value = 'error'
  }
}

async function loadVersions() {
  if (!currentId.value) {
    versions.value = []
    return
  }
  try {
    const data = await listExperimentVersions(courseId.value, currentId.value)
    versions.value = data?.items ?? []
  } catch {
    versions.value = []
  }
}

/** 把服务端某版本的既有内容读回编辑区（旧版会把测试集重置为空默认用例）。 */
async function restoreFromVersion(versionId) {
  versionDetail.value = null
  try {
    versionDetail.value = await getExperimentVersion(courseId.value, versionId)
  } catch {
    return false
  }
  const detail = versionDetail.value
  if (!detail) return false
  testsForm.value.cases = (detail.test_cases ?? []).map((item) => {
    caseSeq += 1
    return {
      id: `s${caseSeq}`,
      case_name: item.case_name ?? '',
      stdin: item.stdin ?? '',
      expected_stdout: item.expected_stdout ?? '',
      is_hidden: Boolean(item.is_hidden),
      weight: Number(item.weight ?? 0),
    }
  })
  limitsForm.value = {
    cpuTimeLimit: Number(detail.cpu_time_limit ?? 5),
    memoryLimit: Number(detail.memory_limit ?? 128000),
    wallTimeLimit: Number(detail.wall_time_limit ?? 10),
    maxProcesses: Number(detail.max_processes ?? 30),
    maxFileSize: Number(detail.max_file_size ?? 1024),
  }
  testsForm.value.writesFormalEvidence = detail.writes_formal_evidence !== false
  if (detail.starter_code && typeof detail.starter_code === 'object') {
    starterCode.value = { ...detail.starter_code }
  }
  // 恢复的权重若恰好等于自动均分结果，就保持"自动"开关开启，语义一致。
  const autoWeights = distributeWeights(testsForm.value.cases.length)
  testsForm.value.autoWeight = testsForm.value.cases.length > 0
    && testsForm.value.cases.every((item, index) => Math.abs(Number(item.weight) - (autoWeights[index] ?? 0)) <= 1e-9)
  return true
}

/** 编辑区就绪：把"下一个待创建版本"的表单填成可提交状态，并记录基线快照。 */
async function primeEditor(task, preferSection) {
  section.value = preferSection
  expandedCaseIds.value = []
  showImport.value = false
  importError.value = ''
  importText.value = ''
  preview.value = null
  versions.value = []
  versionDetail.value = null

  await loadVersions()

  testsForm.value.label = `v${nextVersionNumber.value}`
  const target = targetVersion.value
  let restored = false
  if (target) restored = await restoreFromVersion(target.version_id)

  if (!restored) {
    testsForm.value.cases = defaultCases()
    testsForm.value.autoWeight = true
    testsForm.value.writesFormalEvidence = true
    applyAutoWeights()
  }

  if (!selectedLanguages.value.length && props.languages.length) {
    selectedLanguages.value = [props.languages[0]]
  }
  starterLanguage.value = selectedLanguages.value[0] ?? ''
  referenceForm.value.language = selectedLanguages.value
    .includes(referenceForm.value.language) ? referenceForm.value.language : (selectedLanguages.value[0] ?? '')

  testsForm.value.label = `v${nextVersionNumber.value}`
  // 基线快照必须在此刻记录：之后任何编辑都会让 isDirty 变 true，从而放开
  // "创建新版本"（内容未改动时按钮保持禁用，避免产出重复版本）。
  loadedSnapshot.value = snapshot()
}

async function openTask(task) {
  creating.value = false
  currentId.value = task.experiment_id
  error.value = ''
  basicsForm.value = {
    title: task.title ?? '',
    description: task.description ?? '',
    max_attempts: task.max_attempts ?? 3,
    cooldown_minutes: task.cooldown_minutes ?? 30,
  }
  selectedLanguages.value = Array.isArray(task.language_whitelist) ? [...task.language_whitelist] : []
  selectedKnowledgeIds.value = Array.isArray(task.knowledge_node_ids) ? [...task.knowledge_node_ids] : []
  starterCode.value = (task.starter_code && typeof task.starter_code === 'object')
    ? { ...task.starter_code }
    : {}
  referenceForm.value.source_code = ''
  await primeEditor(task, resolveExperimentSection(task))
}

function startNewTask() {
  creating.value = true
  currentId.value = ''
  section.value = 'basics'
  error.value = ''
  basicsForm.value = { title: '', description: '', max_attempts: 3, cooldown_minutes: 30 }
  selectedLanguages.value = props.languages.length ? [props.languages[0]] : []
  selectedKnowledgeIds.value = []
  starterCode.value = {}
  referenceForm.value = { language: selectedLanguages.value[0] ?? '', source_code: '' }
  versions.value = []
  versionDetail.value = null
  preview.value = null
  limitsForm.value = {
    cpuTimeLimit: 5,
    memoryLimit: 128000,
    wallTimeLimit: 10,
    maxProcesses: 30,
    maxFileSize: 1024,
  }
  testsForm.value = {
    label: 'v1',
    writesFormalEvidence: true,
    autoWeight: true,
    cases: defaultCases(),
  }
  applyAutoWeights()
  expandedCaseIds.value = []
  loadedSnapshot.value = snapshot()
}

// ── 写入动作 ─────────────────────────────────────────────────────────
function describeError(requestError, fallback) {
  return requestError?.message || fallback
}

async function createDefinition() {
  const title = basicsForm.value.title.trim()
  if (!title) {
    error.value = '请填写任务名称。'
    return
  }
  saving.value = true
  busyAction.value = 'create'
  error.value = ''
  try {
    const definition = await createExperimentDefinition(courseId.value, {
      title,
      description: basicsForm.value.description.trim(),
      language_whitelist: [...selectedLanguages.value],
      knowledge_node_ids: selectedKnowledgeIds.value.filter((id) => Number.isInteger(id)),
      max_attempts: Number(basicsForm.value.max_attempts),
      cooldown_minutes: Number(basicsForm.value.cooldown_minutes),
    })
    await loadTasks()
    creating.value = false
    currentId.value = definition?.experiment_id ?? ''
    const task = tasks.value.find((item) => item.experiment_id === currentId.value)
    if (task) await primeEditor(task, 'tests')
    else section.value = 'tests'
  } catch (requestError) {
    error.value = describeError(requestError, '创建实验任务失败')
  } finally {
    saving.value = false
    busyAction.value = ''
  }
}

async function saveBasics() {
  if (!current.value) return
  if (!basicsForm.value.title.trim()) {
    error.value = '请填写任务名称。'
    return
  }
  saving.value = true
  busyAction.value = 'basics'
  error.value = ''
  try {
    await updateExperimentDefinition(courseId.value, current.value.experiment_id, {
      title: basicsForm.value.title.trim(),
      description: basicsForm.value.description.trim(),
      language_whitelist: [...selectedLanguages.value],
      max_attempts: Number(basicsForm.value.max_attempts),
      cooldown_minutes: Number(basicsForm.value.cooldown_minutes),
    })
    await loadTasks()
    // 语言可能变了：起始代码按语言取用，同步一次引用语言。
    if (!selectedLanguages.value.includes(referenceForm.value.language)) {
      referenceForm.value.language = selectedLanguages.value[0] ?? ''
    }
  } catch (requestError) {
    error.value = describeError(requestError, '保存基本信息失败')
  } finally {
    saving.value = false
    busyAction.value = ''
  }
}

async function createVersion() {
  if (!current.value || !canCreateVersion.value) return
  saving.value = true
  busyAction.value = 'version'
  error.value = ''
  try {
    const payload = {
      label: testsForm.value.label,
      ...limitsForm.value,
      writesFormalEvidence: testsForm.value.writesFormalEvidence,
      starterCode: cleanStarterCode(),
      testCases: testsForm.value.cases,
    }
    const version = await createExperimentVersion(
      courseId.value,
      current.value.experiment_id,
      payload,
    )
    await loadVersions()
    testsForm.value.label = `v${nextVersionNumber.value}`
    // 新版本用的就是当前内容，所以基线重置后再创建同内容版本会被拦住。
    loadedSnapshot.value = snapshot()
    if (version?.version_id) {
      versionDetail.value = { ...version }
    }
    section.value = 'publish'
  } catch (requestError) {
    error.value = describeError(requestError, '创建实验版本失败')
  } finally {
    saving.value = false
    busyAction.value = ''
  }
}

async function runReferencePreview() {
  const version = targetVersion.value
  if (!version || !referenceForm.value.source_code.trim()) return
  saving.value = true
  busyAction.value = 'preview'
  error.value = ''
  try {
    preview.value = await previewExperimentReferenceSolution(
      courseId.value,
      version.version_id,
      {
        language: referenceForm.value.language,
        source_code: referenceForm.value.source_code,
      },
    )
    if (preview.value?.accepted) await loadVersions()
  } catch (requestError) {
    preview.value = null
    error.value = describeError(requestError, '参考解预览失败')
  } finally {
    saving.value = false
    busyAction.value = ''
  }
}

async function lockVersion() {
  const version = targetVersion.value
  if (!version || !canLock.value) return
  saving.value = true
  busyAction.value = 'lock'
  error.value = ''
  try {
    await lockExperimentVersion(courseId.value, version.version_id)
    await loadVersions()
  } catch (requestError) {
    error.value = describeError(requestError, '锁定实验版本失败')
  } finally {
    saving.value = false
    busyAction.value = ''
  }
}

async function publish() {
  if (!canPublish.value) return
  saving.value = true
  busyAction.value = 'publish'
  error.value = ''
  try {
    await publishExperimentDefinition(courseId.value, current.value.experiment_id)
    await loadTasks()
    await loadVersions()
    section.value = 'publish'
  } catch (requestError) {
    error.value = describeError(
      requestError,
      '发布实验失败。服务端会复校语言白名单、测试权重、版本锁定、参考解预览与评测机健康状态。',
    )
  } finally {
    saving.value = false
    busyAction.value = ''
  }
}

async function archiveTask() {
  if (!current.value) return
  saving.value = true
  busyAction.value = 'archive'
  error.value = ''
  try {
    await archiveExperimentDefinition(courseId.value, current.value.experiment_id)
    const archivedId = current.value.experiment_id
    await loadTasks()
    if (!tasks.value.some((task) => task.experiment_id === archivedId)) {
      currentId.value = ''
      versions.value = []
    }
  } catch (requestError) {
    error.value = describeError(requestError, '归档实验任务失败')
  } finally {
    saving.value = false
    busyAction.value = ''
  }
}

function goToSection(key) {
  if (!editorOpen.value) return
  section.value = key
}

function applyPreset(preset) {
  limitsForm.value = { ...preset.values }
}

watch(() => selectedLanguages.value.length, (length, previous) => {
  if (length && !starterLanguage.value) starterLanguage.value = selectedLanguages.value[0]
  if (length && !referenceForm.value.language) referenceForm.value.language = selectedLanguages.value[0]
  if (!length && previous) starterLanguage.value = ''
})

watch(() => testsForm.value.autoWeight, (enabled) => {
  if (enabled) applyAutoWeights()
})

onMounted(async () => {
  await Promise.all([loadTasks(), loadKnowledgeNodes()])
})
</script>

<template>
  <section class="sfx-teacher-experiments">
    <!-- 左：任务列表。列表本身滚动，不跟编辑器抢同一根滚动条。 -->
    <aside class="task-column" aria-label="实验任务列表">
      <header class="task-column__head">
        <div class="task-column__headline">
          <h2 class="task-column__title">实验任务</h2>
          <p class="sfx-t-caption">按版本固化题目与测试；正式成绩采用 ACM/ICPC 全量通过规则。</p>
        </div>
        <SfxButton size="sm" variant="secondary" @click="startNewTask">
          <template #icon><Plus :size="15" /></template>
          新建任务
        </SfxButton>
      </header>

      <label class="task-search">
        <Search :size="14" aria-hidden="true" />
        <input
          v-model="keyword"
          class="task-search__input"
          type="search"
          placeholder="搜索任务名称或说明"
          aria-label="搜索实验任务"
        />
      </label>

      <div class="task-list">
        <SfxSkeleton v-if="listState === 'loading'" :lines="4" />
        <SfxError v-else-if="listState === 'error'" :description="listError" @retry="loadTasks" />
        <SfxEmpty
          v-else-if="!taskCount"
          title="没有匹配的实验任务"
          description="换个关键词，或点「新建任务」创建第一个实验。"
        />
        <template v-else>
          <section v-for="group in taskGroups" :key="group.key" class="task-group">
            <p class="task-group__label">
              {{ group.label }} · {{ group.items.length }}
            </p>
            <div
              v-for="task in group.items"
              :key="task.experiment_id"
              class="task-card"
              :class="{ 'is-selected': !creating && task.experiment_id === currentId }"
              role="button"
              tabindex="0"
              :aria-pressed="!creating && task.experiment_id === currentId"
              @click="openTask(task)"
              @keydown.enter.prevent="openTask(task)"
              @keydown.space.prevent="openTask(task)"
            >
              <span class="task-card__row">
                <span class="task-card__title">{{ task.title }}</span>
                <SfxBadge :tone="PUBLISH_META[task.publish_status]?.tone ?? 'neutral'">
                  {{ PUBLISH_META[task.publish_status]?.label ?? task.publish_status }}
                </SfxBadge>
              </span>
              <span class="task-card__meta">
                {{ (task.language_whitelist || []).map(languageLabel).join('、') || '未选择语言' }}
                · 关联 {{ (task.knowledge_node_ids || []).length }} 个知识点
              </span>
            </div>
          </section>
        </template>
      </div>
    </aside>

    <!-- 右：编辑器 -->
    <div class="editor-column">
      <SfxEmpty
        v-if="!editorOpen"
        title="选择左侧任务，或新建一个实验任务"
        description="四段式设定：基本信息 → 测试用例 → 运行限制 → 发布检查。任一段都可直接跳转，不必按顺序走。"
      />

      <template v-else>
        <header class="editor-head">
          <div class="editor-head__main">
            <h2 class="editor-head__title">
              {{ creating ? '新建实验任务' : current?.title }}
            </h2>
            <div class="editor-head__badges">
              <template v-if="creating">
                <SfxBadge tone="amber">未保存</SfxBadge>
              </template>
              <template v-else-if="current">
                <SfxBadge :tone="PUBLISH_META[current.publish_status]?.tone ?? 'neutral'">
                  {{ PUBLISH_META[current.publish_status]?.label ?? current.publish_status }}
                </SfxBadge>
                <SfxBadge v-if="targetVersion" tone="ink">{{ targetVersion.label }}</SfxBadge>
                <SfxBadge v-if="targetLocked" tone="green">已锁定</SfxBadge>
                <SfxBadge v-else-if="activeVersion" tone="amber">
                  学生当前使用 {{ activeVersion.label }}
                </SfxBadge>
              </template>
            </div>
          </div>
          <SfxButton
            v-if="!creating && current && current.publish_status === 'draft'"
            size="sm"
            variant="tertiary"
            :loading="busyAction === 'archive'"
            @click="archiveTask"
          >
            归档
          </SfxButton>
        </header>

        <SfxError v-if="error" :description="error" :retryable="false" />

        <nav class="section-nav" role="tablist" aria-label="实验任务设定分段">
          <SfxButton
            v-for="key in EXPERIMENT_SECTIONS"
            :key="key"
            role="tab"
            size="sm"
            :aria-selected="section === key"
            :variant="section === key ? 'secondary' : 'tertiary'"
            :disabled="creating && key !== 'basics'"
            :title="creating && key !== 'basics' ? '先保存任务定义，再配置测试与发布' : ''"
            @click="goToSection(key)"
          >
            {{ EXPERIMENT_SECTION_LABELS[key] }}
          </SfxButton>
        </nav>

        <!-- ① 基本信息 -->
        <section v-if="section === 'basics'" class="pane pane--form">
          <div class="pane-head">
            <h3 class="pane-title">基本信息</h3>
            <p class="sfx-t-caption">
              关联知识点决定成绩能否进入认知统计：<strong>创建时写入，之后不可修改</strong>。
              不选也能发布，但成绩只记分。
            </p>
          </div>

          <label class="field">
            <span class="field__label">任务名称<i class="field__required">*</i></span>
            <input
              v-model.trim="basicsForm.title"
              class="sfx-input"
              maxlength="200"
              placeholder="例如：两数之和"
            />
          </label>

          <label class="field">
            <span class="field__label">任务说明</span>
            <textarea
              v-model="basicsForm.description"
              class="sfx-input sfx-textarea"
              rows="5"
              maxlength="4000"
              placeholder="说明输入输出格式、样例与约束。这段文字会作为学生工作台的任务描述。"
            />
          </label>

          <div class="field">
            <span class="field__label">允许语言<i class="field__required">*</i></span>
            <div class="chip-row">
              <SfxButton
                v-for="language in languageOptions"
                :key="language"
                size="sm"
                :variant="selectedLanguages.includes(language) ? 'primary' : 'secondary'"
                :aria-pressed="selectedLanguages.includes(language)"
                @click="toggleLanguage(language)"
              >
                {{ languageLabel(language) }}
              </SfxButton>
            </div>
            <p class="sfx-t-caption">
              选项来自评测机 <code class="mono">/sandbox/languages</code>，只允许评测机真实可执行的语言。
              <template v-if="!props.languages.length">
                当前未取到沙箱语言列表，已选语言仍会保留。
              </template>
              至少保留一种。
            </p>
          </div>

          <div class="field-grid">
            <label class="field">
              <span class="field__label">最大尝试次数</span>
              <input
                v-model.number="basicsForm.max_attempts"
                class="sfx-input"
                type="number"
                min="1"
                max="20"
              />
            </label>
            <label class="field">
              <span class="field__label">冷却时间（分钟）</span>
              <input
                v-model.number="basicsForm.cooldown_minutes"
                class="sfx-input"
                type="number"
                min="0"
                max="1440"
              />
            </label>
          </div>

          <div class="field">
            <span class="field__label">
              关联知识点（{{ selectedKnowledgeIds.length }} 已选）
            </span>
            <div v-if="selectedKnowledgeTitles.length" class="chip-row chip-row--selected">
              <span v-for="title in selectedKnowledgeTitles" :key="title" class="chip chip--on">
                <Check :size="12" />{{ title }}
              </span>
            </div>
            <template v-if="creating">
              <label class="task-search task-search--wide">
                <Search :size="14" aria-hidden="true" />
                <input
                  v-model="knowledgeKeyword"
                  class="task-search__input"
                  type="search"
                  placeholder="按名称筛选知识点"
                  aria-label="筛选知识点"
                />
              </label>
              <div v-if="knowledgeState === 'ready'" class="knowledge-list">
                <label
                  v-for="node in filteredKnowledge"
                  :key="node.id"
                  class="knowledge-item"
                  :class="{ 'is-on': selectedKnowledgeIds.includes(node.id) }"
                >
                  <input
                    type="checkbox"
                    :checked="selectedKnowledgeIds.includes(node.id)"
                    @change="toggleKnowledgeNode(node.id)"
                  />
                  <span class="knowledge-item__title">{{ node.title }}</span>
                </label>
              </div>
              <SfxSkeleton v-else-if="knowledgeState === 'loading'" :lines="3" />
              <p v-else class="sfx-t-caption">
                课程暂无可用知识图谱节点。可先发布，成绩仅记分、不进统计。
              </p>
            </template>
            <p v-else class="sfx-t-caption">
              关联关系在创建时写入，之后不可更改。如需换绑，请新建一项实验任务。
            </p>
          </div>

          <div class="pane-actions">
            <SfxButton
              v-if="creating"
              :loading="saving && busyAction === 'create'"
              @click="createDefinition"
            >
              创建任务并开始出题
            </SfxButton>
            <template v-else>
              <SfxButton :loading="saving && busyAction === 'basics'" @click="saveBasics">
                保存基本信息
              </SfxButton>
              <SfxButton variant="secondary" @click="goToSection('tests')">去写测试用例</SfxButton>
            </template>
          </div>
        </section>

        <!-- ② 测试用例 -->
        <section v-else-if="section === 'tests'" class="pane">
          <div class="pane-head">
            <h3 class="pane-title">测试用例</h3>
            <p class="sfx-t-caption">
              权重只用于完整性校验，正式判定仍是"全量通过才算过"。
              版本创建后测试集冻结，改动会以
              <strong>v{{ nextVersionNumber }}</strong> 新建，历史版本保留。
            </p>
          </div>

          <div class="case-toolbar">
            <SfxButton size="sm" variant="secondary" @click="addCase(false)">
              <template #icon><Plus :size="14" /></template>
              公开用例
            </SfxButton>
            <SfxButton size="sm" variant="secondary" @click="addCase(true)">
              <template #icon><Plus :size="14" /></template>
              隐藏用例
            </SfxButton>
            <SfxButton size="sm" variant="secondary" @click="showImport = !showImport">
              <template #icon><Upload :size="14" /></template>
              JSON 批量导入
            </SfxButton>
            <span class="case-toolbar__spacer" />
            <label class="switch">
              <input v-model="testsForm.autoWeight" type="checkbox" />
              <span>权重自动均分</span>
            </label>
            <SfxBadge :tone="weightValid ? 'green' : 'red'">
              合计 {{ weightTotal.toFixed(2) }}
              {{ weightValid ? '' : `（还差 ${weightDelta > 0 ? weightDelta.toFixed(2) : '超出'}）` }}
            </SfxBadge>
          </div>

          <p v-if="zeroWeightCount" class="case-warning">
            <TriangleAlert :size="13" aria-hidden="true" />
            有 {{ zeroWeightCount }} 条用例权重为 0。服务端只校验权重总和，
            权重为 0 的用例即使失败也不影响全量通过判定，等于静默失效。
            建议开启「权重自动均分」或手动分配。
          </p>

          <div v-if="showImport" class="import-block">
            <p class="sfx-t-caption">
              粘贴用例数组，字段：<code class="mono">case_name</code> /
              <code class="mono">stdin</code> /
              <code class="mono">expected_stdout</code> /
              <code class="mono">is_hidden</code>（可省略权重，开启自动均分时会重新分配）。
            </p>
            <textarea
              v-model="importText"
              class="sfx-input sfx-textarea mono"
              rows="6"
              spellcheck="false"
              placeholder='[{"case_name":"样例 1","stdin":"1 2","expected_stdout":"3","is_hidden":false}]'
            />
            <p v-if="importError" class="import-error">
              <TriangleAlert :size="13" aria-hidden="true" />{{ importError }}
            </p>
            <div class="pane-actions">
              <SfxButton size="sm" @click="importCases">解析并替换用例</SfxButton>
              <SfxButton size="sm" variant="secondary" @click="showImport = false">收起</SfxButton>
            </div>
          </div>

          <div class="case-list">
            <div class="case-head" aria-hidden="true">
              <span>#</span>
              <span>名称</span>
              <span>类型</span>
              <span>标准输入</span>
              <span>期望输出</span>
              <span>权重</span>
              <span />
            </div>

            <div
              v-for="(testCase, index) in testsForm.cases"
              :key="testCase.id"
              class="case-row"
              :class="{ 'is-expanded': isExpanded(testCase) }"
            >
              <span class="case-row__index">{{ index + 1 }}</span>

              <input
                v-model.trim="testCase.case_name"
                class="sfx-input"
                maxlength="200"
                :aria-label="`第 ${index + 1} 条用例名称`"
              />

              <SfxButton
                size="sm"
                :variant="testCase.is_hidden ? 'secondary' : 'tertiary'"
                :aria-pressed="testCase.is_hidden"
                @click="testCase.is_hidden = !testCase.is_hidden"
              >
                {{ testCase.is_hidden ? '隐藏' : '公开' }}
              </SfxButton>

              <div
                class="case-cell"
                role="button"
                tabindex="0"
                :aria-expanded="isExpanded(testCase)"
                @click="toggleExpanded(testCase)"
                @keydown.enter.prevent="toggleExpanded(testCase)"
                @keydown.space.prevent="toggleExpanded(testCase)"
              >
                <span v-if="previewText(testCase.stdin)" class="case-cell__text mono">
                  {{ previewText(testCase.stdin) }}
                </span>
                <span v-else class="case-cell__empty">编辑标准输入</span>
              </div>

              <div
                class="case-cell"
                role="button"
                tabindex="0"
                :aria-expanded="isExpanded(testCase)"
                @click="toggleExpanded(testCase)"
                @keydown.enter.prevent="toggleExpanded(testCase)"
                @keydown.space.prevent="toggleExpanded(testCase)"
              >
                <span v-if="previewText(testCase.expected_stdout)" class="case-cell__text mono">
                  {{ previewText(testCase.expected_stdout) }}
                </span>
                <span v-else class="case-cell__empty">编辑期望输出</span>
              </div>

              <input
                v-model.number="testCase.weight"
                class="sfx-input"
                type="number"
                min="0"
                max="1"
                step="0.01"
                :readonly="testsForm.autoWeight"
                :class="{ 'is-readonly': testsForm.autoWeight }"
                :aria-label="`第 ${index + 1} 条用例权重`"
              />

              <span class="case-row__ops">
                <SfxButton
                  size="sm"
                  variant="tertiary"
                  :title="`复制第 ${index + 1} 条用例`"
                  @click="duplicateCase(index)"
                >
                  <template #icon><Copy :size="14" /></template>
                  <span class="sr-only">复制</span>
                </SfxButton>
                <SfxButton
                  size="sm"
                  variant="tertiary"
                  :disabled="testsForm.cases.length === 1"
                  :title="testsForm.cases.length === 1 ? '至少保留一条用例' : `删除第 ${index + 1} 条用例`"
                  @click="removeCase(index)"
                >
                  <template #icon><Trash2 :size="14" /></template>
                  <span class="sr-only">删除</span>
                </SfxButton>
              </span>

              <div v-if="isExpanded(testCase)" class="case-row__editors">
                <label class="field">
                  <span class="field__label">标准输入（stdin）</span>
                  <textarea
                    v-model="testCase.stdin"
                    class="sfx-input sfx-textarea mono"
                    rows="5"
                    spellcheck="false"
                  />
                </label>
                <label class="field">
                  <span class="field__label">期望输出（stdout）</span>
                  <textarea
                    v-model="testCase.expected_stdout"
                    class="sfx-input sfx-textarea mono"
                    rows="5"
                    spellcheck="false"
                  />
                </label>
              </div>
            </div>
          </div>

          <p class="case-hint">
            点击「标准输入 / 期望输出」单元格即可展开逐字符编辑；收起后保留首行摘要。
            <template v-if="testsForm.autoWeight">
              自动均分已开启：{{ caseCount }} 条用例每条约
              {{ (100 / Math.max(caseCount, 1) / 100).toFixed(2) }}。
            </template>
          </p>

          <div class="pane-actions">
            <SfxButton
              :disabled="!canCreateVersion"
              :loading="saving && busyAction === 'version'"
              @click="createVersion"
            >
              创建版本 v{{ nextVersionNumber }}
            </SfxButton>
            <SfxButton variant="secondary" @click="goToSection('limits')">配置运行限制</SfxButton>
          </div>
          <p class="sfx-t-caption">{{ createVersionHint }}</p>

          <div v-if="versions.length" class="version-history">
            <p class="version-history__label">版本历史</p>
            <ul class="version-history__list">
              <li v-for="version in versions" :key="version.version_id">
                <span class="version-history__name">{{ version.label }}</span>
                <SfxBadge v-if="version.is_active" tone="green">学生使用中</SfxBadge>
                <SfxBadge v-else-if="version.is_locked" tone="ink">已锁定</SfxBadge>
                <SfxBadge v-else tone="amber">可继续配置</SfxBadge>
              </li>
            </ul>
          </div>
        </section>

        <!-- ③ 运行限制 -->
        <section v-else-if="section === 'limits'" class="pane pane--form">
          <div class="pane-head">
            <h3 class="pane-title">运行限制</h3>
            <p class="sfx-t-caption">
              与测试用例一起在「创建版本」时固化。取值必须落在服务端安全边界内，
              发布时服务端会复校。
            </p>
          </div>

          <div class="field">
            <span class="field__label">预设</span>
            <div class="chip-row">
              <SfxButton
                v-for="preset in LIMIT_PRESETS"
                :key="preset.key"
                size="sm"
                variant="secondary"
                :title="preset.note"
                @click="applyPreset(preset)"
              >
                {{ preset.label }}
              </SfxButton>
            </div>
          </div>

          <div class="field-grid field-grid--three">
            <label v-for="field in LIMIT_FIELDS" :key="field.key" class="field">
              <span class="field__label">{{ field.label }}</span>
              <span class="field__control">
                <input
                  v-model.number="limitsForm[field.key]"
                  class="sfx-input"
                  type="number"
                  :min="field.min"
                  :max="field.max"
                />
                <span v-if="field.unit" class="field__unit">{{ field.unit }}</span>
              </span>
              <span class="sfx-t-caption">范围 {{ field.min }} – {{ field.max }}</span>
            </label>
          </div>

          <label class="switch switch--block">
            <input v-model="testsForm.writesFormalEvidence" type="checkbox" />
            <span>
              计入学习证据
              <em class="sfx-t-caption">关闭后成绩仅记分，不写 LearningEvidence、不进认知统计。</em>
            </span>
          </label>

          <div class="field">
            <span class="field__label">开始代码（可选，按语言）</span>
            <div class="tab-row">
              <SfxButton
                v-for="language in selectedLanguages"
                :key="language"
                size="sm"
                :variant="starterLanguage === language ? 'primary' : 'secondary'"
                :aria-pressed="starterLanguage === language"
                @click="starterLanguage = language"
              >
                {{ languageLabel(language) }}
              </SfxButton>
            </div>
            <textarea
              v-if="starterLanguage"
              v-model="starterCode[starterLanguage]"
              class="sfx-input sfx-textarea mono"
              rows="7"
              spellcheck="false"
              :placeholder="`学生打开工作台时预填这段 ${languageLabel(starterLanguage)} 代码`"
            />
            <p v-else class="sfx-t-caption">请先在「基本信息」中选择允许语言。</p>
            <p class="sfx-t-caption">
              学生可随时重置回这里的内容；留空则为空编辑器。切换语言前请先保存，
              当前 Tab 的改动会随「创建版本」一次性提交。
            </p>
          </div>

          <div class="pane-actions">
            <SfxButton variant="secondary" @click="goToSection('tests')">返回测试用例</SfxButton>
            <SfxButton variant="secondary" @click="goToSection('publish')">去发布检查</SfxButton>
          </div>
        </section>

        <!-- ④ 发布检查 -->
        <section v-else class="pane">
          <div class="pane-head">
            <h3 class="pane-title">发布检查</h3>
            <p class="sfx-t-caption">
              以下顺序即服务端 <code class="mono">ExperimentPublishValidator</code> 的前置条件。
              未满足的项会在发布时被直接拒绝，所以提前在这里逐项闭合。
            </p>
          </div>

          <ol class="checklist">
            <li
              v-for="(item, index) in checklist"
              :key="item.key"
              class="checklist__item"
              :class="`is-${item.state}`"
            >
              <span class="checklist__mark" aria-hidden="true">
                <Check v-if="item.state === 'done'" :size="14" />
                <Lock v-else-if="item.key === 'lock'" :size="14" />
                <span v-else>{{ index + 1 }}</span>
              </span>
              <span class="checklist__body">
                <span class="checklist__label">{{ item.label }}</span>
                <span class="checklist__detail sfx-t-caption">{{ item.detail }}</span>
              </span>
              <SfxButton
                v-if="item.action && item.key !== 'publish'"
                size="sm"
                variant="tertiary"
                @click="goToSection(item.action.section)"
              >
                {{ item.action.label }}
              </SfxButton>
            </li>
          </ol>

          <div class="preview-block">
            <div class="preview-block__head">
              <h4 class="sfx-t-ui">参考解预览</h4>
              <SfxBadge v-if="preview" :tone="preview.accepted ? 'green' : 'red'">
                {{ preview.passed_count }} / {{ preview.total_count }} 通过
              </SfxBadge>
              <SfxBadge v-else-if="previewVerified" tone="green">已通过</SfxBadge>
              <SfxBadge v-else tone="amber">未运行</SfxBadge>
            </div>
            <p class="sfx-t-caption">
              参考源码只用于这次预览，不落库、不进日志、不进智能体上下文；
              隐藏用例的输入输出也不会随预览外泄。
            </p>
            <div class="preview-block__row">
              <SfxButton
                v-for="language in selectedLanguages"
                :key="language"
                size="sm"
                :variant="referenceForm.language === language ? 'primary' : 'secondary'"
                :aria-pressed="referenceForm.language === language"
                @click="referenceForm.language = language"
              >
                {{ languageLabel(language) }}
              </SfxButton>
            </div>
            <textarea
              v-model="referenceForm.source_code"
              class="sfx-input sfx-textarea mono"
              rows="9"
              spellcheck="false"
              placeholder="粘贴能全量通过的参考解。未提供目标版本的参考解语言时先在上方选择。"
            />
            <div class="pane-actions">
              <SfxButton
                :disabled="!targetVersion || !referenceForm.source_code.trim()"
                :loading="saving && busyAction === 'preview'"
                @click="runReferencePreview"
              >
                <template #icon><Play :size="14" /></template>
                对 {{ targetVersion?.label ?? '目标版本' }} 运行预览
              </SfxButton>
              <SfxButton
                variant="secondary"
                :disabled="!canLock"
                :loading="saving && busyAction === 'lock'"
                @click="lockVersion"
              >
                <template #icon><Lock :size="14" /></template>
                锁定并设为默认版本
              </SfxButton>
            </div>
            <p v-if="!targetVersion" class="sfx-t-caption">
              还没有可预览的版本，请先在「测试用例」中创建版本。
            </p>
            <p v-else-if="!previewVerified" class="sfx-t-caption">
              锁定要求该版本的参考解预览全量通过；预览结果会写回服务端，刷新后仍然有效。
            </p>
          </div>

          <div class="publish-block">
            <p class="sfx-t-caption">
              发布时服务端还会复校：课程编码沙箱能力、语言白名单、默认版本处于活动与锁定状态、
              通过阈值 1.0、资源边界、测试集非空且权重合计 1.00、评测机健康检查。
            </p>
            <div class="pane-actions">
              <SfxButton
                :disabled="!canPublish"
                :loading="saving && busyAction === 'publish'"
                @click="publish"
              >
                <template #icon><Rocket :size="14" /></template>
                {{ current?.publish_status === 'published' ? '已发布' : '发布给学生' }}
              </SfxButton>
              <SfxButton variant="secondary" @click="goToSection('tests')">
                改动测试集（将创建新版本）
              </SfxButton>
            </div>
          </div>
        </section>
      </template>
    </div>
  </section>
</template>

<style scoped>
/* ── 骨架：两列 —— 左任务列表，右编辑器。两列各自滚动，
   避免旧版"整页 overflow:hidden + 面板无滚动容器"导致的内容截断。 ── */
.sfx-teacher-experiments {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  /* design.md §5.2：可滚动行必须用 minmax(0, 1fr)，直接写 1fr 会被内容撑开。 */
  grid-template-rows: minmax(0, 1fr);
  gap: var(--space-4);
}

/* ── 左列 ── */
.task-column {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  background: var(--surface-panel);
}

.task-column__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-2);
}

.task-column__headline { min-width: 0; }

.task-column__title {
  margin: 0 0 var(--space-1);
  font-size: var(--title-3-size);
  line-height: var(--title-3-line);
  font-weight: var(--title-3-weight);
}

.task-column__headline p { margin: 0; line-height: 1.5; }

.task-search {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 34px;
  padding: 0 var(--space-3);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-panel);
  color: var(--text-muted);
}

.task-search:focus-within { border-color: var(--color-focus); }

.task-search__input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text-primary);
  font-size: var(--ui-md-size);
  font-family: inherit;
}

.task-search--wide { margin-top: var(--space-2); }

.task-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding-right: 2px;
}

.task-group { display: flex; flex-direction: column; gap: var(--space-2); }

.task-group__label {
  margin: 0;
  font-size: var(--caption-size);
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.task-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-3);
  border: 1px solid var(--border-subtle);
  border-left: 3px solid transparent;
  border-radius: var(--radius-md);
  background: var(--surface-panel);
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-out),
    background var(--duration-fast) var(--ease-out);
}

.task-card:hover { border-color: var(--border-strong); }

.task-card.is-selected {
  border-color: var(--color-brand);
  border-left-color: var(--color-brand);
  background: var(--color-brand-soft);
}

.task-card__row { display: flex; align-items: center; gap: var(--space-2); }

.task-card__title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
  font-size: var(--ui-md-size);
  color: var(--text-primary);
}

.task-card__meta {
  font-size: var(--caption-size);
  color: var(--text-muted);
  line-height: 1.5;
}

/* ── 右列 ── */
.editor-column {
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-5) var(--space-6);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  background: var(--surface-panel);
}

.editor-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
}

.editor-head__main { min-width: 0; }

.editor-head__title {
  margin: 0 0 var(--space-2);
  font-size: var(--title-3-size);
  line-height: var(--title-3-line);
  font-weight: var(--title-3-weight);
}

.editor-head__badges { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; }

/* 段导航：四段任意跳转，不强制线性。 */
.section-nav {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--border-subtle);
}

.pane { display: flex; flex-direction: column; gap: var(--space-4); min-width: 0; }

.pane--form { max-width: 720px; }

.pane-head { display: flex; flex-direction: column; gap: var(--space-1); }

.pane-title {
  margin: 0;
  font-size: var(--title-3-size);
  line-height: var(--title-3-line);
  font-weight: var(--title-3-weight);
}

.pane-head p { margin: 0; line-height: 1.6; }

.pane-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

/* ── 字段 ── */
.field { display: flex; flex-direction: column; gap: var(--space-2); min-width: 0; }

.field__label {
  font-size: var(--ui-md-size);
  font-weight: var(--ui-md-weight);
  color: var(--text-primary);
}

.field__required { color: var(--red-500); font-style: normal; margin-left: 2px; }

.field__control { position: relative; display: flex; align-items: center; }

.field__unit {
  position: absolute;
  right: var(--space-3);
  font-size: var(--caption-size);
  color: var(--text-muted);
  pointer-events: none;
}

.field-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-3) var(--space-4); }

.field-grid--three { grid-template-columns: repeat(3, minmax(0, 1fr)); }

.field .sfx-input.is-readonly,
.field .sfx-input[readonly] { background: var(--surface-cool); color: var(--text-secondary); }

/* ── chip / switch / tab ── */
.chip-row { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; }

.chip-row--selected { margin-bottom: var(--space-1); }

.chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px var(--space-2);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-default);
  background: var(--surface-cool);
  font-size: var(--caption-size);
  color: var(--text-secondary);
}

.chip--on {
  border-color: var(--green-300);
  background: var(--green-100);
  color: var(--green-700);
}

.switch {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--ui-md-size);
  color: var(--text-primary);
  cursor: pointer;
}

.switch--block { align-items: flex-start; }
.switch--block em { display: block; font-style: normal; margin-top: 2px; }

.tab-row { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; }

/* ── 知识点 ── */
.knowledge-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-1) var(--space-3);
  max-height: 220px;
  overflow-y: auto;
  padding: var(--space-2);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-cool);
}

.knowledge-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 30px;
  padding: 0 var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--ui-sm-size);
  cursor: pointer;
}

.knowledge-item.is-on { background: var(--color-brand-soft); font-weight: 500; }

.knowledge-item__title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ── 测试用例表 ── */
.case-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.case-toolbar__spacer { flex: 1; min-width: 0; }

.import-block {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-cool);
}

.import-error {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  margin: 0;
  color: var(--red-700);
  font-size: var(--caption-size);
}

.case-list { display: flex; flex-direction: column; gap: var(--space-2); }

.case-head,
.case-row {
  display: grid;
  grid-template-columns: 28px minmax(120px, 1.1fr) 76px minmax(140px, 1.6fr) minmax(140px, 1.6fr) 84px 72px;
  gap: var(--space-2);
  align-items: center;
}

.case-head {
  padding: 0 var(--space-2);
  font-size: var(--caption-size);
  color: var(--text-muted);
}

.case-row {
  padding: var(--space-2);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--surface-panel);
}

.case-row.is-expanded { border-color: var(--ink-300); background: var(--surface-cool); }

.case-row__index { font-size: var(--caption-size); color: var(--text-muted); text-align: center; }

.case-cell {
  display: flex;
  align-items: center;
  min-height: 34px;
  padding: 0 var(--space-2);
  border: 1px dashed var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-cool);
  cursor: pointer;
  overflow: hidden;
}

.case-cell:hover { border-color: var(--ink-300); }

.case-cell__text {
  font-size: var(--caption-size);
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.case-cell__empty { font-size: var(--caption-size); color: var(--text-muted); }

.case-row__ops { display: inline-flex; align-items: center; gap: var(--space-1); }

.case-row__editors {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
  padding-top: var(--space-2);
  border-top: 1px solid var(--border-subtle);
}

.case-hint { margin: 0; font-size: var(--caption-size); color: var(--text-muted); line-height: 1.6; }

.case-warning {
  display: flex;
  align-items: flex-start;
  gap: var(--space-1);
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--amber-300);
  border-radius: var(--radius-sm);
  background: var(--amber-100);
  color: var(--amber-700);
  font-size: var(--caption-size);
  line-height: 1.6;
}

.version-history {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding-top: var(--space-3);
  border-top: 1px solid var(--border-subtle);
}

.version-history__label {
  margin: 0;
  font-size: var(--caption-size);
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.version-history__list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.version-history__list li { display: inline-flex; align-items: center; gap: var(--space-2); }

.version-history__name { font-size: var(--ui-sm-size); color: var(--text-primary); }

/* ── 发布检查清单 ── */
.checklist {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.checklist__item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--surface-panel);
}

.checklist__item.is-done { border-color: var(--green-300); background: var(--green-100); }
.checklist__item.is-ready { border-color: var(--ink-300); background: var(--color-brand-soft); }
.checklist__item.is-blocked { background: var(--surface-cool); }

.checklist__mark {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  border-radius: var(--radius-full);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border-default);
  background: var(--surface-panel);
  font-size: var(--caption-size);
  color: var(--text-muted);
}

.checklist__item.is-done .checklist__mark { border-color: var(--green-500); color: var(--green-700); }
.checklist__item.is-ready .checklist__mark { border-color: var(--color-brand); color: var(--color-brand); }

.checklist__body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }

.checklist__label { font-size: var(--ui-md-size); font-weight: var(--ui-md-weight); color: var(--text-primary); }

.checklist__detail { line-height: 1.5; }

.preview-block,
.publish-block {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
}

.preview-block { background: var(--surface-canvas); }

.preview-block__head { display: flex; align-items: center; gap: var(--space-2); }
.preview-block__head h4 { flex: 1; margin: 0; }
.preview-block__row { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; }
.preview-block p { margin: 0; line-height: 1.6; }
.publish-block p { margin: 0; line-height: 1.6; }

.mono { font-family: var(--font-mono); }

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

/* 移动端（design.md §12.5）：两列改纵排，各自滚动降级为整体滚动。 */
@media (max-width: 1100px) {
  .sfx-teacher-experiments {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto minmax(0, 1fr);
  }

  .task-column { max-height: 260px; }
}

@media (max-width: 760px) {
  .editor-column { padding: var(--space-4); }
  .field-grid,
  .field-grid--three,
  .knowledge-list,
  .case-row__editors { grid-template-columns: minmax(0, 1fr); }
  .case-head { display: none; }
  .case-row { grid-template-columns: minmax(0, 1fr); }
  .case-row__index { text-align: left; }
}
</style>
