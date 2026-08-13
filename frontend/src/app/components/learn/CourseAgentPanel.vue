<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { BookMarked, Code2, CornerUpLeft, Lightbulb, ListChecks, LineChart, MapPinned, Mic, RefreshCw, SendHorizonal, TriangleAlert, X } from 'lucide-vue-next'
import SfxButton from '@/app/ui/SfxButton.vue'
import { useVoiceInput } from '@/features/student-learning/composables/useVoiceInput.js'

/**
 * 课程智能体面板（page-design §12.5 UNDERSTAND / §13.1 统一人格 / §6.7 SystemResponsePanel）。
 *
 * 受控接入（P1）：useLearningWorkspace.sendQuestion 现在在 cognitive_analysis 能力开关
 * 开启 + analyticsEligible（真实学生）+ studentId 三者齐备时优先调用 TeachingAgent
 * (/teaching-agent/respond)；503/失败时静默回退 V1 /chat/ask，不影响正常 Q&A。
 * 教师/助教预览视角（analyticsEligible=false）直接走 V1。
 *
 * 结构（§6.7）：①系统观察 ②依据（原文引用）③回答 ④建议下一步教学行动。
 * 回答失败 → 显式错误 + 重试；低置信 → 提示核对原文引用；无引用不伪造。
 */
const props = defineProps({
  ws: { type: Object, required: true },
  anchor: { type: Object, default: null },
  activeAdjustment: { type: Object, default: null },
  adjustmentBusy: { type: Boolean, default: false },
  adjustmentNotice: { type: String, default: '' },
})

const emit = defineEmits([
  'exit',
  'action',
  'accept-adjustment',
  'dismiss-adjustment',
  'retry-opening-review',
  'return-adjustment',
])

const rootRef = ref(null)
const inputRef = ref(null)
const listRef = ref(null)

const quickActions = [
  { id: 'rephrase', label: '换一种解释', icon: RefreshCw, prompt: '请换一种方式解释：' },
  { id: 'example', label: '举个例子', icon: Lightbulb, prompt: '请举一个具体例子说明：' },
  { id: 'quiz', label: '出一道小题', icon: ListChecks, prompt: '请针对这个知识点出一道小题考我：' },
]
const teachingActions = [{ id: 'visualize', label: '看可视化', icon: LineChart }, { id: 'practice', label: '用代码验证', icon: Code2 }]

function send(question) {
  props.ws.sendQuestion(question)
}

function handleQuick(action) {
  const base = props.ws.currentNode.value?.title || '当前知识点'
  send(`${action.prompt}${base}`)
}

function handleSubmit() {
  send(props.ws.questionDraft.value)
}

// 语音输入：录音 → 后端豆包 ASR 转写 → 文本填入问题草稿（用户确认后发送）
const {
  status: voiceStatus,
  supported: voiceSupported,
  durationMs: voiceDurationMs,
  start: startVoice,
  stop: stopVoice,
} = useVoiceInput({
  getCourseId: () => props.ws.course.value?.courseId ?? null,
  onText: (text) => {
    props.ws.questionDraft.value = text
    nextTick(() => inputRef.value?.focus())
  },
})

function handleVoiceClick() {
  if (voiceStatus.value === 'recording') {
    stopVoice()
  } else {
    startVoice()
  }
}

function formatVoiceSeconds() {
  return Math.floor(voiceDurationMs.value / 1000)
}

function handleInput(e) {
  props.ws.questionDraft.value = e.target.value
}

function retry(message) {
  if (message?.retryQuestion) send(message.retryQuestion)
}

// C1 修复：打开时焦点进入输入框；Esc 关闭；关闭后焦点回触发区（由 LearnPage 处理）
function handleKeydown(e) {
  if (e.key === 'Escape') {
    e.preventDefault()
    emit('exit')
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
  nextTick(() => inputRef.value?.focus())
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
})

watch(
  () => props.ws.messages.value.length,
  async () => {
    await nextTick()
    listRef.value?.scrollTo({ top: listRef.value.scrollHeight })
  }
)

