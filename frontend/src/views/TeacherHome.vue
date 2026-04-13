<template>
  <div class="teacher-home">
    <NavigationBar />
    <div class="teacher-content">
      <div class="welcome-section">
        <h1>👨‍🏫 教师工作台</h1>
        <p class="subtitle">管理您的智课内容，编辑知识点脚本</p>
      </div>
      
      <div class="action-cards">
        <div class="action-card" @click="goToKnowledge">
          <div class="card-icon">📚</div>
          <h3>知识图谱管理</h3>
          <p>上传文档、编辑智课脚本、生成语音</p>
        </div>
        
        <div class="action-card" @click="goToCourses">
          <div class="card-icon">📖</div>
          <h3>我的课程</h3>
          <p>查看已创建的课程列表</p>
        </div>
        
        <div class="action-card" @click="goToProfile">
          <div class="card-icon">⚙️</div>
          <h3>账户设置</h3>
          <p>修改个人信息和偏好设置</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import NavigationBar from '@/components/NavigationBar.vue'

const router = useRouter()

const goToKnowledge = () => {
  router.push('/teacher/knowledge')
}

const goToCourses = () => {
  router.push('/profile')
}

const goToProfile = () => {
  router.push('/profile')
}
</script>

<style scoped>
.teacher-home {
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.teacher-content {
  max-width: 1200px;
  margin: 0 auto;
  padding: 60px 24px;
}

.welcome-section {
  text-align: center;
  color: white;
  margin-bottom: 48px;
}

.welcome-section h1 {
  font-size: 36px;
  margin-bottom: 12px;
}

.subtitle {
  font-size: 16px;
  opacity: 0.9;
}

.action-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 24px;
}

.action-card {
  background: white;
  border-radius: 16px;
  padding: 32px;
  cursor: pointer;
  transition: all 0.3s ease;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);
}

.action-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.15);
}

.card-icon {
  font-size: 48px;
  margin-bottom: 16px;
}

.action-card h3 {
  font-size: 20px;
  color: #1f2937;
  margin-bottom: 8px;
}

.action-card p {
  font-size: 14px;
  color: #6b7280;
}
</style>
