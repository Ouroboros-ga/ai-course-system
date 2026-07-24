<template>
  <div class="qsm-panel">
    <!-- 头部 -->
    <header class="qsm-header">
      <div class="header-title">
        <Layers :size="18" class="header-icon" />
        <h3>题源映射管理</h3>
        <span v-if="mappings.length" class="count-badge">{{ mappings.length }}</span>
      </div>
      <div class="header-meta">
        <span v-if="lastGenerated" class="meta-text">上次生成: {{ formatTime(lastGenerated) }}</span>
      </div>
    </header>

    <!-- 加载态 -->
    <div v-if="loading && !mappings.length" class="qsm-state">
      <Loader2 :size="24" class="spin-icon" />
      <span>加载映射数据...</span>
    </div>

    <!-- 空态 -->
    <div v-else-if="!mappings.length" class="qsm-state empty">
      <FileQuestion :size="36" class="state-icon" />
      <p class="state-text">暂无题源映射</p>
      <p class="state-hint">点击下方"生成映射"由 AI EduAgent 自动建立题目与课件、知识点的对照关系</p>
    </div>

    <!-- 主体三栏对照 -->
    <div v-else class="qsm-body">
      <!-- 左栏：题目与答案 -->
      <section class="qsm-col qsm-left">
        <div class="col-header">
          <ListChecks :size="15" class="col-icon" />
          <span>题目与答案</span>
        </div>
        <div class="question-list">
          <div
            v-for="item in mappings"
            :key="item.id"
            class="question-item"
            :class="{
              active: selectedId === item.id,
              locked: item.status === 'locked',
              rejected: item.status === 'rejected',
            }"
            @click="selectMapping(item.id)"
          >
            <div class="question-item-top">
              <span class="question-index">#{{ item.question_index ?? item.question_id }}</span>
              <span class="status-tag" :class="`status-${item.status}`">{{ statusLabel(item.status) }}</span>
            </div>
            <div class="question-text">{{ item.question_text || '(无题目文本)' }}</div>
            <div v-if="item.answer" class="question-answer">
              <span class="answer-label">答案:</span>
              <span class="answer-text">{{ item.answer }}</span>
            </div>
          </div>
        </div>
      </section>

      <!-- 中栏：AI 映射理由 -->
      <section class="qsm-col qsm-middle">
        <div class="col-header">
          <Brain :size="15" class="col-icon" />
          <span>AI 映射理由</span>
        </div>
        <div v-if="selected" class="rationale-content">
          <div class="confidence-block">
            <div class="confidence-label">
              <span>置信度</span>
              <span class="confidence-value">{{ formatPercent(selected.confidence) }}</span>
            </div>
            <div class="confidence-bar">
              <div
                class="confidence-fill"
                :class="confidenceClass(selected.confidence)"
                :style="{ width: confidenceWidth(selected.confidence) }"
              ></div>
            </div>
          </div>

          <div class="rationale-text">
            <div class="block-title"><Sparkles :size="13" /> EduAgent 推理依据</div>
            <p>{{ selected.ai_rationale || 'AI 未提供映射理由。' }}</p>
          </div>

          <div class="status-block">
            <div class="block-title"><Info :size="13" /> 当前状态</div>
            <div class="status-row">
              <span class="status-tag lg" :class="`status-${selected.status}`">
                <component :is="statusIcon(selected.status)" :size="13" />
                {{ statusLabel(selected.status) }}
              </span>
              <span v-if="selected.version" class="version-text">v{{ selected.version }}</span>
            </div>
          </div>

          <div v-if="selected.status === 'locked'" class="lock-notice">
            <Shield :size="14" class="shield-icon" />
            <span>已锁定: EduAgent 重跑不可覆盖此映射</span>
          </div>
        </div>
        <div v-else class="col-placeholder">
          <span>从左侧选择题目查看 AI 映射理由</span>
        </div>
      </section>

      <!-- 右栏：课件页码 / OCR 证据 / 知识点 -->
      <section class="qsm-col qsm-right">
        <div class="col-header">
          <BookOpen :size="15" class="col-icon" />
          <span>课件对照</span>
        </div>
        <div v-if="selected" class="detail-content">
          <!-- 课件页码范围 -->
          <div class="detail-block">
            <div class="block-title"><FileText :size="13" /> 课件页码范围</div>
            <div v-if="editing" class="page-edit">
              <input
                v-model.number="editForm.pageStart"
                type="number"
                min="1"
                class="page-input"
                placeholder="起始页"
              />
              <span class="page-sep">-</span>
              <input
                v-model.number="editForm.pageEnd"
                type="number"
                min="1"
                class="page-input"
                placeholder="结束页"
              />
            </div>
            <div v-else class="page-display">
              <span class="page-num">{{ selected.page_start ?? '-' }}</span>
              <span class="page-sep">-</span>
              <span class="page-num">{{ selected.page_end ?? '-' }}</span>
            </div>
          </div>

          <!-- OCR 证据 -->
          <div class="detail-block">
            <div class="block-title"><FileSearch :size="13" /> OCR 证据</div>
            <div v-if="ocrEvidenceList.length" class="ocr-list">
              <div v-for="(ev, i) in ocrEvidenceList" :key="i" class="ocr-item">
                <span v-if="ev.page != null" class="ocr-page">P{{ ev.page }}</span>
                <span class="ocr-text">{{ ev.text }}</span>
              </div>
            </div>
            <p v-else class="block-empty">无 OCR 证据</p>
          </div>

          <!-- 知识点 -->
          <div class="detail-block">
            <div class="block-title"><Tag :size="13" /> 知识点</div>
            <div v-if="editing" class="kp-edit">
              <div class="kp-tags">
                <span v-for="(kp, i) in editForm.knowledgePoints" :key="i" class="kp-tag">
                  {{ kp }}
                  <button class="kp-remove" @click.stop="removeKp(i)"><X :size="11" /></button>
                </span>
              </div>
              <input
                v-model="kpInput"
                class="kp-input"
                placeholder="输入知识点后回车添加"
                @keydown.enter.prevent="addKp"
                @keydown.delete="backspaceKp"
              />
            </div>
            <div v-else class="kp-display">
              <span v-for="(kp, i) in knowledgePointList" :key="i" class="kp-tag static">{{ kp }}</span>
              <span v-if="!knowledgePointList.length" class="block-empty">无知识点</span>
            </div>
          </div>
        </div>
        <div v-else class="col-placeholder">
          <span>从左侧选择题目查看课件对照</span>
        </div>
      </section>
    </div>

    <!-- 底部操作栏 -->
    <footer class="qsm-footer">
      <div class="footer-group">
        <button class="action-btn primary" :disabled="generating || loading" @click="handleGenerate">
          <Sparkles :size="15" />
          {{ generating ? '生成中...' : '生成映射' }}
        </button>
        <button
          v-if="!editing"
          class="action-btn"
          :disabled="!selected || selected.status === 'locked'"
          @click="startEdit"
        >
          <Pencil :size="15" /> 编辑
        </button>
        <template v-else>
          <button class="action-btn success" :disabled="saving" @click="handleSave">
            <Save :size="15" /> {{ saving ? '保存中...' : '保存' }}
          </button>
          <button class="action-btn" @click="cancelEdit"><X :size="15" /> 取消</button>
        </template>
      </div>
      <div class="footer-group">
        <button
          v-if="selected && selected.status !== 'locked'"
          class="action-btn warn"
          :disabled="!selected || generating"
          @click="handleLock"
        >
          <Lock :size="15" /> 锁定
        </button>
        <button
          v-else-if="selected && selected.status === 'locked'"
          class="action-btn"
          :disabled="!selected || generating"
          @click="handleUnlock"
        >
          <Unlock :size="15" /> 解锁
        </button>
        <button
          class="action-btn danger"
          :disabled="!selected || selected.status === 'rejected' || generating"
          @click="handleReject"
        >
          <Ban :size="15" /> 拒绝
        </button>
        <button
          class="action-btn"
          :disabled="!selected || selected.status === 'locked' || generating"
          :title="
            selected && selected.status === 'locked'
              ? '已锁定，EduAgent 重跑不可覆盖'
              : '重新生成此映射'
          "
          @click="handleRerun"
        >
          <RefreshCw :size="15" /> 重跑
        </button>
      </div>
    </footer>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import {
  Layers,
  ListChecks,
  Brain,
  BookOpen,
  FileText,
  FileSearch,
  Tag,
  X,
  Sparkles,
  Pencil,
  Save,
  Lock,
  Unlock,
  Ban,
  RefreshCw,
  Shield,
  Loader2,
  FileQuestion,
  CheckCircle,
  AlertTriangle,
  Info,
} from 'lucide-vue-next'
import {
  listMappings,
  generateMappings,
  updateMapping,
  updateMappingStatus,
} from '@/api/question_bank.js'