function formatTime(seconds) {
  const value = Math.max(0, Number(seconds) || 0)
  return `${Math.floor(value / 60)}:${String(Math.floor(value % 60)).padStart(2, '0')}`
}

function reviewPage(adjustment) {
  return adjustment?.review_target?.page ?? null
}

function isActiveAdjustment(adjustment) {
  return String(props.activeAdjustment?.proposal?.adjustment_id || '') === String(adjustment?.adjustment_id || '')
}

function isReviewingAdjustment(adjustment) {
  return isActiveAdjustment(adjustment) && props.activeAdjustment?.navigationStatus === 'reviewing'
}

function isVisibleProposal(adjustment) {
  return adjustment?.status === 'proposed'
    && !adjustment?.declined_at
    && !adjustment?.invalidated_at
    && !isActiveAdjustment(adjustment)
}

function hasMessageForActiveAdjustment() {
  const adjustmentId = props.activeAdjustment?.proposal?.adjustment_id
  return Boolean(adjustmentId && props.ws.messages.value.some(message => (
    String(message.learningAdjustment?.adjustment_id || '') === String(adjustmentId)
  )))
}
</script>

<template>
  <aside ref="rootRef" class="sfx-agent" aria-label="课程智能体" @keydown="handleKeydown">
    <header class="sfx-agent-header">
      <div class="sfx-agent-anchor">
        <span class="sfx-agent-title sfx-t-ui">课程智能体</span>
        <span class="sfx-agent-anchor-text sfx-t-caption" v-if="anchor">
          锚点：{{ anchor.sourceNodeTitle }}<template v-if="anchor.sourcePage"> · 第 {{ anchor.sourcePage }} 页</template><template v-if="anchor.sourceTime != null"> · {{ formatTime(anchor.sourceTime) }}</template>
        </span>
      </div>
      <button type="button" class="sfx-agent-close" aria-label="关闭提问面板（Esc）" @click="emit('exit')">
        <X :size="18" />
      </button>
    </header>

    <div ref="listRef" class="sfx-agent-messages">
      <div v-if="!ws.messages.value.length" class="sfx-agent-greeting">
        <p class="sfx-t-body">就当前知识点向我提问。</p>
        <p class="sfx-t-caption">回答会结合当前课程内容；有来源时显示原文引用，没有可靠来源时会明确说明。</p>
      </div>

      <div v-for="message in ws.messages.value" :key="message.id"
           class="sfx-agent-message" :class="`is-${message.role}`">
        <template v-if="message.role === 'user'">
          <p class="sfx-agent-question sfx-t-ui">{{ message.content }}</p>
        </template>
        <template v-else>
          <div class="sfx-agent-answer" :class="{ 'is-error': message.error }">
            <!-- ① 系统观察（§6.7）：真实锚点上下文，非伪造 -->
            <p class="sfx-agent-observe sfx-t-caption" v-if="message.nodeId != null">
              <span class="sfx-agent-seg-label">系统观察</span>
              结合当前知识点<template v-if="message.page"> · 第 {{ message.page }} 页</template>
            </p>

            <!-- ③ 回答 -->
            <p class="sfx-agent-answer-text sfx-t-body">{{ message.content }}</p>

            <div v-if="message.lowConfidence" class="sfx-agent-lowconf sfx-t-caption">
              <TriangleAlert :size="13" /> 本次回答置信度较低，建议核对下方原文引用。
            </div>
            <div v-if="message.fallbackNotice" class="sfx-agent-lowconf sfx-t-caption">
              <TriangleAlert :size="13" /> {{ message.fallbackNotice }}
            </div>

            <!-- ② 依据：原文引用（design.md 4.5 左 3px 墨蓝边） -->
            <ul v-if="message.citations?.length" class="sfx-agent-citations">
              <li class="sfx-agent-seg-label">依据</li>
              <li v-for="(citation, index) in message.citations" :key="citation.id || index"
                  class="sfx-agent-citation">
                <BookMarked :size="13" />
                <span>{{ citation.title || citation.source || '课程资料' }}</span>
                <span v-if="citation.page != null" class="sfx-t-caption">p.{{ citation.page }}</span>
              </li>
            </ul>

            <section
              v-if="isVisibleProposal(message.learningAdjustment)"
              class="sfx-agent-adjustment"
              aria-label="学习回顾建议"
            >
              <p class="sfx-agent-adjustment-title sfx-t-ui">
                <MapPinned :size="15" /> 建议回顾第 {{ reviewPage(message.learningAdjustment) }} 页
              </p>
              <p class="sfx-t-caption">
                回顾后由你自行选择何时返回原学习位置。
              </p>
              <div class="sfx-agent-adjustment-actions">
                <SfxButton
                  variant="secondary"
                  size="sm"
                  :loading="adjustmentBusy"
                  :disabled="adjustmentBusy"
                  @click="emit('accept-adjustment', message.learningAdjustment)"
                >回顾并补充讲解</SfxButton>
                <SfxButton
                  variant="tertiary"
                  size="sm"
                  :disabled="adjustmentBusy"
                  @click="emit('dismiss-adjustment', message.learningAdjustment)"
                >继续当前位置</SfxButton>
              </div>
            </section>

            <section
              v-if="isActiveAdjustment(message.learningAdjustment)"
              class="sfx-agent-adjustment is-active"
              aria-label="正在回顾"
            >
              <template v-if="isReviewingAdjustment(message.learningAdjustment)">
                <p class="sfx-agent-adjustment-title sfx-t-ui">
                  <CornerUpLeft :size="15" /> 正在回顾，原学习位置已保留
                </p>
                <SfxButton
                  variant="secondary"
                  size="sm"
                  :loading="adjustmentBusy"
                  :disabled="adjustmentBusy"
                  @click="emit('return-adjustment')"
                >返回原学习位置</SfxButton>
              </template>
              <template v-else>
                <p class="sfx-agent-adjustment-title sfx-t-ui">
                  <TriangleAlert :size="15" /> 已确认回顾，尚未打开内容
                </p>
                <p class="sfx-t-caption">原学习位置仍已保留，打开成功后可自行返回。</p>
                <SfxButton
                  variant="secondary"
                  size="sm"
                  :loading="adjustmentBusy"
                  :disabled="adjustmentBusy"
                  @click="emit('retry-opening-review')"
                >重试打开回顾</SfxButton>
              </template>
            </section>

            <button v-if="message.error" type="button" class="sfx-agent-retry sfx-t-ui"
                    @click="retry(message)">
              <RefreshCw :size="13" /> 重试
            </button>
          </div>
        </template>
      </div>

      <section
        v-if="activeAdjustment && !hasMessageForActiveAdjustment()"
        class="sfx-agent-adjustment is-active"
        aria-label="待继续的学习回顾"
      >
        <template v-if="activeAdjustment.navigationStatus === 'reviewing'">
          <p class="sfx-agent-adjustment-title sfx-t-ui">
            <CornerUpLeft :size="15" /> 正在回顾，原学习位置已保留
          </p>
          <SfxButton
            variant="secondary"
            size="sm"
            :loading="adjustmentBusy"
            :disabled="adjustmentBusy"
            @click="emit('return-adjustment')"
          >返回原学习位置</SfxButton>
        </template>
        <template v-else>
          <p class="sfx-agent-adjustment-title sfx-t-ui">
            <TriangleAlert :size="15" /> 已确认回顾，尚未打开内容
          </p>
          <p class="sfx-t-caption">原学习位置仍已保留，打开成功后可自行返回。</p>
          <SfxButton
            variant="secondary"
            size="sm"
            :loading="adjustmentBusy"
            :disabled="adjustmentBusy"
            @click="emit('retry-opening-review')"
          >重试打开回顾</SfxButton>
        </template>
      </section>

      <p v-if="adjustmentNotice" class="sfx-agent-adjustment-notice sfx-t-caption" role="status">
        <TriangleAlert :size="13" /> {{ adjustmentNotice }}
      </p>

      <div v-if="ws.isAsking.value" class="sfx-agent-thinking sfx-t-caption" role="status">
        课程智能体正在结合当前课程内容生成回答…
      </div>
    </div>

    <footer class="sfx-agent-footer">
      <!-- ④ 建议下一步教学行动（§6.7）：真实可操作项，非伪造 -->
      <div class="sfx-agent-next">
        <span class="sfx-agent-seg-label sfx-t-caption">建议下一步</span>
        <div class="sfx-agent-quick">
          <button v-for="action in quickActions" :key="action.id" type="button"
                  class="sfx-agent-quick-btn sfx-t-sm" :disabled="ws.isAsking.value"
                  @click="handleQuick(action)">
            <component :is="action.icon" :size="14" /> {{ action.label }}
          </button>
        </div>
        <div class="sfx-agent-quick"><button v-for="action in teachingActions" :key="action.id" type="button" class="sfx-agent-quick-btn sfx-t-sm" @click="emit('action', action.id)"><component :is="action.icon" :size="14" /> {{ action.label }}</button></div>
      </div>

      <form class="sfx-agent-input" @submit.prevent="handleSubmit">
        <textarea
          ref="inputRef"
          :value="ws.questionDraft.value"
          rows="2"
          maxlength="2000"
          placeholder="就当前知识点提问…（Enter 发送，Shift+Enter 换行）"
          aria-label="向课程智能体提问"
          @input="handleInput"
          @keydown.enter.exact.prevent="handleSubmit"
        />
        <button
          v-if="voiceStatus === 'idle'"
          type="button"
          class="sfx-agent-mic"
          :disabled="!voiceSupported"
          :title="voiceSupported ? '语音输入（录音转文字）' : '当前浏览器不支持语音输入'"
          aria-label="语音输入"
          @click="handleVoiceClick"
        >
          <Mic :size="17" />
        </button>
        <button
          v-else
          type="button"
          class="sfx-agent-mic"
          :class="{ 'is-recording': voiceStatus === 'recording' }"
          :disabled="voiceStatus === 'transcribing'"
          :title="voiceStatus === 'recording' ? '点击停止录音' : '正在转写…'"
          aria-label="停止录音并转写"
          @click="handleVoiceClick"
        >
          <template v-if="voiceStatus === 'recording'">
            <span class="sfx-agent-mic-dot"></span>
            <span class="sfx-agent-mic-timer">{{ formatVoiceSeconds() }}s</span>
          </template>
          <span v-else class="sfx-agent-mic-spinner"></span>
        </button>
        <button type="submit" class="sfx-agent-send"
                :disabled="ws.isAsking.value || !ws.questionDraft.value.trim()"
                aria-label="发送问题">
          <SendHorizonal :size="17" />
        </button>
      </form>
    </footer>
  </aside>
