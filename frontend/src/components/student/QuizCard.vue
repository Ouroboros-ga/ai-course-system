<template>
  <div class="quiz-card">
    <div class="quiz-question">{{ quiz.question }}</div>
    <div class="quiz-options">
      <button
        v-for="(optText, optKey) in quiz.options"
        :key="optKey"
        class="quiz-option-btn"
        :class="{
          'selected': selectedAnswer === optKey,
          'correct': answerRevealed && optKey === quiz.correct_answer,
          'wrong': answerRevealed && selectedAnswer === optKey && optKey !== quiz.correct_answer,
          'disabled': answerRevealed
        }"
        :disabled="answerRevealed"
        @click="$emit('select-option', optKey)"
      >
        <span class="option-key">{{ optKey }}</span>
        <span class="option-text">{{ optText }}</span>
      </button>
    </div>
    <div v-if="answerRevealed" class="quiz-result">
      <div class="result-indicator" :class="selectedAnswer === quiz.correct_answer ? 'is-correct' : 'is-wrong'">
        <CheckCircle v-if="selectedAnswer === quiz.correct_answer" :size="16" />
        <XCircle v-else :size="16" />
        {{ selectedAnswer === quiz.correct_answer ? '回答正确！' : '回答错误' }}
      </div>
      <div class="result-explanation">
        <span class="explanation-label"><PenLine :size="14" /> 解析：</span>
        {{ quiz.explanation }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { CheckCircle, XCircle, PenLine } from 'lucide-vue-next'

defineProps({
  quiz: {
    type: Object,
    required: true,
  },
  selectedAnswer: {
    default: null,
  },
  answerRevealed: {
    type: Boolean,
    default: false,
  },
})

defineEmits(['select-option'])
</script>

<style scoped>
.quiz-card {
  margin-top: var(--space-3);
  padding: var(--space-4);
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
}

.quiz-question {
  font-size: 15px;
  font-weight: var(--font-semibold);
  color: var(--color-text);
  margin-bottom: 14px;
  line-height: 1.6;
}

.quiz-options {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.quiz-option-btn {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 14px;
  background: var(--color-surface);
  border: 2px solid var(--color-border);
  border-radius: var(--radius-md);
  cursor: pointer;
  text-align: left;
  transition: all var(--duration-normal) var(--ease);
  font-size: var(--text-sm);
  line-height: 1.5;
  color: var(--color-text-secondary);
}

.quiz-option-btn:hover:not(.disabled) {
  border-color: var(--color-primary);
  background: var(--color-secondary-light);
}

.quiz-option-btn.selected {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
}

.quiz-option-btn.correct {
  border-color: var(--color-success);
  background: var(--color-success-light);
  color: var(--color-success);
}

.quiz-option-btn.wrong {
  border-color: var(--color-danger);
  background: var(--color-danger-light);
  color: var(--color-danger);
}

.quiz-option-btn.disabled {
  cursor: default;
  opacity: 0.85;
}

.option-key {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 26px;
  height: 26px;
  border-radius: var(--radius-full);
  background: var(--color-border);
  color: var(--color-text-secondary);
  font-weight: var(--font-bold);
  font-size: 13px;
  flex-shrink: 0;
}

.quiz-option-btn.selected .option-key {
  background: var(--color-primary);
  color: var(--color-text-inverse);
}

.quiz-option-btn.correct .option-key {
  background: var(--color-success);
  color: var(--color-text-inverse);
}

.quiz-option-btn.wrong .option-key {
  background: var(--color-danger);
  color: var(--color-text-inverse);
}

.option-text {
  flex: 1;
  padding-top: 2px;
}

.quiz-result {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--color-border);
}

.result-indicator {
  font-size: 15px;
  font-weight: var(--font-semibold);
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.result-indicator.is-correct {
  color: var(--color-success);
}

.result-indicator.is-wrong {
  color: var(--color-danger);
}

.result-explanation {
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.7;
  background: var(--color-surface);
  padding: 10px 14px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--color-border);
}

.explanation-label {
  font-weight: var(--font-semibold);
  color: var(--color-text-secondary);
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}
</style>
