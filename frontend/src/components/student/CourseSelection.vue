<template>
  <div class="course-selection">
    <div class="selection-header">
      <h2><BookOpen :size="28" /> 我的课程</h2>
      <p class="subtitle">选择老师制作的智课开始学习</p>
    </div>

    <div class="courses-container">
      <LoadingSpinner v-if="isLoadingCourses" text="正在加载课程..." />

      <div v-else-if="availableCourses.length === 0" class="empty-state">
        <div class="empty-icon"><BookOpen :size="64" :stroke-width="1.5" /></div>
        <h3>暂无可用课程</h3>
        <p>老师还没有发布任何智课</p>
      </div>

      <div v-else class="courses-grid">
        <div
          v-for="course in availableCourses"
          :key="course.id"
          class="course-card"
          @click="selectCourse(course)"
        >
          <div class="card-header">
            <span class="course-icon"><Ruler :size="32" /></span>
            <span class="status-badge" :class="course.status">
              {{ getStatusLabel(course.status) }}
            </span>
          </div>
          <div class="card-body">
            <h3 class="course-title">{{ course.title }}</h3>
            <p class="course-desc">{{ course.description || '暂无描述' }}</p>
            <div class="course-meta">
              <span class="meta-item"><Presentation :size="14" /> {{ course.teacher_name || '未知教师' }}</span>
              <span class="meta-item"><BookOpen :size="14" /> {{ course.total_nodes || 0 }} 个知识点</span>
              <span class="meta-item"><Hourglass :size="14" /> {{ formatDuration(course.total_duration) }}</span>
            </div>
          </div>
          <div class="card-footer">
            <button
              class="start-btn"
              @click.stop="enterCourse(course)"
              :disabled="course.status !== 'published'"
            >
              <template v-if="course.status === 'published'">
                <Rocket :size="16" /> 开始学习 <ArrowRight :size="16" />
              </template>
              <template v-else>
                <Hourglass :size="16" /> 未发布
              </template>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { inject } from 'vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import { STUDENT_LEARNING_KEY } from '@/composables/useStudentLearning.js'
import {
  BookOpen,
  Ruler,
  Presentation,
  Hourglass,
  Rocket,
  ArrowRight,
} from 'lucide-vue-next'

const {
  availableCourses,
  isLoadingCourses,
  selectCourse,
  enterCourse,
  getStatusLabel,
  formatDuration,
} = inject(STUDENT_LEARNING_KEY)
</script>

<style scoped>
.course-selection {
  height: 100%;
  padding: var(--space-5);
  overflow-y: auto;
}

.selection-header {
  margin-bottom: var(--space-5);
}

.selection-header h2 {
  font-size: var(--text-3xl);
  color: var(--color-text);
  margin-bottom: var(--space-2);
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.subtitle {
  font-size: var(--text-base);
  color: var(--color-text-secondary);
}

.courses-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
  gap: var(--space-5);
  max-width: 1400px;
}

.course-card {
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  padding: var(--space-5);
  box-shadow: var(--shadow-sm);
  cursor: pointer;
  transition: var(--transition-all);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.course-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-lg);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.course-icon {
  color: var(--color-primary);
  display: inline-flex;
}

.status-badge {
  padding: var(--space-1) var(--space-3);
  border-radius: var(--space-3);
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
}

.status-badge.published { background: var(--color-success-light); color: var(--color-success-hover); }
.status-badge.draft { background: var(--color-warning-light); color: var(--color-warning-hover); }
.status-badge.archived { background: var(--color-surface-2); color: var(--color-text-secondary); }

.course-title {
  font-size: var(--text-lg);
  font-weight: var(--font-semibold);
  color: var(--color-text);
  margin: 0;
}

.course-desc {
  font-size: var(--text-base);
  color: var(--color-text-secondary);
  line-height: 1.5;
  margin: 0;
}

.course-meta {
  display: flex;
  gap: var(--space-4);
  flex-wrap: wrap;
  font-size: 13px;
  color: var(--color-text-muted);
}

.meta-item {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

.start-btn {
  width: 100%;
  padding: var(--space-3);
  background: var(--gradient-primary);
  color: var(--color-text-inverse);
  border: none;
  border-radius: var(--radius-md);
  font-size: var(--text-base);
  font-weight: var(--font-medium);
  cursor: pointer;
  transition: var(--transition-all);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
}

.start-btn:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-primary);
}

.start-btn:disabled {
  background: linear-gradient(135deg, var(--color-text-muted), var(--color-text-secondary));
  cursor: not-allowed;
  opacity: 0.6;
}

.card-footer {
  display: flex;
  gap: var(--space-3);
}

.loading-state, .empty-state {
  text-align: center;
  padding: var(--space-10) var(--space-5);
  color: var(--color-text-secondary);
}

.empty-icon {
  margin-bottom: var(--space-4);
  color: var(--color-text-muted);
  display: flex;
  justify-content: center;
}
</style>