</template>

<style scoped>
.sfx-agent {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.sfx-agent-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-4);
  border-bottom: 1px solid var(--border-subtle);
}

.sfx-agent-anchor {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  min-width: 0;
}

.sfx-agent-title { font-weight: 600; color: var(--ink-900); }
.sfx-agent-anchor-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.sfx-agent-close {
  width: 32px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  flex-shrink: 0;
}
.sfx-agent-close:hover { background: var(--surface-cool); color: var(--ink-700); }

.sfx-agent-messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.sfx-agent-greeting {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  color: var(--text-secondary);
}

.sfx-agent-message.is-user {
  align-self: flex-end;
  max-width: 88%;
}

.sfx-agent-question {
  background: var(--ink-100);
  color: var(--ink-900);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
}

.sfx-agent-message.is-assistant { max-width: 100%; }

.sfx-agent-answer {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  color: var(--text-primary);
}

.sfx-agent-answer.is-error {
  background: var(--red-100);
  border: 1px solid var(--red-300);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
}

/* 结构化分段标签（§6.7） */
.sfx-agent-seg-label {
  font-size: var(--caption-size);
  font-weight: 600;
  color: var(--text-muted);
  text-transform: none;
  letter-spacing: 0.02em;
}

.sfx-agent-observe {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--text-secondary);
}

