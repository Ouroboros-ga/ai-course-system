<template>
  <div class="student-home">
    <div class="student-content">
      <div class="welcome-section">
        <h1><GraduationCap :size="32" /> 学习中心</h1>
        <p class="subtitle">选择智课开始学习，随时提问互动</p>
      </div>

      <div class="tabs-section">
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'my' }"
          @click="activeTab = 'my'"
        >
          <BookOpen :size="18" /> 我的课程 ({{ myCourses.length }})
        </button>
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'available' }"
          @click="activeTab = 'available'"
        >
          <Search :size="18" /> 课程广场 ({{ availableCourses.length }})
        </button>
      </div>

      <div class="course-list-section">
        <!-- 我的课程（已选） -->
        <div v-if="activeTab === 'my'">
          <h2><BookOpen :size="20" /> 我正在学习的课程</h2>
          <LoadingSpinner v-if="isLoadingMy" text="正在加载..." />
          <div v-else-if="myCourses.length === 0" class="empty-state">
            <div class="empty-icon"><Inbox :size="48" :stroke-width="1.5" /></div>
            <p>您还没有选择任何课程</p>
            <p class="hint">去“课程广场”看看有什么有趣的课程吧</p>
            <button class="action-link" @click="activeTab = 'available'">浏览课程 <ArrowRight :size="14" /></button>
          </div>
          <div v-else class="course-grid">
            <div
              v-for="course in myCourses"
              :key="course.course_id"
              class="course-card enrolled"
            >
              <div class="card-header">
                <div class="course-cover">
                  <CheckCircle :size="24" />
                </div>
                <span class="enrolled-badge">已选课</span>
              </div>
              <div class="course-info">
                <h3>{{ course.title }}</h3>
                <p class="teacher-name"><Presentation :size="14" /> {{ course.teacher_name }}</p>
                <p class="course-meta">
                  <span><BarChart3 :size="14" /> {{ course.total_nodes || 0 }} 个知识点</span>
                  <span><Clock :size="14" /> {{ formatDuration(course.total_duration) }}</span>
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
                  <span><BookOpen :size="14" /> 累计学习 {{ formatStudyTime(course.total_study_minutes) }}</span>
                  <span v-if="course.last_study_time">
                    上次学习: {{ formatTime(course.last_study_time) }}
                  </span>
                </div>
              </div>
              <div class="card-actions">
                <button class="primary-btn" @click="enterCourse(course)">
                  <Rocket :size="16" /> 继续学习
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
          <h2><Target :size="20" /> 课程广场 - 选择你感兴趣的课程</h2>
          <LoadingSpinner v-if="isLoadingAvailable" text="正在加载..." />
          <div v-else-if="availableCourses.length === 0" class="empty-state">
            <div class="empty-icon"><Inbox :size="48" :stroke-width="1.5" /></div>
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
                  <BookOpen :size="24" />
                </div>
                <span class="status-badge">
                  <Users :size="14" /> {{ course.student_count || 0 }} 人在学
                </span>
              </div>
              <div class="course-info">
                <h3>{{ course.title }}</h3>
                <p class="course-desc">{{ course.description || '暂无描述' }}</p>
                <p class="teacher-name"><Presentation :size="14" /> {{ course.teacher_name }}</p>
                <p class="course-meta">
                  <span><BarChart3 :size="14" /> {{ course.total_nodes || 0 }} 个知识点</span>
                  <span><Clock :size="14" /> {{ formatDuration(course.total_duration) }}</span>
                </p>
              </div>
              <div class="card-actions">
                <button
                  class="primary-btn"
                  @click="enrollCourse(course)"
                  :disabled="isEnrolling && enrollingId === course.id"
                >
                  <Sparkles :size="16" />
                  {{
                    isEnrolling && enrollingId === course.id
                      ? '选课中...'
                      : '选择此课程'
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
import {
  GraduationCap,
  BookOpen,
  Search,
  Inbox,
  ArrowRight,
  CheckCircle,
  Presentation,
  BarChart3,
  Clock,
  Rocket,
  Target,
  Users,
  Sparkles,
} from 'lucide-vue-next'

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
  background: var(--gradient-primary);
}

.student-content {
  max-width: 1200px;
  margin: 0 auto;
  padding: var(--space-7) var(--space-5);
}

.welcome-section {
  text-align: center;
  color: var(--color-text-inverse);
  margin-bottom: var(--space-6);
}

.welcome-section h1 {
  font-size: var(--text-3xl);
  margin: 0 0 var(--space-3) 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
}

.subtitle {
  font-size: var(--text-base);
  opacity: 0.9;
  margin: 0;
}

.tabs-section {
  display: flex;
  gap: var(--space-4);
  margin-bottom: var(--space-5);
  justify-content: center;
}

.tab-btn {
  padding: var(--space-3) var(--space-6);
  border: 2px solid rgba(255, 255, 255, 0.3);
  background: rgba(255, 255, 255, 0.1);
  color: var(--color-text-inverse);
  border-radius: var(--radius-2xl);
  font-size: 15px;
  font-weight: var(--font-medium);
  cursor: pointer;
  transition: var(--transition-all);
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}

.tab-btn:hover {
  background: rgba(255, 255, 255, 0.2);
  transform: translateY(-2px);
}

.tab-btn.active {
  background: var(--color-surface);
  color: var(--color-primary);
  border-color: var(--color-surface);
  box-shadow: var(--shadow-md);
}

.course-list-section {
  background: var(--color-surface);
  border-radius: var(--radius-xl);
  padding: var(--space-6);
  box-shadow: var(--shadow-xl);
}

.course-list-section h2 {
  font-size: var(--text-xl);
  color: var(--color-text);
  margin: 0 0 var(--space-5) 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.course-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--space-5);
}

