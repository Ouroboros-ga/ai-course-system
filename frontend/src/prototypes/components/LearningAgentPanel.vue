<script setup>
import { ref } from 'vue'
import {
  Bot, ChevronDown, ChevronUp, Copy, ExternalLink, MessageSquarePlus,
  Send, ThumbsDown, ThumbsUp, X, AlertTriangle, RotateCcw
} from 'lucide-vue-next'
import PrototypeStatusBadge from './PrototypeStatusBadge.vue'

const props = defineProps({
  answer: { type: Object, required: true },
  suggestions: { type: Array, required: true },
  generating: { type: Boolean, default: false },
  mobile: { type: Boolean, default: false },
  anchorActive: { type: Boolean, default: false }
})

const emit = defineEmits(['ask', 'close', 'locate', 'feedback', 'start-prerequisite', 'return-anchor'])

const question = ref('')
const expandedCitation = ref('citation-1')
const feedback = ref('')

const submit = (value = question.value) => {
  const normalized = value.trim()
  if (!normalized || props.generating) return
  emit('ask', normalized)
  question.value = ''
}

const chooseFeedback = (value) => {
  feedback.value = value
  emit('feedback', value)
}
</script>

<template>
  <aside class="fd-rail fd-agent" aria-label="课程智能体">
    <div class="fd-rail__header">
      <div class="fd-agent__identity">
        <span class="fd-agent__icon"><Bot :size="18" /></span>
        <div>
          <p class="fd-eyebrow">当前课程协作者</p>
          <h2>课程智能体 <span class="fd-ai-mark">AI</span></h2>
        </div>
      </div>
      <button v-if="mobile" class="fd-icon-button" type="button" aria-label="关闭课程智能体" @click="emit('close')">
        <X :size="18" />
      </button>
    </div>

    <div class="fd-agent__scroll">
      <section class="fd-suggestions" aria-labelledby="suggestion-title">
        <h3 id="suggestion-title">你可能想问</h3>
        <button v-for="item in suggestions" :key="item" type="button" @click="submit(item)">
          <MessageSquarePlus :size="15" />
          <span>{{ item }}</span>
        </button>
      </section>

      <section class="fd-answer" aria-live="polite">
        <div class="fd-answer__question">为什么 BFS 能找到距离最近的顶点？</div>
        <div class="fd-answer__meta">
          <PrototypeStatusBadge :status="generating ? 'processing' : 'generated'" :label="generating ? '正在生成' : 'AI 回答'" compact />
        </div>
        <p v-if="generating" class="fd-generating">正在结合当前知识点组织回答…</p>
        <p v-else>{{ answer.text }}</p>

        <div class="fd-citations">
          <h3>引用依据 <span>Mock 规划能力</span></h3>
          <article v-for="citation in answer.citations" :key="citation.id" class="fd-citation">
            <button
              class="fd-citation__toggle"
              type="button"
              :aria-expanded="expandedCitation === citation.id"
              @click="expandedCitation = expandedCitation === citation.id ? '' : citation.id"
            >
              <span>{{ citation.title }}</span>
              <component :is="expandedCitation === citation.id ? ChevronUp : ChevronDown" :size="16" />
            </button>
            <div v-if="expandedCitation === citation.id" class="fd-citation__body">
              <p>{{ citation.excerpt }}</p>
              <div>
                <PrototypeStatusBadge status="generated" :label="citation.label" compact />
                <button
                  class="fd-text-button"
                  type="button"
                  :disabled="!citation.locatable"
                  :title="citation.locatable ? '定位到课件位置' : '稳定定位接口尚未接入'"
                  @click="emit('locate', citation)"
                >
                  <ExternalLink :size="14" /> 定位
                </button>
              </div>
            </div>
          </article>
        </div>

        <div class="fd-confidence">
          <AlertTriangle :size="16" aria-hidden="true" />
          <p>{{ answer.confidenceText }}</p>
        </div>

        <div class="fd-answer__actions">
          <button type="button" aria-label="复制回答"><Copy :size="16" />复制</button>
          <button
            type="button"
            :class="{ 'is-active': feedback === 'helpful' }"
            aria-label="回答有帮助"
            @click="chooseFeedback('helpful')"
          ><ThumbsUp :size="16" />有帮助</button>
          <button
            type="button"
            :class="{ 'is-active': feedback === 'unhelpful' }"
            aria-label="回答没有帮助"
            @click="chooseFeedback('unhelpful')"
          ><ThumbsDown :size="16" />没帮助</button>
        </div>
      </section>

      <button v-if="anchorActive" class="fd-return-button" type="button" @click="emit('return-anchor')">
        <RotateCcw :size="16" /> 返回原讲解位置
      </button>

      <section class="fd-agent__prerequisite">
        <p class="fd-eyebrow">知识点补充建议</p>
        <strong>2.3 队列（Queue）</strong>
        <p>理解先进先出后再回到 BFS，学习路径会更顺畅。</p>
        <button class="fd-secondary-button" type="button" @click="emit('start-prerequisite')">进入补学</button>
      </section>
    </div>

    <form class="fd-composer" @submit.prevent="submit()">
      <label for="prototype-question">围绕当前知识点提问</label>
      <div>
        <textarea
          id="prototype-question"
          v-model="question"
          rows="2"
          placeholder="输入问题，Enter 发送"
          :disabled="generating"
          @keydown.enter.exact.prevent="submit()"
        ></textarea>
        <button class="fd-icon-button fd-icon-button--primary" type="submit" :disabled="!question.trim() || generating" aria-label="发送问题">
          <Send :size="18" />
        </button>
      </div>
    </form>
  </aside>
</template>
