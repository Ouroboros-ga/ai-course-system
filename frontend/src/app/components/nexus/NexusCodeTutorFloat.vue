<script setup>
/**
 * NX-CT1 代码伴学浮窗：每学生的常驻 Nexus 会话壳（session_id = 'code-tutor'）。
 *
 * - 挂在 AppShell 全局 fixed 层（不进页面内部，不破坏 design.md §5 三层滚动）；
 * - 只读：绑定哪次提交仅传 run_id 引用声明，源码/判题/产物尾部由后端投影+
 *   read_my_submission 工具按需拉取；本组件不请求、不存储源码；
 * - 命名用 Nexus 品牌（"Nexus 代码伴学"），不出现 CodingAgent 独立品牌。
 */
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Send, Sparkles, Square, Wrench, X } from 'lucide-vue-next'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxError from '@/app/ui/SfxError.vue'
import { showToast } from '@/utils/toast.js'
import { renderContent } from '@/utils/markdownRenderer.js'
import {
  CODE_TUTOR_BIND_EVENT,
  CODE_TUTOR_PROBLEM_EVENT,
  CODE_TUTOR_SESSION_ID,
  getNexusSessionMessages,
  streamCodeTutorMessage,
} from '@/api/nexus.js'
import { getCodingDiagnosis, getExperimentRun } from '@/api/experiments.js'

const POS_KEY = 'sfx:code-tutor:pos'
const OPEN_KEY = 'sfx:code-tutor:open'
const BIND_KEY = 'sfx:code-tutor:binding'
const PROBLEM_KEY = 'sfx:code-tutor:problem'
const WIN_W = 680
const WIN_H = 600

const route = useRoute()

const open = ref(false)
const pos = ref({ x: 0, y: 0 })
const binding = ref(null) // { courseId, runId, outcome, passed, total }
const problem = ref(null) // { courseId, experimentId, title }
const codeSnapshot = ref('') // 编辑器代码原文（讨论材料，不持久化，随题目页事件更新）
const diagnosisShownFor = ref(null) // 已自显诊断的 runId（同 run 不重复拉取）
const verifying = ref(false)
const messages = ref([]) // { role: 'user'|'assistant', text, toolNote }
const draft = ref('')
const streaming = ref(false)
const thinking = ref(false)
const streamError = ref(null)
const aborter = ref(null)
const fabRef = ref(null)
const inputRef = ref(null)
const listRef = ref(null)
const liveMsg = ref(null) // 流式追加中的 assistant 消息（节流渲染用）

/* Markdown 节流渲染（抄 NexusPage renderedAnswer 防"冻住—突进"）：
 * renderContent 跑全量解析，流式消息 200ms 重解析一次，其余命中缓存；
 * 用户原文保持纯文本回显（忠实原文 + 不解析用户输入里的 markdown 符号）。 */
const renderCache = new WeakMap()
function renderedBody(m) {
  const text = m.text || ''
  const cached = renderCache.get(m)
  if (cached && cached.len === text.length) return cached.html
  const isLive = streaming.value && m === liveMsg.value
  const now = typeof performance !== 'undefined' && performance.now ? performance.now() : Date.now()
  if (!isLive || now - (cached?.at || 0) >= 200) {
    try {
      const html = renderContent(text)
      renderCache.set(m, { html, len: text.length, at: now })
      return html
    } catch {
      return cached?.html || ''
    }
  }
  return cached?.html || ''
}

function routeCourseId() {
  const raw = route.params?.courseId
  const id = Number(raw)
  return Number.isInteger(id) && id > 0 ? id : null
}

function defaultPos() {
  return {
    x: Math.max(16, window.innerWidth - WIN_W - 24),
    y: Math.max(16, window.innerHeight - WIN_H - 24),
  }
}

function clampPos(p) {
  // 窗口能完整放下时必须完整在视口内（杜绝"半截卡在屏幕外像乱飘"）；
  // 视口比窗口还小时贴边（右/下对齐，保证表头可抓）。
  const w = Math.min(WIN_W, window.innerWidth - 32)
  const h = Math.min(WIN_H, window.innerHeight - 32)
  const maxX = window.innerWidth - w
  const maxY = window.innerHeight - h
  return {
    x: maxX >= 0 ? Math.min(Math.max(p.x, 0), maxX) : Math.min(Math.max(p.x, maxX), 0),
    y: maxY >= 0 ? Math.min(Math.max(p.y, 0), maxY) : 0,
  }
}

