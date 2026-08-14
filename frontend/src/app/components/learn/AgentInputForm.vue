<script setup>
import { nextTick, onMounted, ref, watch } from 'vue'
import { Mic, SendHorizonal } from 'lucide-vue-next'
import { useVoiceInput } from '@/features/student-learning/composables/useVoiceInput.js'

const props = defineProps({
  ws: { type: Object, required: true },
  autofocus: { type: Boolean, default: false },
  placeholder: { type: String, default: '就当前知识点提问…（Enter 发送，Shift+Enter 换行）' },
})

const emit = defineEmits(['submit'])

const inputRef = ref(null)

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

function handleSubmit() {
  const value = String(props.ws.questionDraft.value || '').trim()
  if (!value || props.ws.isAsking.value) return
  props.ws.sendQuestion(value)
  emit('submit', value)
}

function focusInput() {
  inputRef.value?.focus()
}

defineExpose({ focus: focusInput })

onMounted(() => {
  if (props.autofocus) nextTick(() => inputRef.value?.focus())
})

watch(() => props.autofocus, (v) => {
  if (v) nextTick(() => inputRef.value?.focus())
})
</script>

<template>
  <form class="sfx-agent-input-form" @submit.prevent="handleSubmit">
    <textarea
      ref="inputRef"
      :value="ws.questionDraft.value"
      rows="2"
      maxlength="2000"
      :placeholder="placeholder"
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
</template>

<style scoped>
.sfx-agent-input-form {
  display: flex;
  align-items: flex-end;
  gap: var(--space-2);
  padding: var(--space-3);
  background: var(--surface-panel);
  border-top: 1px solid var(--border-subtle);
}
.sfx-agent-input-form textarea {
  flex: 1;
  min-width: 0;
  resize: none;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-canvas);
  color: var(--text-primary);
  font: inherit;
  font-size: var(--ui-sm-size);
  line-height: 1.5;
  outline: none;
  transition: border-color var(--duration-fast) var(--ease-out);
}
.sfx-agent-input-form textarea:focus {
  border-color: var(--ink-500);
}
.sfx-agent-mic {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-panel);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}
.sfx-agent-mic:hover:not(:disabled) {
  color: var(--text-primary);
  border-color: var(--border-strong);
}
.sfx-agent-mic:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.sfx-agent-mic.is-recording {
  color: var(--red-500);
  border-color: var(--red-300);
  background: var(--red-50);
}
.sfx-agent-mic-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--red-500);
  animation: sfx-mic-pulse 1.2s ease-in-out infinite;
}
.sfx-agent-mic-timer {
  font-size: var(--caption-size);
  font-variant-numeric: tabular-nums;
  margin-left: 4px;
}
.sfx-agent-mic-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid var(--border-strong);
  border-top-color: transparent;
  border-radius: 50%;
  animation: sfx-spin 0.8s linear infinite;
}
.sfx-agent-send {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  border: none;
  border-radius: var(--radius-md);
  background: var(--ink-700);
  color: #fff;
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}
.sfx-agent-send:hover:not(:disabled) {
  background: var(--ink-800);
}
.sfx-agent-send:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
@keyframes sfx-mic-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(0.85); }
}
@keyframes sfx-spin {
  to { transform: rotate(360deg); }
}
</style>
