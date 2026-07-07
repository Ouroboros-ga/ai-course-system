<template>
  <div class="my-courses">
    <div class="header">
      <button class="back-btn" @click="goBack"><ArrowLeft :size="16" /> 返回</button>
      <h2>我的课程</h2>
    </div>

    <!-- 我的课程核心内容 -->
    <div class="courses-list">
      <div class="course-item" v-for="course in courses" :key="course.id">
        <div class="course-icon"><component :is="iconMap[course.icon]" :size="24" /></div>
        <div class="course-info">
          <div class="course-name">{{ course.name }}</div>
          <div class="course-progress">进度：{{ course.progress }}%</div>
        </div>
        <div class="course-status">{{ course.status }}</div>
      </div>
    </div>

    <!-- 新增课程按钮 -->
    <button class="add-course-btn"><Plus :size="16" /> 新增课程</button>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ArrowLeft, BookOpen, Code, FileText, Plus } from 'lucide-vue-next'

const iconMap = {
  book: BookOpen,
  code: Code,
  file: FileText
}

// 定义返回事件
const emit = defineEmits(['close'])

// 模拟我的课程数据
const courses = ref([
  { id: 1, icon: 'book', name: 'Vue3 实战开发', progress: 85, status: '进行中' },
  { id: 2, icon: 'code', name: 'JavaScript 高级语法', progress: 60, status: '进行中' },
  { id: 3, icon: 'file', name: '前端工程化实践', progress: 100, status: '已完成' }
])

// 返回个人中心
const goBack = () => {
  emit('close')
}
</script>

<style scoped>
.my-courses {
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  padding: var(--space-5);
  max-width: 500px;
  width: 90%;
  max-height: 90vh;
  overflow-y: auto;
  font-family: var(--font-sans);
}

.header {
  display: flex;
  align-items: center;
  margin-bottom: var(--space-5);
}

.back-btn {
  background: none;
  border: none;
  font-size: var(--text-base);
  color: var(--color-primary);
  cursor: pointer;
  margin-right: var(--space-3);
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.courses-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  margin-bottom: var(--space-5);
}

.course-item {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-4);
  background: var(--color-surface-2);
  border-radius: var(--radius-md);
}

.course-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: var(--space-8);
  height: var(--space-8);
  background: var(--color-primary-light);
  border-radius: var(--radius-md);
  color: var(--color-primary);
  flex-shrink: 0;
}

.course-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.course-name {
  font-size: var(--text-base);
  font-weight: var(--font-semibold);
  color: var(--color-text);
}

.course-progress {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.course-status {
  font-size: var(--text-sm);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--color-border);
  color: var(--color-text-secondary);
}

.course-status[data-status="进行中"] {
  background: var(--color-info-light);
  color: var(--color-info);
}

.course-status[data-status="已完成"] {
  background: var(--color-success-light);
  color: var(--color-success-hover);
}

.add-course-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  width: 100%;
  padding: 14px;
  border-radius: var(--radius-md);
  background: var(--color-primary);
  color: var(--color-text-inverse);
  border: none;
  font-size: var(--text-base);
  cursor: pointer;
  transition: background var(--duration-normal) var(--ease);
}

.add-course-btn:hover {
  background: var(--color-primary-hover);
}

@media (max-width: 768px) {
  .my-courses {
    width: 95%;
    padding: var(--space-4);
  }
}
</style>