function restore() {
  try {
    open.value = localStorage.getItem(OPEN_KEY) === '1'
    const raw = localStorage.getItem(POS_KEY)
    if (raw) pos.value = clampPos(JSON.parse(raw))
    else pos.value = defaultPos()
  } catch {
    pos.value = defaultPos()
  }
}

function persist() {
  try {
    localStorage.setItem(OPEN_KEY, open.value ? '1' : '0')
    localStorage.setItem(POS_KEY, JSON.stringify(pos.value))
  } catch { /* 持久化失败不影响使用 */ }
}

function toggle(force) {
  open.value = typeof force === 'boolean' ? force : !open.value
  persist()
  if (open.value) {
    loadHistory()
    maybeShowDiagnosis()
    nextTick(() => inputRef.value?.focus())
  } else {
    stopStream()
    nextTick(() => fabRef.value?.focus())
  }
}

/** 打开时若绑着失败的提交且尚未展示过诊断：自动拉取诊断详解并置顶呈现。
 * 只读 GET，不存在（404）就静默记 flag 不再打扰；网络失败不清 flag，下次重进再试。 */
async function maybeShowDiagnosis() {
  const bound = binding.value
  if (!bound?.runId || diagnosisShownFor.value === bound.runId) return
  if (!isFailedOutcome(bound.outcome)) return
  try {
    const data = await getCodingDiagnosis(bound.courseId, bound.runId)
    const record = data?.data ?? data ?? {}
    if (!record || record.run_id == null) {
      diagnosisShownFor.value = bound.runId
      return
    }
    messages.value.push({ role: 'assistant', text: formatDiagnosis(record), diagnosis: true })
    diagnosisShownFor.value = bound.runId
    await nextTick()
    scrollBottom()
  } catch {
    // 诊断拉取失败不阻断：用户仍可直接提问，伴学经提交快照作答。
  }
}

function isFailedOutcome(outcome) {
  return ['wrong_answer', 'time_limit_exceeded', 'memory_limit_exceeded',
    'runtime_error', 'compilation_error'].includes(String(outcome))
}

function formatDiagnosis(record) {
  const lines = [
    `## 诊断详解（${outcomeText(record.outcome)}${record.passed_count != null ? ` · ${record.passed_count}/${record.total_count ?? '?'}` : ''}）`,
    '',
    `**结论**：${record.summary || record.error_class || '判题未通过'}`,
  ]
  const steps = Array.isArray(record.debug_steps) ? record.debug_steps.filter(Boolean) : []
  if (steps.length) {
    lines.push('', '**分步建议**：')
    steps.slice(0, 5).forEach((step, i) => lines.push(`${i + 1}. ${step}`))
  }
  lines.push('', `（服务端诊断 \`diagnosis:${String(record.diagnosis_id || '').slice(0, 20)}\`，供参考；追问可继续深挖）`)
  return lines.join('\n')
}

/** 打开时懒加载服务端历史（与 Nexus 页面同 thread，天然续接；失败静默，下次打开重试）。 */
let historyLoaded = false
let historyLoading = false
async function loadHistory() {
  if (historyLoaded || historyLoading || messages.value.length) return
  historyLoading = true
  try {
    const res = await getNexusSessionMessages(CODE_TUTOR_SESSION_ID)
    const remote = Array.isArray(res?.messages) ? res.messages : []
    messages.value = remote.slice(-30).map((m) => ({
      role: m.role === 'assistant' ? 'assistant' : 'user',
      text: String(m.content || ''),
    }))
    historyLoaded = true
  } catch {
    // 服务端历史不可读不阻断：本窗继续可用，发送链路的错误会如实展示。
  } finally {
    historyLoading = false
    nextTick(scrollBottom)
  }
}