const props = defineProps({
  courseId: { type: Number, required: true },
})

const mappings = ref([])
const selectedId = ref(null)
const loading = ref(false)
const generating = ref(false)
const saving = ref(false)
const editing = ref(false)
const lastGenerated = ref(null)

const editForm = reactive({
  pageStart: null,
  pageEnd: null,
  knowledgePoints: [],
})
const kpInput = ref('')

const selected = computed(
  () => mappings.value.find((m) => m.id === selectedId.value) || null,
)

const ocrEvidenceList = computed(() => {
  if (!selected.value?.ocr_evidence) return []
  const ev = selected.value.ocr_evidence
  if (Array.isArray(ev)) return ev
  if (typeof ev === 'string') return ev.trim() ? [{ text: ev }] : []
  return []
})

const knowledgePointList = computed(() => {
  if (!selected.value?.knowledge_points) return []
  const kp = selected.value.knowledge_points
  if (Array.isArray(kp)) {
    return kp.map((k) => (typeof k === 'string' ? k : k.name || k.title || ''))
  }
  return []
})

// ── 生命周期 ──

onMounted(loadMappings)
watch(() => props.courseId, (val) => {
  if (val != null) loadMappings()
})

async function loadMappings() {
  loading.value = true
  try {
    const data = await listMappings(props.courseId)
    mappings.value = Array.isArray(data)
      ? data
      : data?.mappings ?? data?.items ?? []
    if (mappings.value.length && !selectedId.value) {
      selectedId.value = mappings.value[0].id
    }
  } catch {
    mappings.value = []
  } finally {
    loading.value = false
  }
}