.sfx-agent-answer-text { color: var(--text-primary); }

.sfx-agent-lowconf {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  color: var(--amber-700);
}

.sfx-agent-citations {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  background: var(--surface-cool);
  border-left: 3px solid var(--ink-500);
  border-radius: 0 var(--radius-md) var(--radius-md) 0;
  padding: var(--space-3) var(--space-4);
}

.sfx-agent-citation {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--ui-sm-size);
  color: var(--text-secondary);
}

.sfx-agent-adjustment {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--amber-300);
  border-radius: var(--radius-md);
  background: var(--amber-100);
}

.sfx-agent-adjustment.is-active {
  border-color: var(--green-300);
  background: var(--green-100);
}

.sfx-agent-adjustment-title,
.sfx-agent-adjustment-notice {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}

.sfx-agent-adjustment-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.sfx-agent-adjustment-notice { color: var(--amber-700); }

.sfx-agent-retry {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  color: var(--red-700);
  font-weight: 500;
}

.sfx-agent-thinking { color: var(--text-muted); }

.sfx-agent-footer {
  border-top: 1px solid var(--border-subtle);
  padding: var(--space-3) var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.sfx-agent-next {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.sfx-agent-quick {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.sfx-agent-quick-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  height: 30px;
  padding: 0 var(--space-3);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-default);
  background: var(--surface-panel);
  color: var(--ink-700);
}
.sfx-agent-quick-btn:hover:not(:disabled) { background: var(--surface-cool); }
.sfx-agent-quick-btn:disabled { color: var(--text-disabled); cursor: not-allowed; }

.sfx-agent-input {
  display: flex;
  align-items: flex-end;
  gap: var(--space-2);
}

.sfx-agent-input textarea {
  flex: 1;
  min-height: 44px;
  max-height: 120px;
  resize: none;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  padding: var(--space-3);
  font-family: inherit;
  font-size: var(--ui-md-size);
  color: var(--text-primary);
  background: var(--surface-panel);
}

.sfx-agent-input textarea:hover { border-color: var(--border-strong); }
.sfx-agent-input textarea:focus-visible { outline: 2px solid var(--color-focus); outline-offset: 0; }
.sfx-agent-input textarea::placeholder { color: var(--text-muted); }

.sfx-agent-send {
  width: 44px;
  height: 44px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  background: var(--color-brand);
  color: var(--text-inverse);
}
.sfx-agent-send:hover:not(:disabled) { background: var(--color-brand-hover); }
.sfx-agent-send:disabled { background: var(--border-strong); cursor: not-allowed; }

.sfx-agent-mic {
  width: 44px;
  height: 44px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  border-radius: var(--radius-md);
  border: 1px solid var(--border-default);
  background: var(--surface-panel);
  color: var(--text-secondary);
  cursor: pointer;
}
.sfx-agent-mic:hover:not(:disabled) { border-color: var(--border-strong); color: var(--ink-700); }
.sfx-agent-mic:disabled { color: var(--text-disabled); cursor: not-allowed; }
.sfx-agent-mic.is-recording {
  border-color: var(--red-500);
  background: var(--red-100);
  color: var(--red-700);
}
.sfx-agent-mic-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--red-700);
  animation: sfx-mic-pulse 1s ease-in-out infinite;
}
.sfx-agent-mic-timer {
  font-size: var(--caption-size);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.sfx-agent-mic-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid var(--border-strong);
  border-top-color: transparent;
  border-radius: 50%;
  animation: sfx-mic-spin 0.8s linear infinite;
}
@keyframes sfx-mic-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.45; transform: scale(0.8); }
}
@keyframes sfx-mic-spin {
  to { transform: rotate(360deg); }
}
</style>
