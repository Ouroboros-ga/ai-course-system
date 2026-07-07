<template>
  <div :class="['message-row', msg.role === 'user' ? 'user-message' : 'ai-message']">
    <AgentAvatar v-if="msg.role === 'ai'" />
    <div class="avatar user-avatar" v-else><User :size="16" /></div>
    <div class="bubble" :class="msg.role === 'user' ? 'user-bubble' : 'ai-bubble'">
      <div v-if="msg.role === 'ai'" class="ai-content markdown-body" v-html="renderContent(msg.content)"></div>
      <div v-else class="user-content">{{ msg.content }}</div>

      <QuizCard
        v-if="msg.quiz"
        :quiz="msg.quiz"
        :selected-answer="msg.selectedAnswer"
        :answer-revealed="msg.answerRevealed"
        @select-option="selectQuizOption(msg, $event)"
      />

      <AnalysisCard
        v-if="msg.understandingAnalysis"
        :analysis="msg.understandingAnalysis"
      />
    </div>
  </div>
</template>

<script setup>
import { inject } from 'vue'
import { User } from 'lucide-vue-next'
import { STUDENT_LEARNING_KEY } from '@/composables/useStudentLearning.js'
import AgentAvatar from './AgentAvatar.vue'
import QuizCard from './QuizCard.vue'
import AnalysisCard from './AnalysisCard.vue'

defineProps({
  msg: {
    type: Object,
    required: true,
  },
})

const { renderContent, selectQuizOption } = inject(STUDENT_LEARNING_KEY)
</script>

<style scoped>
.message-row {
  display: flex;
  gap: var(--space-3);
  max-width: 900px;
  width: 100%;
  margin: 0 auto;
}

.user-message { flex-direction: row-reverse; }

.avatar {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-sm);
  font-weight: var(--font-bold);
  flex-shrink: 0;
}

.user-avatar {
  background: var(--color-border);
  color: var(--color-text-secondary);
}

.bubble {
  max-width: 85%;
  padding: 14px 18px;
  border-radius: var(--radius-lg);
  line-height: 1.6;
}

.ai-bubble {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-top-left-radius: 4px;
  box-shadow: var(--shadow-sm);
}

.user-bubble {
  background: var(--gradient-primary);
  color: var(--color-text-inverse);
  border-top-right-radius: 4px;
}

.ai-content, .user-content {
  word-wrap: break-word;
}

.user-content { color: var(--color-text-inverse); }

@media (max-width: 640px) {
  .avatar {
    width: 30px;
    height: 30px;
  }
}
</style>
