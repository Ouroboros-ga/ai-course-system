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
        {{ selectedAnswer === quiz.correct_answer ? '✅ 回答正确！' : '❌ 回答错误' }}
      </div>
      <div class="result-explanation">
        <span class="explanation-label">📝 解析：</span>
        {{ quiz.explanation }}
      </div>
    </div>
  </div>
</template>

<script setup>
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
  margin-top: 12px;
  padding: 16px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
}

.quiz-question {
  font-size: 15px;
  font-weight: 600;
  color: #1f2937;
  margin-bottom: 14px;
  line-height: 1.6;
}

.quiz-options {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.quiz-option-btn {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 14px;
  background: white;
  border: 2px solid #e5e7eb;
  border-radius: 8px;
  cursor: pointer;
  text-align: left;
  transition: all 0.2s ease;
  font-size: 14px;
  line-height: 1.5;
  color: #374151;
}

.quiz-option-btn:hover:not(.disabled) {
  border-color: #6366f1;
  background: #f5f3ff;
}

.quiz-option-btn.selected {
  border-color: #6366f1;
  background: #eef2ff;
}

.quiz-option-btn.correct {
  border-color: #10b981;
  background: #ecfdf5;
  color: #065f46;
}

.quiz-option-btn.wrong {
  border-color: #ef4444;
  background: #fef2f2;
  color: #991b1b;
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
  border-radius: 50%;
  background: #e5e7eb;
  color: #374151;
  font-weight: 700;
  font-size: 13px;
  flex-shrink: 0;
}

.quiz-option-btn.selected .option-key {
  background: #6366f1;
  color: white;
}

.quiz-option-btn.correct .option-key {
  background: #10b981;
  color: white;
}

.quiz-option-btn.wrong .option-key {
  background: #ef4444;
  color: white;
}

.option-text {
  flex: 1;
  padding-top: 2px;
}

.quiz-result {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid #e5e7eb;
}

.result-indicator {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 10px;
}

.result-indicator.is-correct {
  color: #059669;
}

.result-indicator.is-wrong {
  color: #dc2626;
}

.result-explanation {
  font-size: 13px;
  color: #4b5563;
  line-height: 1.7;
  background: white;
  padding: 10px 14px;
  border-radius: 6px;
  border: 1px solid #e5e7eb;
}

.explanation-label {
  font-weight: 600;
  color: #374151;
}
</style>