function selectMapping(id) {
  if (editing.value) return
  selectedId.value = id
}

// ── 状态与格式化辅助 ──

function statusLabel(status) {
  const map = {
    auto_accepted: '自动接受',
    teacher_edited: '教师已编辑',
    locked: '已锁定',
    rejected: '已拒绝',
  }
  return map[status] || status
}

function statusIcon(status) {
  const map = {
    auto_accepted: CheckCircle,
    teacher_edited: Pencil,
    locked: Lock,
    rejected: AlertTriangle,
  }
  return map[status] || CheckCircle
}

function confidenceWidth(c) {
  const v = Math.max(0, Math.min(1, Number(c) || 0))
  return `${Math.round(v * 100)}%`
}

function confidenceClass(c) {
  const v = Number(c) || 0
  if (v >= 0.8) return 'high'
  if (v >= 0.5) return 'mid'
  return 'low'
}

function formatPercent(c) {
  return `${Math.round((Number(c) || 0) * 100)}%`
}

function formatTime(t) {
  if (!t) return ''
  const d = new Date(t)
  return `${d.getHours().toString().padStart(2, '0')}:${d
    .getMinutes()
    .toString()
    .padStart(2, '0')}`
}

// ── 编辑流程 ──

function startEdit() {
  if (!selected.value) return
  editing.value = true
  editForm.pageStart = selected.value.page_start ?? null
  editForm.pageEnd = selected.value.page_end ?? null
  editForm.knowledgePoints = [...knowledgePointList.value]
}

