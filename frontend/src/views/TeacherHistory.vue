<template>
  <div class="teacher-history">
    <div class="history-container">
      <div class="page-header">
        <h1>📚 课程管理</h1>
        <p class="subtitle">查看和管理您创建的所有课程以及学生学习状态</p>
        <router-link to="/teacher/create" class="create-new-btn">
          ➕ 创建新课程
        </router-link>
      </div>

      <!-- 统计概览 -->
      <div class="page-stats-overview">
        <div class="page-stat-card">
          <div class="page-stat-icon">📚</div>
          <div class="page-stat-info">
            <div class="page-stat-number">{{ stats.courseCount }}</div>
            <div class="page-stat-label">智课数量</div>
          </div>
        </div>
        <div class="page-stat-card">
          <div class="page-stat-icon">👥</div>
          <div class="page-stat-info">
            <div class="page-stat-number">{{ stats.studentCount }}</div>
            <div class="page-stat-label">学生人数</div>
          </div>
        </div>
        <div class="page-stat-card">
          <div class="page-stat-icon">📢</div>
          <div class="page-stat-info">
            <div class="page-stat-number">{{ publishedCount }}</div>
            <div class="page-stat-label">已发布课程</div>
          </div>
        </div>
      </div>

      <!-- 课程列表 -->
      <div class="courses-section">
        <div v-if="isLoading" class="loading-state">
          <div class="spinner"></div>
          <span>正在加载课程...</span>
        </div>

        <div v-else-if="courses.length === 0" class="empty-state">
          <div class="empty-icon">📖</div>
          <h3>暂无历史课程</h3>
          <p>您还没有创建任何课程，点击上方按钮开始创建您的第一门智课</p>
          <router-link to="/teacher/create" class="start-create-btn">
            开始创建 →
          </router-link>
        </div>

        <div v-else class="courses-grid">
          <div
            v-for="course in courses"
            :key="course.id"
            class="course-card"
            @click="selectCourse(course)"
            :class="{ selected: selectedCourse?.id === course.id }"
          >
            <div class="card-header">
              <span class="course-icon">📐</span>
              <span class="status-badge" :class="course.status">
                {{ getStatusLabel(course.status) }}
              </span>
              <span class="create-time">{{ formatTime(course.created_at) }}</span>
            </div>

            <div class="card-body">
              <h3 class="course-title">{{ course.title }}</h3>
              <p class="course-desc">{{ course.description || '暂无描述' }}</p>

              <div class="course-meta">
                <span class="meta-item">📊 {{ course.total_nodes || 0 }} 个知识点</span>
                <span class="meta-item">⏱️ {{ formatDuration(course.total_duration) }}</span>
                <span class="meta-item">👥 {{ course.student_count || 0 }} 名学生</span>
              </div>

              <div v-if="course.stats" class="quick-stats">
                <div class="quick-stat-item">
                  <span class="quick-stat-label">平均进度</span>
                  <span class="quick-stat-value">{{ course.stats.avg_progress || 0 }}%</span>
                </div>
                <div class="quick-stat-item">
                  <span class="quick-stat-label">平均理解度</span>
                  <span class="quick-stat-value">{{ course.stats.avg_understanding || 0 }}%</span>
                </div>
              </div>
            </div>

            <div class="card-footer">
              <button class="action-btn view-btn" @click.stop="viewCourseDetail(course)">
                查看详情
              </button>
              <button
                class="action-btn students-btn"
                @click.stop="viewStudents(course)"
              >
                👥 学生状态 ({{ course.student_count || 0 }})
              </button>
              <button
                v-if="course.status === 'draft'"
                class="action-btn publish-btn"
                @click.stop="publishCourse(course)"
                :disabled="isPublishing"
              >
                {{ isPublishing && publishingId === course.id ? '发布中...' : '🚀 发布课程' }}
              </button>
              <button
                v-else-if="course.status === 'published'"
                class="action-btn unpublish-btn"
                @click.stop="unpublishCourse(course)"
                :disabled="isPublishing"
              >
                {{ isPublishing && publishingId === course.id ? '处理中...' : '📢 已发布' }}
              </button>
              <button
                class="action-btn delete-btn"
                @click.stop="deleteCourse(course)"
                :disabled="isDeleting && deletingId === course.id"
              >
                {{ isDeleting && deletingId === course.id ? '删除中...' : '🗑️ 删除' }}
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 学生详情面板 -->
      <div v-if="selectedCourse && showStudentPanel" class="student-panel">
        <div class="panel-header">
          <h3>👥 《{{ selectedCourse.title }}》- 学生学习状态</h3>
          <button class="close-btn" @click="closeStudentPanel">✕</button>
        </div>

        <div v-if="isLoadingStudents" class="loading-state small">
          <div class="spinner small"></div>
          <span>加载学生数据...</span>
        </div>

        <div v-else-if="students.length === 0" class="no-students">
          暂无学生选择此课程
        </div>

        <div v-else class="students-content">
          <!-- 统计概览 -->
          <div class="panel-stats-overview">
            <div class="panel-stat-card">
              <div class="panel-stat-number">{{ courseStats.totalStudents || 0 }}</div>
              <div class="panel-stat-label">选课人数</div>
            </div>
            <div class="panel-stat-card">
              <div class="panel-stat-number">{{ courseStats.avgProgress || 0 }}%</div>
              <div class="panel-stat-label">平均进度</div>
            </div>
            <div class="panel-stat-card">
              <div class="panel-stat-number">{{ courseStats.avgUnderstanding || 0 }}%</div>
              <div class="panel-stat-label">平均理解度</div>
            </div>
            <div class="panel-stat-card">
              <div class="panel-stat-number">{{ courseStats.avgStudyHoursPerStudent || 0 }}h</div>
              <div class="panel-stat-label">学生平均学习时长</div>
            </div>
          </div>

          <!-- 进度分布（饼状图 + 条形图） -->
          <div v-if="courseStats.progressDistribution" class="progress-distribution">
            <h4>📊 学习进度分布</h4>
            <div class="chart-row">
              <div class="pie-chart-container">
                <Pie :data="pieChartData" :options="pieChartOptions" />
              </div>
              <div class="dist-list">
                <div v-for="item in progressLabels" :key="item.label" class="dist-item">
                  <span class="dist-color-dot" :class="'dot-' + item.key"></span>
                  <span class="dist-label">{{ item.label }}</span>
                  <div class="dist-bar-bg">
                    <div
                      class="dist-bar-fill"
                      :style="{ width: getDistPercent(item.count) + '%' }"
                      :class="'dist-' + item.key"
                    ></div>
                  </div>
                  <span class="dist-count">{{ item.count }}人</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 按节点的学习进度饼状图 -->
          <div v-if="nodeProgressData.length > 0" class="node-progress-section">
            <h4>📖 各知识点完成率</h4>
            <div class="node-chart-container">
              <Doughnut :data="nodeChartData" :options="nodeChartOptions" />
            </div>
            <div class="node-progress-list">
              <div
                v-for="node in nodeProgressData"
                :key="node.node_id"
                class="node-progress-item"
              >
                <div class="node-info-row">
                  <span class="node-type-icon">{{ getNodeTypeIcon(node.node_type) }}</span>
                  <span class="node-title-text" :title="node.title">{{ node.title }}</span>
                  <span v-if="node.is_key_point" class="key-point-badge">重点</span>
                </div>
                <div class="node-progress-bar-row">
                  <div class="node-progress-bar-bg">
                    <div
                      class="node-progress-bar-fill"
                      :style="{ width: node.completion_rate + '%' }"
                      :class="getNodeProgressClass(node.completion_rate)"
                    ></div>
                  </div>
                  <span class="node-progress-text">{{ node.completion_rate }}%</span>
                  <span class="node-completed-count">{{ node.completed_count }}/{{ node.total_students }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 学生列表 -->
          <div class="students-list">
            <h4>学生详情列表</h4>
            <div class="list-header-row">
              <span class="col-name">学生姓名</span>
              <span class="col-progress">学习进度</span>
              <span class="col-understanding">理解度</span>
              <span class="col-time">学习时长</span>
            </div>
            <div
              v-for="student in students"
              :key="student.enrollmentId"
              class="student-row"
            >
              <span class="col-name student-name">{{ student.username }}</span>
              <span class="col-progress">
                <div class="mini-progress-wrap">
                  <div class="mini-progress-bar">
                    <div
                      class="mini-progress-fill"
                      :style="{ width: student.progress + '%' }"
                      :class="getProgressClass(student.progress)"
                    ></div>
                  </div>
                  <span class="progress-text">{{ student.progress }}%</span>
                </div>
              </span>
              <span class="col-understanding">
                <span
                  class="understanding-badge"
                  :class="'level-' + student.level"
                >{{ getLevelLabel(student.level) }}</span>
              </span>
              <span class="col-time">{{ formatStudyTime(student.studyMinutes) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Pie, Doughnut } from 'vue-chartjs'
import {
  Chart as ChartJS,
  ArcElement,
  Tooltip,
  Legend,
  CategoryScale,
} from 'chart.js'
import api from '@/api/index.js'
import request from '@/utils/request.js'
import { showToast } from '@/utils/toast'

ChartJS.register(ArcElement, Tooltip, Legend, CategoryScale)

const router = useRouter()

const courses = ref([])
const isLoading = ref(true)
const selectedCourse = ref(null)
const showStudentPanel = ref(false)
const isPublishing = ref(false)
const publishingId = ref(null)
const isDeleting = ref(false)
const deletingId = ref(null)

const stats = ref({
  courseCount: 0,
  studentCount: 0,
})

const publishedCount = computed(() => {
  return courses.value.filter(c => c.status === 'published').length
})

const students = ref([])
const isLoadingStudents = ref(false)
const courseStats = ref({
  totalStudents: 0,
  avgProgress: 0,
  avgUnderstanding: 0,
  avgStudyHoursPerStudent: 0,
  progressDistribution: null,
})

const nodeProgressData = ref([])

const PROGRESS_COLORS = {
  not_started: '#d1d5db',
  beginner: '#93c5fd',
  intermediate: '#a78bfa',
  advanced: '#86efac',
  completed: '#34d399',
}

const progressLabels = computed(() => {
  const dist = courseStats.value.progressDistribution || {}
  return [
    { key: 'not_started', label: '未开始', count: dist.not_started || 0 },
    { key: 'beginner', label: '初学', count: dist.beginner || 0 },
    { key: 'intermediate', label: '进阶', count: dist.intermediate || 0 },
    { key: 'advanced', label: '熟练', count: dist.advanced || 0 },
    { key: 'completed', label: '完成', count: dist.completed || 0 },
  ]
})

const pieChartData = computed(() => ({
  labels: progressLabels.value.map(i => i.label),
  datasets: [{
    data: progressLabels.value.map(i => i.count),
    backgroundColor: progressLabels.value.map(i => PROGRESS_COLORS[i.key]),
    borderWidth: 2,
    borderColor: '#ffffff',
  }],
}))

const pieChartOptions = computed(() => ({
  responsive: true,
  maintainAspectRatio: true,
  plugins: {
    legend: {
      position: 'bottom',
      labels: {
        padding: 12,
        usePointStyle: true,
        font: { size: 12 },
      },
    },
    tooltip: {
      callbacks: {
        label(ctx) {
          const total = ctx.dataset.data.reduce((a, b) => a + b, 0)
          const pct = total > 0 ? Math.round(ctx.parsed / total * 100) : 0
          return `${ctx.label}: ${ctx.parsed}人 (${pct}%)`
        },
      },
    },
  },
}))

const nodeChartData = computed(() => {
  const nodes = nodeProgressData.value
  if (nodes.length === 0) return { labels: [], datasets: [] }

  const completedCounts = nodes.map(n => n.completed_count)
  const remainingCounts = nodes.map(n => n.total_students - n.completed_count)

  return {
    labels: nodes.map(n => n.title),
    datasets: [
      {
        label: '已完成',
        data: completedCounts,
        backgroundColor: '#34d399',
        borderWidth: 1,
        borderColor: '#ffffff',
      },
      {
        label: '未完成',
        data: remainingCounts,
        backgroundColor: '#e5e7eb',
        borderWidth: 1,
        borderColor: '#ffffff',
      },
    ],
  }
})

const nodeChartOptions = computed(() => ({
  responsive: true,
  maintainAspectRatio: true,
  plugins: {
    legend: {
      position: 'bottom',
      labels: {
        padding: 12,
        usePointStyle: true,
        font: { size: 12 },
      },
    },
    tooltip: {
      callbacks: {
        label(ctx) {
          const node = nodeProgressData.value[ctx.dataIndex]
          if (!node) return ''
          if (ctx.datasetIndex === 0) {
            return `已完成: ${node.completed_count}人 (${node.completion_rate}%)`
          }
          return `未完成: ${node.total_students - node.completed_count}人`
        },
      },
    },
  },
}))

function getStatusLabel(status) {
  const map = { published: '已发布', draft: '草稿', archived: '已归档' }
  return map[status] || status
}

function formatTime(timestamp) {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

function formatDuration(seconds) {
  if (!seconds) return '0分钟'
  const mins = Math.floor(seconds / 60)
  return `${mins}分钟`
}

function formatStudyTime(minutes) {
  if (!minutes) return '0分钟'
  if (minutes < 60) return `${minutes}分钟`
  const hours = Math.floor(minutes / 60)
  const mins = minutes % 60
  return `${hours}小时${mins}分钟`
}

function getDistPercent(count) {
  const total = courseStats.value.totalStudents || 1
  return Math.round((count / total) * 100)
}

function getProgressClass(progress) {
  if (progress >= 80) return 'high'
  if (progress >= 50) return 'medium'
  return 'low'
}

function getLevelLabel(level) {
  const labels = { excellent: '优秀', high: '良好', medium: '一般', low: '需加强', unknown: '未知' }
  return labels[level] || level
}

function getNodeTypeIcon(type) {
  const icons = {
    lecture: '📖', question: '❓', breakpoint: '🔖',
    summary: '📋', video: '🎬', interactive: '💬',
  }
  return icons[type] || '📄'
}

function getNodeProgressClass(rate) {
  if (rate >= 80) return 'node-high'
  if (rate >= 50) return 'node-medium'
  if (rate > 0) return 'node-low'
  return 'node-none'
}

async function loadCourses() {
  isLoading.value = true
  try {
    const data = await request({ url: '/document/courses', method: 'get' })
    courses.value = data.courses || []
  } catch (error) {
    showToast('加载课程失败', 'error')
  } finally {
    isLoading.value = false
  }
}

function selectCourse(course) {
  selectedCourse.value = course
}

function viewCourseDetail(course) {
  router.push(`/teacher/course/${course.id}`)
}

async function viewStudents(course) {
  selectedCourse.value = course
  showStudentPanel.value = true
  await loadStudentsAndStats(course.id)
}

function closeStudentPanel() {
  showStudentPanel.value = false
  selectedCourse.value = null
  students.value = []
  nodeProgressData.value = []
}

async function publishCourse(course) {
  isPublishing.value = true
  publishingId.value = course.id

  try {
    await request({ url: `/document/course/${course.id}/publish`, method: 'post' })
    showToast('课程发布成功！学生现在可以选择此课程', 'success')
    course.status = 'published'
    await loadCourses()
  } catch (error) {
    showToast(error.message || '发布失败，请重试', 'error')
  } finally {
    isPublishing.value = false
    publishingId.value = null
  }
}

async function unpublishCourse(course) {
  if (!confirm('确定要取消发布吗？已选课的学生将无法继续学习。')) return

  isPublishing.value = true
  publishingId.value = course.id

  try {
    await request({ url: `/document/course/${course.id}/unpublish`, method: 'post' })
    showToast('已取消发布', 'success')
    course.status = 'draft'
  } catch (error) {
    showToast(error.message || '操作失败，请重试', 'error')
  } finally {
    isPublishing.value = false
    publishingId.value = null
  }
}

async function deleteCourse(course) {
  const studentCount = course.student_count || 0

  let confirmMsg = `确定要删除课程《${course.title}》吗？`
  if (studentCount > 0) {
    confirmMsg += `\n\n⚠️ 该课程已有 ${studentCount} 名学生选课，删除后学生将无法继续学习。此操作不可恢复！`
  } else {
    confirmMsg += '\n\n此操作不可恢复！'
  }

  if (!confirm(confirmMsg)) return

  isDeleting.value = true
  deletingId.value = course.id

  try {
    await request({ url: `/document/course/${course.id}`, method: 'delete' })
    showToast('课程已成功删除', 'success')
    courses.value = courses.value.filter(c => c.id !== course.id)
    if (selectedCourse.value?.id === course.id) {
      closeStudentPanel()
    }
  } catch (error) {
    showToast(error.message || '删除失败，请重试', 'error')
  } finally {
    isDeleting.value = false
    deletingId.value = null
  }
}

async function loadStudentsAndStats(courseId) {
  isLoadingStudents.value = true

  try {
    const statsData = await request({ url: `/document/course/${courseId}/stats`, method: 'get' })
    courseStats.value = {
      totalStudents: statsData.total_students || 0,
      avgProgress: statsData.avg_progress || 0,
      avgUnderstanding: statsData.avg_understanding || 0,
      avgStudyHoursPerStudent: statsData.avg_study_hours_per_student || 0,
      progressDistribution: statsData.progress_distribution || {},
    }
    nodeProgressData.value = statsData.node_progress || []
  } catch (error) {
    courseStats.value = { totalStudents: 0, avgProgress: 0, avgUnderstanding: 0, avgStudyHoursPerStudent: 0, progressDistribution: {} }
    nodeProgressData.value = []
  }

  try {
    const data = await request({ url: `/document/course/${courseId}/students`, method: 'get' })
    if (data.students) {
      students.value = data.students.map(s => ({
        enrollmentId: s.enrollment_id,
        username: s.username || `学生${s.student_id}`,
        progress: s.overall_progress || 0,
        level: s.understanding_level || 'unknown',
        understandingScore: s.avg_understanding_score || 0,
        studyMinutes: s.total_study_minutes || 0,
      }))
    } else {
      students.value = []
    }
  } catch (studentError) {
    students.value = []
  } finally {
    isLoadingStudents.value = false
  }
}

onMounted(() => {
  loadCourses()
  loadStats()
})

async function loadStats() {
  try {
    const res = await api.user.getUserStats()
    if (res) {
      stats.value = {
        courseCount: res.courseCount || 0,
        studentCount: res.studentCount || 0,
      }
    }
  } catch (error) {
  }
}
</script>

<style scoped>
.teacher-history {
  min-height: calc(100vh - var(--navbar-height));
  background: #f5f7fa;
}

.history-container {
  max-width: 1400px;
  margin: 0 auto;
  padding: 24px;
}

.page-header {
  margin-bottom: 32px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 16px;
}

.page-header h1 {
  font-size: 32px;
  color: #111827;
  margin: 0;
  flex: 1;
  min-width: 200px;
}

.subtitle {
  font-size: 16px;
  color: #6b7280;
  width: 100%;
  margin: 0;
}

.create-new-btn {
  padding: 10px 24px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: white;
  text-decoration: none;
  border-radius: 8px;
  font-weight: 500;
  transition: all 0.3s ease;
}

.create-new-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4);
}

/* 页面级统计概览 */
.page-stats-overview {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.page-stat-card {
  background: white;
  border-radius: 12px;
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  transition: transform 0.2s ease;
}

.page-stat-card:hover {
  transform: translateY(-2px);
}

.page-stat-icon {
  font-size: 32px;
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  background: #f3f4f6;
}

.page-stat-info { flex: 1; }

.page-stat-number {
  font-size: 28px;
  font-weight: 700;
  color: #6366f1;
  line-height: 1.2;
}

.page-stat-label {
  font-size: 13px;
  color: #6b7280;
  margin-top: 2px;
}

/* 课程网格 */
.courses-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
  gap: 24px;
  margin-bottom: 32px;
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
  border: 2px solid transparent;
}

.course-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
}