// ---- 拖拽（表头手柄，pointer 事件； released-motion 下仍可用，属用户直接操纵） ----
// 收尾必须三保险：pointerup（once）+ pointercancel（触摸被接管/手势打断）+
// window blur（Alt+Tab 等把松开动作落在窗口外）。任一缺席都会留下"幽灵拖拽"——
// 此后每次鼠标移动都瞬移窗口，看起来就是"乱飘"。
let drag = null
function onDragStart(event) {
  if (event.button !== undefined && event.button !== 0) return
  // 表头内的可交互元素（收起按钮等）不启动拖拽。
  if (event.target?.closest?.('button, textarea, input, a, summary')) return
  drag = { dx: event.clientX - pos.value.x, dy: event.clientY - pos.value.y }
  window.addEventListener('pointermove', onDragMove)
  window.addEventListener('pointerup', onDragEnd, { once: true })
  window.addEventListener('pointercancel', onDragEnd, { once: true })
  window.addEventListener('blur', onDragEnd, { once: true })
}
function onDragMove(event) {
  if (!drag) return
  pos.value = clampPos({ x: event.clientX - drag.dx, y: event.clientY - drag.dy })
}
function onDragEnd() {
  if (!drag) return
  drag = null
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('pointerup', onDragEnd)
  window.removeEventListener('pointercancel', onDragEnd)
  window.removeEventListener('blur', onDragEnd)
  persist()
}

// ---- 绑定：只接受事件声明 + 服务端验主（getExperimentRun 404 即拒收） ----
// 绑定落 localStorage：刷新/跨路由不丢；每次恢复都重新验主，失效静默解绑。
async function verifyBinding(courseId, runId) {
  const cid = Number(courseId)
  const rid = String(runId || '').slice(0, 64)
  if (!Number.isInteger(cid) || cid <= 0 || !rid) return null
  try {
    const data = await getExperimentRun(cid, rid)
    const run = data?.data ?? data ?? {}
    if (!run || run.run_id == null) return null
    return {
      courseId: cid,
      runId: rid,
      outcome: run.outcome ?? run.status ?? 'unknown',
      passed: run.passed_count ?? null,
      total: run.total_count ?? null,
    }
  } catch {
    return null
  }
}

function persistBinding() {
  try {
    if (binding.value) {
      localStorage.setItem(BIND_KEY, JSON.stringify({
        courseId: binding.value.courseId, runId: binding.value.runId,
      }))
    } else {
      localStorage.removeItem(BIND_KEY)
    }
  } catch { /* 持久化失败不影响使用 */ }
}

async function bindSubmission({ courseId, runId }) {
  verifying.value = true
  try {
    const next = await verifyBinding(courseId, runId)
    if (!next) {
      showToast('绑定失败：找不到该提交或无权访问', 'error')
      return
    }
    binding.value = next
    persistBinding()
    if (!open.value) toggle(true)
    showToast('已绑定本次提交，伴学可见判题摘要', 'success')
  } finally {
    verifying.value = false
  }
}

function onBindEvent(event) {
  bindSubmission(event.detail || {})
}

/** 题目关联事件（NX-CT1-R5）：题目页派发，本浮窗静默关联、不自动打开。
 * 切题（experimentId 变化）时旧提交绑定自动失效，避免把 A 题的 run 带到 B 题；
 * 同题时只更新快照/标题，不碰已有绑定（静默润物，不打扰）。 */
async function onProblemEvent(event) {
  const detail = event.detail || {}
  const cid = Number(detail.courseId)
  const eid = String(detail.experimentId || '').slice(0, 64)
  if (!Number.isInteger(cid) || cid <= 0 || !eid) return
  const switched = !problem.value || problem.value.experimentId !== eid
  problem.value = {
    courseId: cid,
    experimentId: eid,
    title: String(detail.title || '').slice(0, 200),
  }
  persistProblem()
  if ('codeSnapshot' in detail) {
    codeSnapshot.value = typeof detail.codeSnapshot === 'string' ? detail.codeSnapshot : ''
  }
  if (switched) {
    binding.value = null
    diagnosisShownFor.value = null
    persistBinding()
  }
  if (detail.runId) {
    const next = await verifyBinding(cid, detail.runId)
    if (next) {
      binding.value = next
      persistBinding()
    }
  }
}

function unbindProblem() {
  problem.value = null
  codeSnapshot.value = ''
  binding.value = null
  diagnosisShownFor.value = null
  persistProblem()
  persistBinding()
}

function persistProblem() {
  try {
    if (problem.value) {
      localStorage.setItem(PROBLEM_KEY, JSON.stringify(problem.value))
    } else {
      localStorage.removeItem(PROBLEM_KEY)
    }
  } catch { /* 持久化失败不影响使用 */ }
}

