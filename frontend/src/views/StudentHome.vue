<template>
  <div class="student-home">
    <div class="student-content">
      <div class="welcome-section">
        <h1>👨‍🎓 学习中心</h1>
        <p class="subtitle">选择智课开始学习，随时提问互动</p>
      </div>

      <div class="tabs-section">
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'my' }"
          @click="activeTab = 'my'"
        >
          📚 我的课程 ({{ myCourses.length }})
        </button>
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'available' }"
          @click="activeTab = 'available'"
        >
          🔍 课程广场 ({{ availableCourses.length }})
        </button>
      </div>

      <div class="course-list-section">
        <!-- 我的课程（已选） -->
        <div v-if="activeTab === 'my'">
          <h2>📖 我正在学习的课程</h2>
          <LoadingSpinner v-if="isLoadingMy" text="正在加载..." />
          <div v-else-if="myCourses.length === 0" class="empty-state">
            <div class="empty-icon">📭</div>
            <p>您还没有选择任何课程</p>
            <p class="hint">去"课程广场"看看有什么有趣的课程吧</p>
            <button class="action-link" @click="activeTab = 'available'">浏览课程 →</button>
          </div>
          <div v-else class="course-grid">
            <div
              v-for="course in myCourses"
              :key="course.course_id"
              class="course-card enrolled"
            >
              <div class="card-header">
                <div class="course-cover">
                  <span class="course-icon">✅</span>
                </div>
                <span class="enrolled-badge">已选课</span>
              </div>
              <div class="course-info">
                <h3>{{ course.title }}</h3>
                <p class="teacher-name">👨‍🏫 {{ course.teacher_name }}</p>
                <p class="course-meta">
                  <span>📊 {{ course.total_nodes || 0 }} 个知识点</span>
                  <span>⏱️ {{ formatDuration(course.total_duration) }}</span>
                </p>
                <div class="course-progress">
                  <div class="progress-bar">
                    <div
                      class="progress-fill"
                      :style="{ width: course.overall_progress + '%' }"
                    ></div>
                  </div>
                  <span class="progress-text">{{ course.overall_progress }}% 已学习</span>
                </div>
                <div class="study-info" v-if="course.total_study_minutes > 0">
                  <span>📚 累计学习 {{ formatStudyTime(course.total_study_minutes) }}</span>
                  <span v-if="course.last_study_time">
                    上次学习: {{ formatTime(course.last_study_time) }}
                  </span>
                </div>
              </div>
              <div class="card-actions">
                <button class="primary-btn" @click="enterCourse(course)">
                  🚀 继续学习
                </button>
                <button class="danger-btn" @click="confirmUnenroll(course)">
                  退出课程
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- 可选课程（未选） -->
        <div v-if="activeTab === 'available'">
          <h2>🎯 课程广场 - 选择你感兴趣的课程</h2>
          <LoadingSpinner v-if="isLoadingAvailable" text="正在加载..." />
          <div v-else-if="availableCourses.length === 0" class="empty-state">
            <div class="empty-icon">📭</div>
            <p>暂无可选课程</p>
            <p class="hint">请等待老师发布新课程</p>
          </div>
          <div v-else class="course-grid">
            <div
              v-for="course in availableCourses"
              :key="course.id"
              class="course-card"
            >
              <div class="card-header">
                <div class="course-cover">
                  <span class="course-icon">📖</span>
                </div>
                <span class="status-badge">
                  👥 {{ course.student_count || 0 }} 人在学
                </span>
              </div>
              <div class="course-info">
                <h3>{{ course.title }}</h3>
                <p class="course-desc">{{ course.description || '暂无描述' }}</p>
                <p class="teacher-name">👨‍🏫 {{ course.teacher_name }}</p>
                <p class="course-meta">
                  <span>📊 {{ course.total_nodes || 0 }} 个知识点</span>
                  <span>⏱️ {{ formatDuration(course.total_duration) }}</span>
                </p>
              </div>
              <div class="card-actions">
                <button
                  class="primary-btn"
                  @click="enrollCourse(course)"
                  :disabled="isEnrolling && enrollingId === course.id"
                >
                  {{
                    isEnrolling && enrollingId === course.id
                      ? '选课中...'
                      : '✨ 选择此课程'
                  }}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import request from '@/utils/request.js'
import { showToast } from '@/utils/toast'

const router = useRouter()

const activeTab = ref('my')
const myCourses = ref([])
const availableCourses = ref([])
const isLoadingMy = ref(true)
const isLoadingAvailable = ref(true)
const isEnrolling = ref(false)
const enrollingId = ref(null)

onMounted(() => {
  loadMyCourses()
  loadAvailableCourses()
})

const loadMyCourses = async () => {
  isLoadingMy.value = true
  try {
    const data = await request({ url: '/document/my-courses', method: 'get' })
    myCourses.value = data.courses || []
  } catch (err) {
    console.error('加载我的课程失败:', err)
  } finally {
    isLoadingMy.value = false
  }
}

const loadAvailableCourses = async () => {
  isLoadingAvailable.value = true
  try {
    const data = await request({ url: '/document/courses', method: 'get' })
    const allCourses = data.courses || []

    const enrolledIds = new Set(myCourses.value.map(c => c.course_id))
    availableCourses.value = allCourses.filter(c => !enrolledIds.has(c.id))
  } catch (err) {
    console.error('加载可选课程失败:', err)
  } finally {
    isLoadingAvailable.value = false
  }
}

