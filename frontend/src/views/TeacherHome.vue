<template>
  <div class="teacher-home">
    <div class="teacher-content">
      <div class="welcome-section">
        <h1><GraduationCap class="welcome-icon" :size="32" /> 教师工作台</h1>
        <p class="subtitle">管理您的智课内容，编辑知识点脚本</p>
      </div>

      <div class="action-cards">
        <div class="action-card" @click="goToCourses">
          <div class="card-icon"><BookOpen :size="36" /></div>
          <h3>智课管理</h3>
          <p>上传文档、编辑智课脚本、生成语音</p>
        </div>

        <div class="action-card" @click="goToCreate">
          <div class="card-icon"><Plus :size="36" /></div>
          <h3>创建新课程</h3>
          <p>上传文档创建新的智课</p>
        </div>

        <div class="action-card" @click="goToProfile">
          <div class="card-icon"><Settings :size="36" /></div>
          <h3>账户设置</h3>
          <p>修改个人信息和偏好设置</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { GraduationCap, BookOpen, Plus, Settings } from 'lucide-vue-next'

const router = useRouter()

const goToCourses = () => {
  router.push('/teacher/history')
}

const goToCreate = () => {
  router.push('/teacher/create')
}

const goToProfile = () => {
  router.push('/profile')
}
</script>

<style scoped>
.teacher-home {
  min-height: calc(100vh - var(--navbar-height));
  background: var(--gradient-primary);
}

.teacher-content {
  max-width: 1000px;
  margin: 0 auto;
  padding: var(--space-10) var(--space-6);
}

.welcome-section {
  text-align: center;
  color: var(--color-text-inverse);
  margin-bottom: var(--space-8);
}

.welcome-section h1 {
  font-size: var(--text-3xl);
  margin: 0 0 var(--space-3) 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
}

.welcome-icon {
  flex-shrink: 0;
}

.subtitle {
  font-size: var(--text-base);
  opacity: 0.9;
  margin: 0;
}

.action-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: var(--space-5);
}

.action-card {
  background: var(--color-surface);
  border-radius: var(--radius-xl);
  padding: var(--space-6);
  cursor: pointer;
  transition: var(--transition-all);
  box-shadow: var(--shadow-lg);
}

.action-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-xl);
}

.card-icon {
  color: var(--color-primary);
  margin-bottom: var(--space-3);
  display: flex;
}

.action-card h3 {
  font-size: var(--text-lg);
  color: var(--color-text);
  margin: 0 0 var(--space-2) 0;
}

.action-card p {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  margin: 0;
}
</style>