/** 恢复上次关联题目（只恢复身份，不恢复编辑器快照——快照必须由题目页现取，防 stale 代码）。 */
function restoreProblem() {
  let saved = null
  try {
    saved = JSON.parse(localStorage.getItem(PROBLEM_KEY) || 'null')
  } catch { saved = null }
  if (!saved?.experimentId) return
  problem.value = {
    courseId: Number(saved.courseId) || null,
    experimentId: String(saved.experimentId).slice(0, 64),
    title: String(saved.title || '').slice(0, 200),
  }
}

/** 恢复上次绑定：静默重验，失效（删课/无权）则静默解绑，不打扰用户。 */
async function restoreBinding() {
  let saved = null
  try {
    saved = JSON.parse(localStorage.getItem(BIND_KEY) || 'null')
  } catch { saved = null }
  if (!saved?.runId) return
  const next = await verifyBinding(saved.courseId, saved.runId)
  binding.value = next
  persistBinding()
}

function outcomeText(o) {
  const map = {
    accepted: '✓ 已通过', wrong_answer: '! 答案不对', time_limit_exceeded: '! 超时',
    memory_limit_exceeded: '! 超内存', runtime_error: '! 运行出错',
    compilation_error: '! 编译失败', pending: '◷ 判题中', running: '◷ 判题中',
    unknown: '◇ 状态未知',
  }
  return map[String(o)] || `◇ ${o}`;
}

// ---- 对话 ----
function scrollBottom() {
  const el = listRef.value
  if (!el) return
  // 仅用户停留在底部附近时跟随，避免打断回看。
  if (el.scrollHeight - el.scrollTop - el.clientHeight < 120) {
    el.scrollTop = el.scrollHeight
  }
}

function stopStream() {
  try { aborter.value?.abort() } catch { /* 忽略 */ }
  aborter.value = null
  streaming.value = false
  thinking.value = false
  liveMsg.value = null
}

async function send() {
  const text = draft.value.trim()
  if (!text || streaming.value) return
  draft.value = ''
  streamError.value = null
  messages.value.push({ role: 'user', text })
  messages.value.push({ role: 'assistant', text: '', toolNote: '' })
  streaming.value = true
  thinking.value = true
  liveMsg.value = messages.value[messages.value.length - 1]
  const ctrl = new AbortController()
  aborter.value = ctrl
  await nextTick()
  scrollBottom()
  const target = messages.value[messages.value.length - 1]
  try {
    await streamCodeTutorMessage({
      message: text,
      courseId: binding.value?.courseId ?? problem.value?.courseId ?? routeCourseId(),
      runId: binding.value?.runId ?? null,
      problemRef: problem.value ? { experiment_id: problem.value.experimentId } : null,
      codeSnapshot: codeSnapshot.value || null,
      signal: ctrl.signal,
      onEvent: ({ event, data }) => {
        if (event === 'token') {
          thinking.value = false
          target.text += data?.content || ''
          scrollBottom()
        } else if (event === 'reasoning') {
          target.reasoning = (target.reasoning || '') + (data?.content || '')
        } else if (event === 'tool_call') {
          if (data?.name === 'read_my_submission') {
            target.toolNote = '正在读取绑定的提交快照…'
          }
        } else if (event === 'tool_result') {
          if (data?.name === 'read_my_submission') {
            target.toolNote = data?.status === 'error'
              ? `提交快照读取失败（${data?.code || '未知错误'}）`
              : '已读取提交快照（含源码与判题摘要）'
          }
        } else if (event === 'error') {
          thinking.value = false
          streamError.value = {
            code: data?.code || '',
            message: data?.message || '伴学暂时不可用',
          }
        } else if (event === 'done') {
          thinking.value = false
        }
      },
    })
  } catch (error) {
    if (error?.name !== 'AbortError') {
      streamError.value = { code: error?.errorCode || '', message: error?.message || '伴学暂时不可用' }
      // 失败不吞输入：恢复上次提问，用户可直接重发。
      draft.value = text
    }
  } finally {
    streaming.value = false
    thinking.value = false
    liveMsg.value = null
    aborter.value = null
    scrollBottom()
  }
}

function onInputKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    send()
  }
}