.course-card.selected {
  border-color: #6366f1;
  box-shadow: 0 4px 16px rgba(99, 102, 241, 0.2);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.course-icon { font-size: 28px; }

.status-badge {
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
}

.status-badge.published { background: #d1fae5; color: #065f46; }
.status-badge.draft { background: #fef3c7; color: #92400e; }
.status-badge.archived { background: #f3f4f6; color: #6b7280; }

.create-time {
  font-size: 12px;
  color: #9ca3af;
}

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
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.course-meta {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  font-size: 13px;
  color: #9ca3af;
}

.quick-stats {
  display: flex;
  gap: 16px;
  padding: 12px;
  background: #f9fafb;
  border-radius: 8px;
}

.quick-stat-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.quick-stat-label {
  font-size: 11px;
  color: #6b7280;
}

.quick-stat-value {
  font-size: 16px;
  font-weight: 700;
  color: #6366f1;
}

.card-footer {
  display: flex;
  gap: 12px;
  margin-top: auto;
}

.action-btn {
  flex: 1;
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  border: none;
}

.view-btn { background: #f3f4f6; color: #374151; }
.view-btn:hover { background: #e5e7eb; }

.students-btn {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: white;
}

.students-btn:hover {
  transform: scale(1.02);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4);
}

.publish-btn {
  background: linear-gradient(135deg, #10b981, #059669);
  color: white;
}

.publish-btn:hover:not(:disabled) {
  transform: scale(1.02);
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.4);
}

.publish-btn:disabled { opacity: 0.6; cursor: not-allowed; }

.unpublish-btn {
  background: linear-gradient(135deg, #f59e0b, #d97706);
  color: white;
}

.unpublish-btn:hover:not(:disabled) {
  transform: scale(1.02);
  box-shadow: 0 4px 12px rgba(245, 158, 11, 0.4);
}

.unpublish-btn:disabled { opacity: 0.6; cursor: not-allowed; }

.delete-btn {
  background: linear-gradient(135deg, #ef4444, #dc2626);
  color: white;
}

.delete-btn:hover:not(:disabled) {
  transform: scale(1.02);
  box-shadow: 0 4px 12px rgba(239, 68, 68, 0.4);
}

.delete-btn:disabled { opacity: 0.6; cursor: not-allowed; }

/* 加载和空状态 */
.loading-state, .empty-state {
  text-align: center;
  padding: 80px 20px;
  color: #6b7280;
}

.spinner {
  width: 48px;
  height: 48px;
  border: 4px solid #e5e7eb;
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 16px;
}

.spinner.small {
  width: 32px;
  height: 32px;
  border-width: 3px;
}

@keyframes spin { to { transform: rotate(360deg); } }

.empty-icon { font-size: 64px; margin-bottom: 16px; }

.start-create-btn {
  display: inline-block;
  margin-top: 16px;
  padding: 12px 28px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: white;
  text-decoration: none;
  border-radius: 8px;
  font-weight: 500;
  transition: all 0.3s ease;
}

.start-create-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4);
}

/* 学生面板 */
.student-panel {
  position: fixed;
  top: 0;
  right: 0;
  width: 70%;
  max-width: 900px;
  height: 100vh;
  background: white;
  box-shadow: -4px 0 24px rgba(0, 0, 0, 0.15);
  z-index: 1000;
  overflow-y: auto;
  animation: slideIn 0.3s ease;
}

@keyframes slideIn {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}

.panel-header {
  position: sticky;
  top: 0;
  background: white;
  padding: 20px 24px;
  border-bottom: 1px solid #e5e7eb;
  display: flex;
  justify-content: space-between;
  align-items: center;
  z-index: 10;
}

.panel-header h3 {
  margin: 0;
  font-size: 18px;
  color: #111827;
  flex: 1;
}

.close-btn {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: none;
  background: #f3f4f6;
  cursor: pointer;
  font-size: 16px;
  transition: all 0.2s ease;
}

.close-btn:hover { background: #fee2e2; color: #dc2626; }

.students-content {
  padding: 24px;
}

/* 面板内统计卡片 */
.panel-stats-overview {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.panel-stat-card {
  text-align: center;
  padding: 16px;
  background: #f9fafb;
  border-radius: 8px;
}

.panel-stat-number {
  font-size: 28px;
  font-weight: 700;
  color: #6366f1;
}

.panel-stat-label {
  font-size: 13px;
  color: #6b7280;
  margin-top: 4px;
}

/* 进度分布 */
.progress-distribution {
  margin-bottom: 24px;
}

.progress-distribution h4 {
  font-size: 16px;
  color: #374151;
  margin: 0 0 12px 0;
}

.chart-row {
  display: flex;
  gap: 24px;
  align-items: center;
  padding: 16px;
  background: #f9fafb;
  border-radius: 8px;
}

.pie-chart-container {
  width: 220px;
  flex-shrink: 0;
}

.dist-list {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dist-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}

.dist-color-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.dot-not_started { background: #d1d5db; }
.dot-beginner { background: #93c5fd; }
.dot-intermediate { background: #a78bfa; }
.dot-advanced { background: #86efac; }
.dot-completed { background: #34d399; }

.dist-label {
  width: 48px;
  color: #4b5563;
  font-weight: 500;
  flex-shrink: 0;
}

.dist-bar-bg {
  flex: 1;
  height: 10px;
  background: #e5e7eb;
  border-radius: 5px;
  overflow: hidden;
}

.dist-bar-fill {
  height: 100%;
  border-radius: 5px;
  transition: width 0.5s ease;
}

.dist-not_started { background: #d1d5db; }
.dist-beginner { background: #93c5fd; }
.dist-intermediate { background: #a78bfa; }
.dist-advanced { background: #86efac; }
.dist-completed { background: #34d399; }

.dist-count {
  width: 48px;
  text-align: right;
  color: #6b7280;
  font-weight: 500;
}

/* 节点进度区域 */
.node-progress-section {
  margin-bottom: 24px;
}

.node-progress-section h4 {
  font-size: 16px;
  color: #374151;
  margin: 0 0 12px 0;
}

.node-chart-container {
  width: 280px;
  margin: 0 auto 16px;
}

.node-progress-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 16px;
  background: #f9fafb;
  border-radius: 8px;
  max-height: 400px;
  overflow-y: auto;
}

.node-progress-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.node-info-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.node-type-icon { font-size: 13px; flex-shrink: 0; }

.node-title-text {
  font-size: 13px;
  color: #374151;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.key-point-badge {
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 600;
  background: #fef3c7;
  color: #92400e;
  flex-shrink: 0;
}

.node-progress-bar-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.node-progress-bar-bg {
  flex: 1;
  height: 6px;
  background: #e5e7eb;
  border-radius: 3px;
  overflow: hidden;
}

.node-progress-bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s ease;
}

.node-high { background: #10b981; }
.node-medium { background: #f59e0b; }
.node-low { background: #ef4444; }
.node-none { background: #d1d5db; }

.node-progress-text {
  font-size: 11px;
  color: #6b7280;
  font-weight: 500;
  width: 36px;
  text-align: right;
}

.node-completed-count {
  font-size: 11px;
  color: #9ca3af;
  width: 44px;
  text-align: right;
}

/* 学生列表 */
.students-list h4 {
  font-size: 16px;
  color: #374151;
  margin: 0 0 12px 0;
}

.list-header-row {
  display: grid;
  grid-template-columns: 150px 1fr 120px 120px;
  gap: 12px;
  padding: 12px 16px;
  background: #f8fafc;
  font-size: 13px;
  font-weight: 600;
  color: #6b7280;
  border-radius: 8px 8px 0 0;
  border-bottom: 1px solid #e5e7eb;
}

.student-row {
  display: grid;
  grid-template-columns: 150px 1fr 120px 120px;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid #f3f4f6;
  align-items: center;
  transition: background 0.2s ease;
}

.student-row:hover { background: #f9fafb; }

.student-name {
  font-weight: 500;
  color: #111827;
}

.mini-progress-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}

.mini-progress-bar {
  flex: 1;
  height: 8px;
  background: #e5e7eb;
  border-radius: 4px;
  overflow: hidden;
}

.mini-progress-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s ease;
}

.mini-progress-fill.high { background: #10b981; }
.mini-progress-fill.medium { background: #f59e0b; }
.mini-progress-fill.low { background: #ef4444; }

.progress-text {
  font-size: 12px;
  color: #6b7280;
  font-weight: 500;
  width: 40px;
  text-align: right;
}

.understanding-badge {
  padding: 4px 10px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 600;
}

.level-excellent { background: #d1fae5; color: #065f46; }
.level-high { background: #dbeafe; color: #1e40af; }
.level-medium { background: #fef3c7; color: #92400e; }
.level-low { background: #fee2e2; color: #991b1b; }
.level-unknown { background: #f3f4f6; color: #6b7280; }

.no-students {
  text-align: center;
  padding: 40px;
  color: #9ca3af;
  font-size: 14px;
}

.loading-state.small {
  padding: 40px;
}

/* 响应式 */
@media (max-width: 1200px) {
  .student-panel {
    width: 85%;
  }

  .panel-stats-overview {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 768px) {
  .courses-grid {
    grid-template-columns: 1fr;
  }

  .student-panel {
    width: 95%;
  }

  .chart-row {
    flex-direction: column;
  }

  .pie-chart-container {
    width: 180px;
  }

  .list-header-row,
  .student-row {
    grid-template-columns: 1fr;
    gap: 8px;
  }
}
</style>
