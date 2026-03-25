<template>
  <div class="my-courses">
    <div class="header">
      <button class="back-btn" @click="goBack">← 返回</button>
      <h2>我的课程</h2>
    </div>

    <!-- 我的课程核心内容 -->
    <div class="courses-list">
      <div class="course-item" v-for="course in courses" :key="course.id">
        <div class="course-icon">{{ course.icon }}</div>
        <div class="course-info">
          <div class="course-name">{{ course.name }}</div>
          <div class="course-progress">进度：{{ course.progress }}%</div>
        </div>
        <div class="course-status">{{ course.status }}</div>
      </div>
    </div>

    <!-- 新增课程按钮 -->
    <button class="add-course-btn">+ 新增课程</button>
  </div>
</template>

<script setup>
import { ref } from 'vue'

// 定义返回事件
const emit = defineEmits(['close'])

// 模拟我的课程数据const courses = ref([
  { id: 1, icon: '📚', name: 'Vue3 实战开发', progress: 85, status: '进行中' },
  { id: 2, icon: '💻', name: 'JavaScript 高级语法', progress: 60, status: '进行中' },
  { id: 3, icon: '📝', name: '前端工程化实践', progress: 100, status: '已完成' }
])

// 返回个人中心
const goBack = () => {
  emit('close')
}
</script>

<style scoped>
.my-courses {
  background: white;
  border-radius: 12px;
  padding: 24px;
  max-width: 500px;
  width: 90%;
  max-height: 90vh;
  overflow-y: auto;
  font-family: 'Segoe UI', sans-serif;
}

.header {
  display: flex;
  align-items: center;
  margin-bottom: 24px;
}

.back-btn {
  background: none;
  border: none;
  font-size: 16px;
  color: #4f46e5;
  cursor: pointer;
  margin-right: 12px;
}

.courses-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-bottom: 24px;
}

.course-item {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px;
  background: #f9fafb;
  border-radius: 8px;
}

.course-icon {
  font-size: 28px;
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #eff6ff;
  border-radius: 8px;
}

.course-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.course-name {
  font-size: 16px;
  font-weight: 600;
  color: #1f2937;
}

.course-progress {
  font-size: 14px;
  color: #6b7280;
}

.course-status {
  font-size: 14px;
  padding: 4px 8px;
  border-radius: 4px;
  background: #e5e7eb;
  color: #4b5563;
}

.course-status[data-status="进行中"] {
  background: #dbeafe;
  color: #2563eb;
}

.course-status[data-status="已完成"] {
  background: #d1fae5;
  color: #059669;
}

.add-course-btn {
  width: 100%;
  padding: 14px;
  border-radius: 8px;
  background: #6366f1;
  color: white;
  border: none;
  font-size: 16px;
  cursor: pointer;
  transition: background 0.2s;
}

.add-course-btn:hover {
  background: #4f46e5;
}
</style>