.course-card {
  background: var(--color-bg);
  border-radius: var(--radius-lg);
  padding: var(--space-5);
  border: 2px solid transparent;
  transition: var(--transition-all);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.course-card:hover {
  border-color: var(--color-primary);
  transform: translateY(-2px);
  box-shadow: var(--shadow-primary);
}

.course-card.enrolled {
  border-left: 4px solid var(--color-success);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.course-cover {
  width: var(--space-8);
  height: var(--space-8);
  background: var(--gradient-primary);
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-inverse);
}

.course-card.enrolled .course-cover {
  background: var(--gradient-success);
}

.course-icon {
  font-size: var(--text-2xl);
}

.enrolled-badge,
.status-badge {
  padding: var(--space-1) var(--space-3);
  border-radius: var(--space-3);
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

.enrolled-badge {
  background: var(--color-success-light);
  color: var(--color-success-hover);
}

.status-badge {
  background: var(--color-info-light);
  color: var(--color-info);
}

.course-info h3 {
  font-size: var(--text-base);
  color: var(--color-text);
  margin: 0 0 var(--space-2) 0;
}

.course-desc {
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.4;
  margin: 0 0 var(--space-2) 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.teacher-name {
  font-size: 13px;
  color: var(--color-primary);
  margin: 0 0 var(--space-2) 0;
  font-weight: var(--font-medium);
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.course-meta {
  display: flex;
  gap: var(--space-3);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  margin: 0;
}

.course-meta span {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

.course-progress {
  margin-top: var(--space-1);
}

.progress-bar {
  height: var(--space-2);
  background: var(--color-border);
  border-radius: var(--space-1);
  overflow: hidden;
  margin-bottom: var(--space-1);
}

.progress-fill {
  height: 100%;
  background: var(--gradient-success);
  border-radius: var(--space-1);
  transition: width var(--duration-slow) var(--ease);
}

.progress-text {
  font-size: 11px;
  color: var(--color-success);
  font-weight: var(--font-medium);
}

.study-info {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  font-size: 11px;
  color: var(--color-text-secondary);
}

.study-info span {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

.card-actions {
  display: flex;
  gap: var(--space-3);
  margin-top: auto;
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border);
}

.primary-btn,
.danger-btn {
  flex: 1;
  padding: var(--space-3) var(--space-4);
  border: none;
  border-radius: var(--radius-md);
  font-size: 13px;
  font-weight: var(--font-medium);
  cursor: pointer;
  transition: var(--transition-all);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
}

.primary-btn {
  background: var(--gradient-primary);
  color: var(--color-text-inverse);
}

.primary-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: var(--shadow-primary);
}

.primary-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.danger-btn {
  background: var(--color-danger-light);
  color: var(--color-danger-hover);
  border: 1px solid var(--color-danger-light);
}

.danger-btn:hover {
  background: var(--color-danger-light);
  border-color: var(--color-danger);
}

.loading-state {
  text-align: center;
  padding: var(--space-7);
  color: var(--color-text-secondary);
}

.empty-state {
  text-align: center;
  padding: var(--space-10) var(--space-5);
}

.empty-icon {
  margin-bottom: var(--space-3);
  color: var(--color-text-muted);
}

.empty-state p {
  font-size: 15px;
  color: var(--color-text-secondary);
  margin: 0 0 var(--space-2) 0;
}

.hint {
  font-size: 13px !important;
  color: var(--color-text-muted) !important;
}

.action-link {
  margin-top: var(--space-4);
  padding: var(--space-3) var(--space-5);
  background: var(--gradient-primary);
  color: var(--color-text-inverse);
  border: none;
  border-radius: var(--radius-md);
  font-size: var(--text-base);
  cursor: pointer;
  transition: var(--transition-all);
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

.action-link:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-primary);
}
</style>