function cancelEdit() {
  editing.value = false
  kpInput.value = ''
}

async function handleSave() {
  if (!selected.value) return
  saving.value = true
  try {
    await updateMapping(props.courseId, selected.value.id, {
      page_start: editForm.pageStart,
      page_end: editForm.pageEnd,
      knowledge_points: editForm.knowledgePoints,
    })
    const idx = mappings.value.findIndex((m) => m.id === selectedId.value)
    if (idx !== -1) {
      mappings.value[idx] = {
        ...mappings.value[idx],
        page_start: editForm.pageStart,
        page_end: editForm.pageEnd,
        knowledge_points: editForm.knowledgePoints,
        status: 'teacher_edited',
      }
    }
    editing.value = false
    kpInput.value = ''
  } catch {
    // request.js 已处理错误提示
  } finally {
    saving.value = false
  }
}

// ── 知识点标签编辑 ──

function addKp() {
  const v = kpInput.value.trim()
  if (v && !editForm.knowledgePoints.includes(v)) {
    editForm.knowledgePoints.push(v)
  }
  kpInput.value = ''
}

function removeKp(i) {
  editForm.knowledgePoints.splice(i, 1)
}

function backspaceKp() {
  if (!kpInput.value && editForm.knowledgePoints.length) {
    editForm.knowledgePoints.pop()
  }
}

// ── 映射操作 ──

async function handleGenerate() {
  generating.value = true
  try {
    await generateMappings(props.courseId)
    lastGenerated.value = new Date().toISOString()
    await loadMappings()
  } catch {
    // request.js 已处理错误提示
  } finally {
    generating.value = false
  }
}

async function handleRerun() {
  if (!selected.value || selected.value.status === 'locked') return
  generating.value = true
  try {
    await generateMappings(props.courseId, {
      question_id: selected.value.question_id,
    })
    await loadMappings()
  } catch {
    // request.js 已处理错误提示
  } finally {
    generating.value = false
  }
}

async function handleLock() {
  if (!selected.value) return
  try {
    await updateMappingStatus(props.courseId, selected.value.id, {
      status: 'locked',
    })
    updateLocalStatus('locked')
  } catch {
    // request.js 已处理错误提示
  }
}

async function handleUnlock() {
  if (!selected.value) return
  try {
    await updateMappingStatus(props.courseId, selected.value.id, {
      status: 'teacher_edited',
    })
    updateLocalStatus('teacher_edited')
  } catch {
    // request.js 已处理错误提示
  }
}

async function handleReject() {
  if (!selected.value) return
  try {
    await updateMappingStatus(props.courseId, selected.value.id, {
      status: 'rejected',
    })
    updateLocalStatus('rejected')
  } catch {
    // request.js 已处理错误提示
  }
}

function updateLocalStatus(status) {
  const idx = mappings.value.findIndex((m) => m.id === selectedId.value)
  if (idx !== -1) {
    mappings.value[idx] = { ...mappings.value[idx], status }
  }
}
</script>

<style scoped>
.qsm-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

/* ── 头部 ── */

.qsm-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-border);
  flex-shrink: 0;
}

.header-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.header-title h3 {
  margin: 0;
  font-size: var(--text-base);
  font-weight: var(--font-semibold);
  color: var(--color-text);
}

.header-icon {
  color: var(--color-primary);
  flex-shrink: 0;
}

.count-badge {
  padding: var(--space-1) var(--space-2);
  background: var(--color-primary-light);
  color: var(--color-primary-hover);
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
}

