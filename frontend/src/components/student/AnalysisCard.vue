<template>
  <div class="analysis-card">
    <div class="analysis-header">
      <span>🧠 理解度分析</span>
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
      💡 {{ analysis.suggestions }}
    </div>
  </div>
</template>

<script setup>
import { inject } from 'vue'
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
  margin-top: 12px;
  padding: 12px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 13px;
}

.analysis-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-weight: 600;
  color: #374151;
}

.level-badge {
  padding: 2px 10px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
}

.level-badge.excellent { background: #d1fae5; color: #065f46; }
.level-badge.high { background: #dbeafe; color: #1e40af; }
.level-badge.medium { background: #fef3c7; color: #92400e; }
.level-badge.low { background: #fee2e2; color: #991b1b; }

.analysis-score {
  display: flex;
  justify-content: center;
  margin: 8px 0;
}

.score-circle {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 14px;
  background: conic-gradient(#6366f1 calc(var(--score) * 3.6deg), #e5e7eb 0);
  color: #374151;
}

.keywords-weak {
  margin: 8px 0;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}

.label { font-weight: 500; color: #6b7280; margin-right: 4px; }

.keyword-tag {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
}

.keyword-tag.weak { background: #fee2e2; color: #991b1b; }

.suggestions {
  margin-top: 8px;
  padding: 8px;
  background: #fffbeb;
  border-radius: 4px;
  font-size: 12px;
  color: #92400e;
}
</style>
