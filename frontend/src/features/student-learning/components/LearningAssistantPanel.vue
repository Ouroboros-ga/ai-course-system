<template>
  <aside class="sl-assistant" aria-label="课程智能体">
    <header class="sl-panel-heading">
      <div>
        <span><Bot :size="17" /> 课程智能体</span>
        <small>基于当前课程与知识点回答</small>
      </div>
      <button
        v-if="closable"
        type="button"
        class="sl-icon-button"
        aria-label="收起课程智能体"
        @click="$emit('close')"
      >
        <PanelRightClose :size="18" />
      </button>
    </header>

    <div ref="messageListRef" class="sl-assistant__messages" aria-live="polite">
      <div v-if="messages.length === 0" class="sl-assistant-welcome">
        <div><Sparkles :size="19" /></div>
        <strong>围绕当前讲解继续理解</strong>
        <p>你可以询问概念、公式或当前课件内容。回答是否包含引用，取决于后端实际返回。</p>
        <button type="button" @click="$emit('ask', '请解释当前知识点的核心概念')">
          解释当前知识点
        </button>
      </div>

      <article
        v-for="message in messages"
        :key="message.id"
        class="sl-message"
        :class="['is-' + message.role, { 'is-error': message.error }]"
      >
        <div class="sl-message__meta">
          <UserRound v-if="message.role === 'user'" :size="15" />
          <Bot v-else :size="15" />
          <span>{{ message.role === 'user' ? '我' : '课程智能体' }}</span>
          <small v-if="message.page">第 {{ message.page }} 页</small>
        </div>
        <div
          v-if="message.role === 'assistant'"
          class="sl-message__content markdown-body"
          v-html="renderContent(message.content)"
        ></div>
        <p v-else class="sl-message__content">{{ message.content }}</p>

        <div v-if="message.citations?.length" class="sl-citations">
          <strong>回答来源</strong>
          <button
            v-for="(citation, index) in message.citations"
            :key="citation.id || index"
            type="button"
            disabled
            title="当前接口未提供可靠定位动作"
          >
            {{ citation.title || citation.source || '课程资料' }}
          </button>
        </div>
        <p v-if="message.lowConfidence" class="sl-confidence-warning">
          <CircleAlert :size="15" /> 当前回答置信度较低，请结合课程原文核对。
        </p>
        <button
          v-if="message.error && message.retryQuestion"
          type="button"
          class="sl-retry-link"
          @click="$emit('ask', message.retryQuestion)"
        >
          重新提问
        </button>
      </article>

      <div v-if="isAsking" class="sl-thinking" role="status">
        <LoaderCircle :size="17" class="sl-spin" /> 正在结合当前课程内容回答…
      </div>
    </div>

    <form class="sl-question-box" @submit.prevent="$emit('ask')">
      <label>
        <span class="sl-visually-hidden">向课程智能体提问</span>
        <textarea
          :value="draft"
          rows="2"
          placeholder="针对当前知识点提问…"
          :disabled="isAsking"
          @input="$emit('update:draft', $event.target.value)"
          @keydown.ctrl.enter.prevent="$emit('ask')"
          @keydown.meta.enter.prevent="$emit('ask')"
        ></textarea>
      </label>
      <div>
        <span>Ctrl + Enter 发送</span>
        <button
          type="submit"
          :disabled="isAsking || !draft.trim()"
          aria-label="发送问题"
        >
          <SendHorizontal :size="17" />
          发送
        </button>
      </div>
    </form>
  </aside>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'
import {
  Bot,
  CircleAlert,
  LoaderCircle,
  PanelRightClose,
  SendHorizontal,
  Sparkles,
  UserRound,
} from 'lucide-vue-next'
import { renderContent } from '@/utils/markdownRenderer.js'

const props = defineProps({
  messages: { type: Array, default: () => [] },
  draft: { type: String, default: '' },
  isAsking: { type: Boolean, default: false },
  closable: { type: Boolean, default: true },
})

defineEmits(['ask', 'update:draft', 'close'])

const messageListRef = ref(null)

watch(
  () => [props.messages.length, props.isAsking],
  async () => {
    await nextTick()
    if (messageListRef.value) {
      messageListRef.value.scrollTop = messageListRef.value.scrollHeight
    }
  }
)
</script>