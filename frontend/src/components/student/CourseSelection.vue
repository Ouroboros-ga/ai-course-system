<template>
  <div class="course-selection">
    <div class="selection-header">
      <h2>📚 我的课程</h2>
      <p class="subtitle">选择老师制作的智课开始学习</p>
    </div>

    <div class="courses-container">
      <div v-if="isLoadingCourses" class="loading-state">
        <div class="spinner"></div>
        <span>正在加载课程...</span>
      </div>

      <div v-else-if="availableCourses.length === 0" class="empty-state">
        <div class="empty-icon">📖</div>
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
            <span class="course-icon">📐</span>
            <span class="status-badge" :class="course.status">
              {{ getStatusLabel(course.status) }}
            </span>
          </div>
          <div class="card-body">
            <h3 class="course-title">{{ course.title }}</h3>
            <p class="course-desc">{{ course.description || '暂无描述' }}</p>
            <div class="course-meta">
              <span class="meta-item">👨‍🏫 {{ course.teacher_name || '未知教师' }}</span>
              <span class="meta-item">📖 {{ course.total_nodes || 0 }} 个知识点</span>
              <span class="meta-item">⏱️ {{ formatDuration(course.total_duration) }}</span>
            </div>
          </div>
          <div class="card-footer">
            <button
              class="start-btn"
              @click.stop="enterCourse(course)"
              :disabled="course.status !== 'published'"
            >
              {{ course.status === 'published' ? '🚀 开始学习 →' : '⏳ 未发布' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { inject } from 'vue'
import { STUDENT_LEARNING_KEY } from '@/composables/useStudentLearning.js'

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
  padding: 24px;
  overflow-y: auto;
}

.selection-header {
  margin-bottom: 24px;
}

.selection-header h2 {
  font-size: 28px;
  color: #111827;
  margin-bottom: 8px;
}

.subtitle {
  font-size: 16px;
  color: #6b7280;
}

.courses-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
  gap: 20px;
  max-width: 1400px;
}

.course-card {
  background: white;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  cursor: pointer;
  transition: all 0.3s ease;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.course-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.course-icon { font-size: 32px; }

.status-badge {
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
}

.status-badge.published { background: #d1fae5; color: #065f46; }
.status-badge.draft { background: #fef3c7; color: #92400e; }
.status-badge.archived { background: #f3f4f6; color: #6b7280; }

.course-title {
  font-size: 18px;
  font-weight: 600;
  color: #111827;
  margin: 0;
}

.course-desc {
  font-size: 14px;
  color: #6b7280;
  line-height: 1.5;
  margin: 0;
}

.course-meta {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  font-size: 13px;
  color: #9ca3af;
}

.start-btn {
  width: 100%;
  padding: 10px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s ease;
}

.start-btn:hover {
  transform: scale(1.02);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4);
}

.start-btn:disabled {
  background: linear-gradient(135deg, #9ca3af, #6b7280);
  cursor: not-allowed;
  opacity: 0.6;
}

.card-footer {
  display: flex;
  gap: 10px;
}

.loading-state, .empty-state {
  text-align: center;
  padding: 60px 20px;
  color: #6b7280;
}

.spinner {
  width: 40px;
  height: 40px;
  border: 3px solid #e5e7eb;
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 16px;
}

@keyframes spin { to { transform: rotate(360deg); } }

.empty-icon { font-size: 64px; margin-bottom: 16px; }
</style>