function autoGrow() {
  const el = inputRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 132)}px`
}

watch(draft, () => nextTick(autoGrow))

onMounted(() => {
  restore()
  restoreBinding()
  restoreProblem()
  window.addEventListener(CODE_TUTOR_BIND_EVENT, onBindEvent)
  window.addEventListener(CODE_TUTOR_PROBLEM_EVENT, onProblemEvent)
  window.addEventListener('resize', onResize)
})
onBeforeUnmount(() => {
  window.removeEventListener(CODE_TUTOR_BIND_EVENT, onBindEvent)
  window.removeEventListener(CODE_TUTOR_PROBLEM_EVENT, onProblemEvent)
  window.removeEventListener('resize', onResize)
  onDragEnd()
  stopStream()
})
function onResize() {
  pos.value = clampPos(pos.value)
}
</script>

<template>
  <div class="ct-float" aria-label="Nexus 代码伴学">
    <!-- 工具球：折叠态唯一入口 -->
    <button
      v-if="!open"
      ref="fabRef"
      class="ct-fab"
      type="button"
      aria-label="打开 Nexus 代码伴学"
      title="Nexus 代码伴学"
      @click="toggle(true)"
    >
      <Sparkles :size="22" :stroke-width="1.8" />
    </button>

    <!-- 大对话窗：fixed 浮层，不挤压布局、不产生整页滚动 -->
    <section
      v-else
      class="ct-window"
      role="dialog"
      aria-modal="false"
      aria-label="Nexus 代码伴学对话窗口"
      :style="{ left: `${pos.x}px`, top: `${pos.y}px` }"
    >
      <header class="ct-header" @pointerdown="onDragStart">
        <div class="ct-title">
          <Sparkles :size="18" :stroke-width="1.8" aria-hidden="true" />
          <div>
            <h2>Nexus 代码伴学</h2>
            <p>只读你的提交快照 · 不执行代码</p>
          </div>
        </div>
        <button class="ct-icon-btn" type="button" aria-label="收起代码伴学" @click="toggle(false)">
          <X :size="18" />
        </button>
      </header>

      <!-- 关联条：题目（服务端投影题干） + 提交（服务端验主），单行 -->
      <div class="ct-binding">
        <template v-if="problem">
          <span class="ct-bind-ok" role="status">
            <span aria-hidden="true">◇</span>
            已关联《{{ problem.title || problem.experimentId.slice(0, 16) }}》
            <template v-if="codeSnapshot"> · 含编辑器快照</template>
            <template v-if="binding">
              · 提交 <code>{{ binding.runId.slice(0, 16) }}</code>
              {{ outcomeText(binding.outcome) }}
              <template v-if="binding.passed !== null"> {{ binding.passed }}/{{ binding.total }}</template>
            </template>
          </span>
          <SfxButton variant="tertiary" size="sm" @click="unbindProblem">取消关联</SfxButton>
        </template>
        <span v-else class="ct-bind-empty">
          未关联题目——从 OJ 题目页进入会自动关联题干与编辑器代码。
        </span>
      </div>

      <!-- 消息区：内部独立滚动 -->
      <div ref="listRef" class="ct-messages">
        <div v-if="!messages.length" class="ct-welcome">
          <p>我是你的代码伴学。{{ problem ? `当前关联《${problem.title || '题目'}》，` : '' }}你可以问我：</p>
          <ul>
            <li>「为什么这个用例过不了？」</li>
            <li>「编译报错是什么意思，怎么改？」</li>
            <li>「我的思路卡在哪一步？」</li>
          </ul>
          <p class="ct-welcome-note">我只能看到你本人的提交与判题摘要，看不到隐藏测试用例，也不会替你写完整答案。</p>
        </div>
        <div
          v-for="(m, i) in messages"
          :key="i"
          class="ct-msg"
          :class="m.role === 'user' ? 'is-user' : 'is-assistant'"
        >
          <p class="ct-msg-role">{{ m.role === 'user' ? '你' : '代码伴学' }}</p>
          <p v-if="m.toolNote" class="ct-tool-note">
            <Wrench :size="13" aria-hidden="true" /> {{ m.toolNote }}
          </p>
          <!-- 伴学正文走 Markdown（DOMPurify 已消毒）；用户原文纯文本回显 -->
          <div
            v-if="m.role === 'assistant'"
            class="ct-markdown-body"
            v-html="renderedBody(m)"
          />
          <p v-else class="ct-msg-text">{{ m.text }}</p>
          <details v-if="m.reasoning" class="ct-reasoning">
            <summary>思考过程</summary>
            <p>{{ m.reasoning }}</p>
          </details>
        </div>
        <div v-if="thinking" class="ct-thinking" role="status" aria-live="polite">
          <span class="ct-thinking-avatar" aria-hidden="true"><Sparkles :size="16" /></span>
          <span class="ct-thinking-dots" aria-hidden="true"><span /><span /><span /></span>
          <span>伴学思考中</span>
        </div>
        <SfxError
          v-if="streamError"
          variant="error"
          title="伴学暂时不可用"
          :description="`${streamError.message}${streamError.code ? `（${streamError.code}）` : ''}。输入框已恢复上次提问，可直接重发。`"
          @retry="() => nextTick(() => inputRef?.focus())"
        />
      </div>

      <!-- 输入区：底部固定 -->
      <footer class="ct-input">
        <textarea
          ref="inputRef"
          v-model="draft"
          rows="1"
          maxlength="10000"
          placeholder="问伴学：这段代码哪里有问题？"
          aria-label="向代码伴学提问"
          :disabled="streaming || verifying"
          @keydown="onInputKeydown"
        />
        <SfxButton
          v-if="!streaming"
          variant="primary"
          size="sm"
          :disabled="!draft.trim() || verifying"
          :loading="verifying"
          @click="send"
        >
          <Send :size="14" /> 发送
        </SfxButton>
        <SfxButton v-else variant="secondary" size="sm" @click="stopStream">
          <Square :size="14" /> 停止
        </SfxButton>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.ct-float {
  position: fixed;
  inset: 0;
  z-index: 60;
  pointer-events: none;
}
.ct-fab {
  pointer-events: auto;
  position: absolute;
  right: 24px;
  bottom: 24px;
  width: 46px;
  height: 46px;
  border-radius: var(--radius-full);
  background: var(--color-brand);
  color: var(--text-inverse);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: var(--shadow-md);
  border: 1px solid var(--ink-700);
  transition: transform var(--duration-fast) var(--ease-out), background var(--duration-fast) var(--ease-out);
}
.ct-fab:hover {
  background: var(--color-brand-hover);
  transform: scale(1.06);
}
.ct-window {
  pointer-events: auto;
  position: absolute;
  width: min(680px, calc(100vw - 32px));
  height: min(600px, calc(100dvh - 32px));
  min-width: min(360px, calc(100vw - 32px));
  min-height: 420px;
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-md);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.ct-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--border-default);
  cursor: move;
  touch-action: none;
  user-select: none;
  background: var(--surface-panel);
}
.ct-title {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  color: var(--ink-700);
  min-width: 0;
}
.ct-title h2 {
  font-size: 18px;
  line-height: 26px;
  font-weight: 600;
  color: var(--text-primary);
}
.ct-title p {
  font-size: 12px;
  line-height: 18px;
  color: var(--text-muted);
}
.ct-icon-btn {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
  cursor: pointer;
}
.ct-icon-btn:hover {
  background: var(--ink-100);
  color: var(--ink-700);
}
.ct-binding {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  border-bottom: 1px solid var(--border-subtle, #EDF0F3);
  background: var(--surface-cool);
  font-size: 13px;
  line-height: 18px;
}
.ct-bind-ok {
  color: var(--ink-700);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ct-bind-ok code {
  font-family: "JetBrains Mono", Consolas, monospace;
  font-size: 12px;
}
.ct-bind-empty {
  color: var(--text-muted);
}
.ct-messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.ct-welcome {
  font-size: 16px;
  line-height: 28px;
  color: var(--text-primary);
}
.ct-welcome ul {
  margin: var(--space-2) 0;
  padding-left: var(--space-4);
  list-style: disc;
  color: var(--text-secondary);
}
.ct-welcome-note {
  font-size: 13px;
  line-height: 18px;
  color: var(--text-muted);
}
.ct-msg {
  max-width: 100%;
}
.ct-msg.is-user {
  align-self: flex-end;
  background: var(--ink-100);
  border-radius: var(--radius-md);
  padding: var(--space-2) var(--space-3);
  max-width: 85%;
}
.ct-msg.is-assistant {
  align-self: flex-start;
  max-width: 100%;
  border-left: 3px solid var(--color-focus);
  padding-left: var(--space-3);
}
.ct-msg-role {
  font-size: 12px;
  line-height: 18px;
  color: var(--text-muted);
  margin-bottom: 2px;
}
.ct-msg-text {
  font-size: 16px;
  line-height: 28px;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}
/* 伴学 Markdown 体（规则抄 NexusPage .nx-markdown-body，收敛到本组件令牌） */
.ct-markdown-body {
  font-size: 16px;
  line-height: 28px;
  color: var(--text-primary);
  min-width: 0;
  word-break: break-word;
}
.ct-markdown-body :deep(h1),
.ct-markdown-body :deep(h2),
.ct-markdown-body :deep(h3) {
  color: var(--ink-900);
  line-height: 1.4;
  margin: 0.8em 0 0.4em;
}
.ct-markdown-body :deep(h1) { font-size: 18px; }
.ct-markdown-body :deep(h2),
.ct-markdown-body :deep(h3) { font-size: 16px; }
.ct-markdown-body :deep(p) { margin: 0.5em 0; }
.ct-markdown-body :deep(ul),
.ct-markdown-body :deep(ol) {
  margin: 0.5em 0;
  padding-left: 1.4em;
}
.ct-markdown-body :deep(ul) { list-style: disc; }
.ct-markdown-body :deep(ol) { list-style: decimal; }
.ct-markdown-body :deep(code) {
  font-family: "JetBrains Mono", Consolas, monospace;
  font-size: 12px;
  background: var(--surface-cool);
  border: 1px solid var(--border-subtle, #EDF0F3);
  border-radius: var(--radius-xs);
  padding: 1px 5px;
}
.ct-markdown-body :deep(pre) {
  background: var(--code-bg);
  color: var(--code-text);
  border-radius: var(--radius-sm);
  padding: var(--space-3);
  overflow-x: auto;
}
.ct-markdown-body :deep(pre code) {
  background: transparent;
  border: none;
  padding: 0;
  color: inherit;
}
.ct-markdown-body :deep(table) {
  border-collapse: collapse;
  width: 100%;
  font-size: 13px;
  margin: 0.6em 0;
}
.ct-markdown-body :deep(th),
.ct-markdown-body :deep(td) {
  border: 1px solid var(--border-default);
  padding: 6px 10px;
  text-align: left;
}
.ct-markdown-body :deep(th) { background: var(--surface-cool); }
.ct-markdown-body :deep(a) { color: var(--color-focus); }
.ct-markdown-body :deep(blockquote) {
  margin: 0.5em 0;
  padding: var(--space-2) var(--space-4);
  border-left: 3px solid var(--color-focus);
  background: var(--surface-cool);
  color: var(--text-secondary);
}
.ct-tool-note {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  line-height: 18px;
  color: var(--ink-500);
  margin-bottom: 4px;
}
.ct-reasoning {
  margin-top: var(--space-2);
  font-size: 13px;
  color: var(--text-muted);
}
.ct-reasoning summary {
  cursor: pointer;
}
.ct-thinking {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: 13px;
  color: var(--text-secondary);
}
.ct-thinking-avatar {
  display: flex;
  color: var(--ink-500);
  animation: ct-thinking-pulse 1.5s ease-in-out infinite;
}
.ct-thinking-dots span {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ink-500);
  margin-right: 3px;
  animation: ct-thinking-bounce 1.4s ease-in-out infinite;
}
.ct-thinking-dots span:nth-child(2) { animation-delay: 0.16s; }
.ct-thinking-dots span:nth-child(3) { animation-delay: 0.32s; }
.ct-input {
  flex-shrink: 0;
  display: flex;
  align-items: flex-end;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-top: var(--border-default);
  background: var(--surface-panel);
}
.ct-input textarea {
  flex: 1;
  min-height: 44px;
  max-height: 132px;
  resize: none;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  padding: 10px var(--space-3);
  font-size: 14px;
  line-height: 20px;
  color: var(--text-primary);
  background: var(--surface-panel);
}
.ct-input textarea:focus {
  border-color: var(--color-focus);
  box-shadow: 0 0 0 2px var(--ink-100);
}
.ct-input textarea::placeholder {
  color: var(--text-muted);
}
/* 思考动画（design.md §7.4 规范的本地实现：仅智能体状态指示可用装饰性曲线） */
@keyframes ct-thinking-pulse {
  0%, 100% { transform: scale(1); opacity: 0.85; }
  50% { transform: scale(1.06); opacity: 1; }
}
@keyframes ct-thinking-bounce {
  0%, 100% { transform: translateY(0); opacity: 0.6; }
  50% { transform: translateY(-4px); opacity: 1; }
}

</style>
