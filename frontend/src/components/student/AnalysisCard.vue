<template>
  <div class="analysis-card">
    <div class="analysis-header">
      <span class="header-label"><Brain :size="16" /> 理解度分析</span>
      <span
        class="level-badge"
        :class="analysis.level"
      >
        {{ getLevelLabel(analysis.level) }}
      </span>
    </div>
    <div class="analysis-score">
      <div class="score-circle" :style="{ '--score': analysis.score }">
        {{ (analysis.score * 100).toFixed(0) }}%
      </div>
    </div>
    <div v-if="analysis.keywordsWeak?.length" class="keywords-weak">
      <span class="label">薄弱点：</span>
      <span
        v-for="kw in analysis.keywordsWeak"
        :key="kw"
        class="keyword-tag weak"
      >{{ kw }}</span>
    </div>
    <div v-if="analysis.suggestions" class="suggestions">
      <Lightbulb :size="14" /> {{ analysis.suggestions }}
    </div>
  </div>
</template>

<script setup>
import { inject } from 'vue'
import { Brain, Lightbulb } from 'lucide-vue-next'
import { STUDENT_LEARNING_KEY } from '@/composables/useStudentLearning.js'

defineProps({
  analysis: {
    type: Object,
    required: true,
  },
})

const { getLevelLabel } = inject(STUDENT_LEARNING_KEY)
</script>

<style scoped>
.analysis-card {
  margin-top: var(--space-3);
  padding: var(--space-3);
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: 13px;
}

.analysis-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-2);
  font-weight: var(--font-semibold);
  color: var(--color-text-secondary);
}

.header-label {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

.level-badge {
  padding: 2px 10px;
  border-radius: var(--radius-lg);
  font-size: 11px;
  font-weight: var(--font-semibold);
}

.level-badge.excellent { background: var(--color-success-light); color: var(--color-success); }
.level-badge.high { background: var(--color-info-light); color: var(--color-primary-hover); }
.level-badge.medium { background: var(--color-warning-light); color: var(--color-warning-hover); }
.level-badge.low { background: var(--color-danger-light); color: var(--color-danger); }

.analysis-score {
  display: flex;
  justify-content: center;
  margin: var(--space-2) 0;
}

.score-circle {
  width: var(--space-8);
  height: var(--space-8);
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: var(--font-bold);
  font-size: var(--text-sm);
  background: conic-gradient(var(--color-primary) calc(var(--score) * 3.6deg), var(--color-border) 0);
  color: var(--color-text-secondary);
}

.keywords-weak {
  margin: var(--space-2) 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
  align-items: center;
}

.label { font-weight: var(--font-medium); color: var(--color-text-secondary); margin-right: var(--space-1); }

.keyword-tag {
  padding: 2px var(--space-2);
  border-radius: var(--radius-sm);
  font-size: 11px;
  font-weight: var(--font-medium);
}

.keyword-tag.weak { background: var(--color-danger-light); color: var(--color-danger); }

.suggestions {
  margin-top: var(--space-2);
  padding: var(--space-2);
  background: var(--color-warning-light);
  border-radius: var(--radius-sm);
  font-size: 12px;
  color: var(--color-warning-hover);
  display: flex;
  align-items: flex-start;
  gap: var(--space-1);
}
</style>