const enrollCourse = async (course) => {
  isEnrolling.value = true
  enrollingId.value = course.id

  try {
    const data = await request({
      url: `/document/course/${course.id}/enroll`,
      method: 'post',
    })

    if (data.already_enrolled) {
      showToast('您已经选过此课程了', 'info')
    } else if (data.reactivated) {
      showToast('重新加入课程成功！', 'success')
    } else {
      showToast(`成功加入课程《${course.title}》`, 'success')
    }

    await loadMyCourses()
    await loadAvailableCourses()
    activeTab.value = 'my'
  } catch (error) {
    showToast(error.message || '选课失败，请重试', 'error')
  } finally {
    isEnrolling.value = false
    enrollingId.value = null
  }
}

const confirmUnenroll = (course) => {
  if (!confirm(`确定要退出课程《${course.title}》吗？\n\n您的学习进度将被保留，如需继续学习可重新加入。`)) {
    return
  }

  unenrollCourse(course)
}

const unenrollCourse = async (course) => {
  try {
    await request({
      url: `/document/course/${course.course_id}/unenroll`,
      method: 'post',
    })

    showToast('已退出课程', 'success')
    await loadMyCourses()
    await loadAvailableCourses()
  } catch (error) {
    showToast(error.message || '退课失败，请重试', 'error')
  }
}

const enterCourse = (course) => {
  router.push({
    path: `/student/course/${course.course_id}`,
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

const formatStudyTime = (minutes) => {
  if (!minutes) return '0分钟'
  if (minutes < 60) return `${minutes}分钟`
  const hours = Math.floor(minutes / 60)
  const remainMinutes = minutes % 60
  return `${hours}小时${remainMinutes}分钟`
}

const formatTime = (timeStr) => {
  if (!timeStr) return ''
  const date = new Date(timeStr)
  const now = new Date()
  const diff = now - date

  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`
  if (diff < 604800000) return `${Math.floor(diff / 86400000)}天前`

  return `${date.getMonth() + 1}/${date.getDate()}`
}
</script>

<style scoped>
.student-home {
  min-height: calc(100vh - var(--navbar-height));
  background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%);
}

.student-content {
  max-width: 1200px;
  margin: 0 auto;
  padding: 40px 24px;
}

.welcome-section {
  text-align: center;
  color: white;
  margin-bottom: 32px;
}

.welcome-section h1 {
  font-size: 32px;
  margin: 0 0 12px 0;
}

.subtitle {
  font-size: 16px;
  opacity: 0.9;
  margin: 0;
}

.tabs-section {
  display: flex;
  gap: 16px;
  margin-bottom: 24px;
  justify-content: center;
}

.tab-btn {
  padding: 12px 32px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  background: rgba(255, 255, 255, 0.1);
  color: white;
  border-radius: 25px;
  font-size: 15px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s ease;
}

.tab-btn:hover {
  background: rgba(255, 255, 255, 0.2);
  transform: translateY(-2px);
}

.tab-btn.active {
  background: white;
  color: #0ea5e9;
  border-color: white;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.course-list-section {
  background: white;
  border-radius: 20px;
  padding: 28px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.1);
}

.course-list-section h2 {
  font-size: 20px;
  color: #1f2937;
  margin: 0 0 20px 0;
}

.course-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 20px;
}

.course-card {
  background: #f8fafc;
  border-radius: 12px;
  padding: 20px;
  border: 2px solid transparent;
  transition: all 0.3s ease;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.course-card:hover {
  border-color: #0ea5e9;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.15);
}

.course-card.enrolled {
  border-left: 4px solid #10b981;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.course-cover {
  width: 48px;
  height: 48px;
  background: linear-gradient(135deg, #0ea5e9, #0284c7);
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.course-card.enrolled .course-cover {
  background: linear-gradient(135deg, #10b981, #059669);
}

.course-icon {
  font-size: 24px;
}

.enrolled-badge,
.status-badge {
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
}

.enrolled-badge {
  background: #d1fae5;
  color: #065f46;
}

.status-badge {
  background: #dbeafe;
  color: #1e40af;
}

.course-info h3 {
  font-size: 16px;
  color: #1f2937;
  margin: 0 0 6px 0;
}

.course-desc {
  font-size: 13px;
  color: #6b7280;
  line-height: 1.4;
  margin: 0 0 6px 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.teacher-name {
  font-size: 13px;
  color: #6366f1;
  margin: 0 0 6px 0;
  font-weight: 500;
}

.course-meta {
  display: flex;
  gap: 12px;
  font-size: 12px;
  color: #9ca3af;
  margin: 0;
}

.course-progress {
  margin-top: 4px;
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
  font-size: 11px;
  color: #10b981;
  font-weight: 500;
}

.study-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11px;
  color: #6b7280;
}

.card-actions {
  display: flex;
  gap: 10px;
  margin-top: auto;
  padding-top: 12px;
  border-top: 1px solid #e5e7eb;
}

.primary-btn,
.danger-btn {
  flex: 1;
  padding: 10px 16px;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.primary-btn {
  background: linear-gradient(135deg, #0ea5e9, #0284c7);
  color: white;
}

.primary-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 8px rgba(14, 165, 233, 0.3);
}

.primary-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.danger-btn {
  background: #fef2f2;
  color: #dc2626;
  border: 1px solid #fecaca;
}

.danger-btn:hover {
  background: #fee2e2;
  border-color: #fca5a5;
}

.loading-state {
  text-align: center;
  padding: 40px;
  color: #6b7280;
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 12px;
}

.empty-state p {
  font-size: 15px;
  color: #6b7280;
  margin: 0 0 6px 0;
}

.hint {
  font-size: 13px !important;
  color: #9ca3af !important;
}

.action-link {
  margin-top: 16px;
  padding: 10px 24px;
  background: linear-gradient(135deg, #0ea5e9, #0284c7);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.3s ease;
}

.action-link:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.3);
}
</style>
