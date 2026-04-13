<template>
  <div class="student-home">
    <NavigationBar />
    <div class="student-content">
      <div class="welcome-section">
        <h1>👨‍🎓 学习中心</h1>
        <p class="subtitle">选择智课开始学习，随时提问互动</p>
      </div>
      
      <div class="course-list-section">
        <h2>📚 可选智课列表</h2>
        <div class="course-grid" v-if="courses.length > 0">
          <div 
            v-for="course in courses" 
            :key="course.id" 
            class="course-card"
            @click="selectCourse(course)"
          >
            <div class="course-cover">
              <span class="course-icon">📖</span>
            </div>
            <div class="course-info">
              <h3>{{ course.title }}</h3>
              <p class="course-meta">
                <span>{{ course.total_nodes || 0 }} 个知识点</span>
                <span>{{ formatDuration(course.total_duration) }}</span>
              </p>
              <div class="course-progress" v-if="course.progress">
                <div class="progress-bar">
                  <div class="progress-fill" :style="{ width: course.progress + '%' }"></div>
                </div>
                <span class="progress-text">{{ course.progress }}% 已学习</span>
              </div>
            </div>
          </div>
        </div>
        
        <div v-else class="empty-state">
          <div class="empty-icon">📭</div>
          <p>暂无可学习的智课</p>
          <p class="hint">请等待老师上传课程内容</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import NavigationBar from '@/components/NavigationBar.vue'
import api from '@/api/index.js'
import { showToast } from '@/utils/toast'
import { useCounterStore } from '@/stores/counter.js'

const router = useRouter()
const counter = useCounterStore()

const courses = ref([])

onMounted(() => {
  loadCourses()
})

const loadCourses = async () => {
  try {
    const res = await api.user.getMyInfo()
    if (res && res.data) {
      courses.value = res.data.courses || []
    }
  } catch (err) {
    console.log('加载课程列表失败，使用模拟数据')
    courses.value = [
      {
        id: 1,
        title: '高等数学 - 微积分基础',
        total_nodes: 12,
        total_duration: 720,
        progress: 35
      },
      {
        id: 2,
        title: '线性代数 - 矩阵运算',
        total_nodes: 8,
        total_duration: 480,
        progress: 0
      },
      {
        id: 3,
        title: '概率论与数理统计',
        total_nodes: 15,
        total_duration: 900,
        progress: 60
      }
    ]
  }
}

const selectCourse = (course) => {
  router.push({
    path: '/student/chat',
    query: { courseId: course.id, title: course.title }
  })
  showToast(`开始学习: ${course.title}`, 'success')
}

const formatDuration = (seconds) => {
  if (!seconds) return '0分钟'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}分钟`
  const hours = Math.floor(minutes / 60)
  const remainMinutes = minutes % 60
  return `${hours}小时${remainMinutes}分钟`
}
</script>

<style scoped>
.student-home {
  min-height: 100vh;
  background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%);
}

.student-content {
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

.course-list-section {
  background: white;
  border-radius: 20px;
  padding: 32px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.1);
}

.course-list-section h2 {
  font-size: 20px;
  color: #1f2937;
  margin-bottom: 24px;
}

.course-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 20px;
}

.course-card {
  background: #f8fafc;
  border-radius: 12px;
  padding: 20px;
  cursor: pointer;
  transition: all 0.3s ease;
  border: 2px solid transparent;
}

.course-card:hover {
  border-color: #0ea5e9;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.15);
}

.course-cover {
  width: 60px;
  height: 60px;
  background: linear-gradient(135deg, #0ea5e9, #0284c7);
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 16px;
}

.course-icon {
  font-size: 28px;
}

.course-info h3 {
  font-size: 16px;
  color: #1f2937;
  margin-bottom: 8px;
}

.course-meta {
  display: flex;
  gap: 16px;
  font-size: 13px;
  color: #6b7280;
  margin-bottom: 12px;
}

.course-progress {
  margin-top: 12px;
}

.progress-bar {
  height: 6px;
  background: #e5e7eb;
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 4px;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #10b981, #059669);
  border-radius: 3px;
  transition: width 0.3s ease;
}

.progress-text {
  font-size: 12px;
  color: #10b981;
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
}

.empty-icon {
  font-size: 64px;
  margin-bottom: 16px;
}

.empty-state p {
  font-size: 16px;
  color: #6b7280;
  margin-bottom: 8px;
}

.hint {
  font-size: 14px !important;
  color: #9ca3af !important;
}
</style>