.header-meta .meta-text {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

/* ── 加载/空态 ── */

.qsm-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
  padding: var(--space-10) var(--space-5);
}

.qsm-state.empty .state-icon {
  color: var(--color-text-muted);
  margin-bottom: var(--space-2);
}

.qsm-state.empty .state-text {
  margin: 0;
  font-size: var(--text-base);
  font-weight: var(--font-medium);
  color: var(--color-text);
}

.qsm-state.empty .state-hint {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  text-align: center;
  max-width: 360px;
  line-height: var(--leading-relaxed);
}

.spin-icon {
  animation: qsm-spin 0.8s linear infinite;
  color: var(--color-primary);
}

@keyframes qsm-spin {
  to {
    transform: rotate(360deg);
  }
}

/* ── 三栏主体 ── */

.qsm-body {
  flex: 1;
  display: grid;
  grid-template-columns: 320px 1fr 1fr;
  min-height: 0;
  overflow: hidden;
}

.qsm-col {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-right: 1px solid var(--color-border);
}

.qsm-col:last-child {
  border-right: none;
}

.col-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--color-text);
  background: var(--color-surface-2);
  border-bottom: 1px solid var(--color-border);
  flex-shrink: 0;
}

.col-icon {
  color: var(--color-primary);
  flex-shrink: 0;
}

.col-placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-5);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  text-align: center;
}

/* ── 左栏：题目列表 ── */

.question-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-2);
}

.question-item {
  padding: var(--space-3);
  border-radius: var(--radius-md);
  cursor: pointer;
  border: 1px solid transparent;
  transition: var(--duration-fast) var(--ease);
  margin-bottom: var(--space-1);
}

.question-item:hover {
  background: var(--color-surface-2);
}

.question-item.active {
  background: var(--color-primary-light);
  border-color: var(--color-primary);
}

.question-item.locked {
  border-left: 3px solid var(--color-warning);
}

.question-item.rejected {
  opacity: 0.6;
}

.question-item-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-1);
}

.question-index {
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  color: var(--color-text-muted);
  font-family: var(--font-mono);
}

.question-text {
  font-size: var(--text-sm);
  color: var(--color-text);
  line-height: var(--leading-relaxed);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.question-answer {
  margin-top: var(--space-1);
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  display: flex;
  gap: var(--space-1);
}

.answer-label {
  color: var(--color-text-muted);
  flex-shrink: 0;
}

.answer-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── 中栏：AI 理由 ── */

.rationale-content {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.confidence-block {
  background: var(--color-surface-2);
  border-radius: var(--radius-md);
  padding: var(--space-3);
}

.confidence-label {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-2);
}

.confidence-value {
  font-size: var(--text-base);
  font-weight: var(--font-bold);
  color: var(--color-text);
}

.confidence-bar {
  height: 6px;
  background: var(--color-surface-3);
  border-radius: var(--radius-full);
  overflow: hidden;
}

.confidence-fill {
  height: 100%;
  border-radius: var(--radius-full);
  transition: width var(--duration-slow) var(--ease);
}

.confidence-fill.high {
  background: var(--gradient-success);
}

.confidence-fill.mid {
  background: var(--gradient-warning);
}

.confidence-fill.low {
  background: var(--gradient-danger);
}

.rationale-text p {
  margin: var(--space-1) 0 0;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
}

.status-block .status-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.version-text {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  font-family: var(--font-mono);
}

.lock-notice {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: var(--color-warning-light);
  border-radius: var(--radius-md);
  font-size: var(--text-xs);
  color: var(--color-warning-hover);
}

.shield-icon {
  flex-shrink: 0;
}

/* ── 右栏：课件对照 ── */

.detail-content {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.detail-block {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.block-title {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--color-text);
}

.block-empty {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  margin: 0;
}

.page-edit {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.page-input {
  width: 72px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  color: var(--color-text);
  background: var(--color-surface);
  outline: none;
  transition: var(--duration-fast) var(--ease);
}

.page-input:focus {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px var(--color-primary-light);
}

.page-display {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-base);
  font-weight: var(--font-semibold);
  color: var(--color-text);
}

.page-num {
  min-width: 32px;
  text-align: center;
  padding: var(--space-1) var(--space-3);
  background: var(--color-surface-2);
  border-radius: var(--radius-sm);
}

.page-sep {
  color: var(--color-text-muted);
}

.ocr-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.ocr-item {
  display: flex;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: var(--color-surface-2);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  line-height: var(--leading-relaxed);
}

.ocr-page {
  flex-shrink: 0;
  font-weight: var(--font-semibold);
  color: var(--color-primary-hover);
  font-family: var(--font-mono);
}

.ocr-text {
  color: var(--color-text-secondary);
}

.kp-display {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
}

.kp-tag {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-2);
  background: var(--color-secondary-light);
  color: var(--color-secondary-hover);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
}

.kp-tag.static {
  cursor: default;
}

.kp-edit {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.kp-tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
}

.kp-remove {
  display: inline-flex;
  align-items: center;
  border: none;
  background: none;
  cursor: pointer;
  color: var(--color-secondary-hover);
  padding: 0;
  opacity: 0.6;
  transition: var(--duration-fast) var(--ease);
}

.kp-remove:hover {
  opacity: 1;
  color: var(--color-danger);
}

.kp-input {
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  color: var(--color-text);
  background: var(--color-surface);
  outline: none;
  transition: var(--duration-fast) var(--ease);
}

.kp-input:focus {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px var(--color-primary-light);
}

/* ── 状态标签 ── */

.status-tag {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  white-space: nowrap;
}

.status-tag.lg {
  padding: var(--space-1) var(--space-3);
  font-size: var(--text-sm);
}

.status-auto_accepted {
  background: var(--color-info-light);
  color: var(--color-info);
}

.status-teacher_edited {
  background: var(--color-success-light);
  color: var(--color-success-hover);
}

.status-locked {
  background: var(--color-warning-light);
  color: var(--color-warning-hover);
}

.status-rejected {
  background: var(--color-danger-light);
  color: var(--color-danger-hover);
}

/* ── 底部操作栏 ── */

.qsm-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-5);
  border-top: 1px solid var(--color-border);
  background: var(--color-surface);
  flex-shrink: 0;
}

.footer-group {
  display: flex;
  gap: var(--space-2);
}

.action-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  cursor: pointer;
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  color: var(--color-text-secondary);
  background: var(--color-surface);
  transition: var(--duration-fast) var(--ease);
}

.action-btn:hover:not(:disabled) {
  border-color: var(--color-border-hover);
  background: var(--color-surface-2);
  color: var(--color-text);
}

.action-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.action-btn.primary {
  background: var(--gradient-primary);
  color: var(--color-primary-foreground);
  border: none;
}

.action-btn.primary:hover:not(:disabled) {
  background: var(--gradient-primary-hover);
  box-shadow: var(--shadow-primary);
  color: var(--color-primary-foreground);
}

.action-btn.success {
  background: var(--gradient-success);
  color: var(--color-primary-foreground);
  border: none;
}

.action-btn.success:hover:not(:disabled) {
  box-shadow: var(--shadow-success);
  color: var(--color-primary-foreground);
}

.action-btn.warn {
  background: var(--color-warning-light);
  color: var(--color-warning-hover);
  border-color: transparent;
}

.action-btn.warn:hover:not(:disabled) {
  background: var(--color-warning);
  color: var(--color-primary-foreground);
}

.action-btn.danger {
  background: var(--color-danger-light);
  color: var(--color-danger-hover);
  border-color: transparent;
}

.action-btn.danger:hover:not(:disabled) {
  background: var(--color-danger);
  color: var(--color-primary-foreground);
}
</style>
