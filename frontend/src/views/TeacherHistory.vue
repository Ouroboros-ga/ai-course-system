<template>
  <div class="teacher-history">
    <div class="history-container">
      <div class="page-header">
        <h1><BookOpen class="header-icon" :size="28" /> 课程管理</h1>
        <p class="subtitle">查看和管理您创建的所有课程以及学生学习状态</p>
        <router-link to="/teacher/create" class="create-new-btn">
          <Plus :size="16" /> 创建新课程
        </router-link>
      </div>

      <!-- 统计概览 -->
      <div class="page-stats-overview">
        <div class="page-stat-card">
          <div class="page-stat-icon"><BookOpen :size="28" /></div>
          <div class="page-stat-info">
            <div class="page-stat-number">{{ stats.courseCount }}</div>
            <div class="page-stat-label">智课数量</div>
          </div>
        </div>
        <div class="page-stat-card">
          <div class="page-stat-icon"><Users :size="28" /></div>
          <div class="page-stat-info">
            <div class="page-stat-number">{{ stats.studentCount }}</div>
            <div class="page-stat-label">学生人数</div>
          </div>
        </div>
        <div class="page-stat-card">
          <div class="page-stat-icon"><Megaphone :size="28" /></div>
          <div class="page-stat-info">
            <div class="page-stat-number">{{ publishedCount }}</div>
            <div class="page-stat-label">已发布课程</div>
          </div>
        </div>
      </div>

      <!-- 课程列表 -->
      <div class="courses-section">
        <LoadingSpinner v-if="isLoading" text="正在加载课程..." />

        <div v-else-if="courses.length === 0" class="empty-state">
          <BookOpen class="empty-icon" :size="64" />
          <h3>暂无历史课程</h3>
          <p>您还没有创建任何课程，点击上方按钮开始创建您的第一门智课</p>
          <router-link to="/teacher/create" class="start-create-btn">
            开始创建 <ArrowRight :size="16" />
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
              <span class="course-icon"><Ruler :size="24" /></span>
              <span class="status-badge" :class="course.status">
                {{ getStatusLabel(course.status) }}
              </span>
              <span class="create-time">{{ formatTime(course.created_at) }}</span>
            </div>

            <div class="card-body">
              <h3 class="course-title">{{ course.title }}</h3>
              <p class="course-desc">{{ course.description || '暂无描述' }}</p>

              <div class="course-meta">
                <span class="meta-item"><BarChart3 :size="14" /> {{ course.total_nodes || 0 }} 个知识点</span>
                <span class="meta-item"><Clock :size="14" /> {{ formatDuration(course.total_duration) }}</span>
                <span class="meta-item"><Users :size="14" /> {{ course.student_count || 0 }} 名学生</span>
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
                <Users :size="14" /> 学生状态 ({{ course.student_count || 0 }})
              </button>
              <button
                v-if="course.status === 'draft'"
                class="action-btn publish-btn"
                @click.stop="publishCourse(course)"
                :disabled="isPublishing"
              >
                {{ isPublishing && publishingId === course.id ? '发布中...' : '发布课程' }}
              </button>
              <button
                v-else-if="course.status === 'published'"
                class="action-btn unpublish-btn"
                @click.stop="unpublishCourse(course)"
                :disabled="isPublishing"
              >
                {{ isPublishing && publishingId === course.id ? '处理中...' : '已发布' }}
              </button>
              <button
                class="action-btn delete-btn"
                @click.stop="deleteCourse(course)"
                :disabled="isDeleting && deletingId === course.id"
              >
                {{ isDeleting && deletingId === course.id ? '删除中...' : '删除' }}
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 学生详情面板 -->
      <div v-if="selectedCourse && showStudentPanel" class="student-panel">
        <div class="panel-header">
          <h3><Users :size="20" /> 《{{ selectedCourse.title }}》- 学生学习状态</h3>
          <button class="close-btn" @click="closeStudentPanel"><X :size="16" /></button>
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
            <h4><BarChart3 :size="18" /> 学习进度分布</h4>
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
            <h4><BookOpen :size="18" /> 各知识点完成率</h4>
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
                  <component :is="getNodeTypeIcon(node.node_type)" class="node-type-icon" :size="13" />
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
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
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
import {
  BookOpen, Users, Megaphone, Plus, ArrowRight, Ruler,
  BarChart3, Clock, X, HelpCircle, ClipboardList,
  Bookmark, Video, MessageCircle, FileText,
} from 'lucide-vue-next'

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
  not_started: '#cbd5e1',
  beginner: '#93c5fd',
  intermediate: '#8b5cf6',
  advanced: '#86efac',
  completed: '#10b981',
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
        backgroundColor: '#10b981',
        borderWidth: 1,
        borderColor: '#ffffff',
      },
      {
        label: '未完成',
        data: remainingCounts,
        backgroundColor: '#e2e8f0',
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
    lecture: BookOpen,
    question: HelpCircle,
    breakpoint: Bookmark,
    summary: ClipboardList,
    video: Video,
    interactive: MessageCircle,
  }
  return icons[type] || FileText
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
  background: var(--color-bg);
}

.history-container {
  max-width: 1400px;
  margin: 0 auto;
  padding: var(--space-6);
}

.page-header {
  margin-bottom: var(--space-8);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-4);
}

.page-header h1 {
  font-size: var(--text-3xl);
  color: var(--color-text);
  margin: 0;
  flex: 1;
  min-width: 200px;
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.header-icon {
  color: var(--color-primary);
}

.subtitle {
  font-size: var(--text-base);
  color: var(--color-text-secondary);
  width: 100%;
  margin: 0;
}

.create-new-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-6);
  background: var(--gradient-primary);
  color: var(--color-primary-foreground);
  text-decoration: none;
  border-radius: var(--radius-md);
  font-weight: var(--font-medium);
  transition: var(--duration-normal) var(--ease);
}

.create-new-btn:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-primary);
}

/* 页面级统计概览 */
.page-stats-overview {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-4);
  margin-bottom: var(--space-6);
}

.page-stat-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-5);
  display: flex;
  align-items: center;
  gap: var(--space-4);
  box-shadow: var(--shadow-sm);
  transition: var(--duration-normal) var(--ease);
}

.page-stat-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}

.page-stat-icon {
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-lg);
  background: var(--color-primary-light);
  color: var(--color-primary);
  flex-shrink: 0;
}

.page-stat-info { flex: 1; }

.page-stat-number {
  font-size: var(--text-2xl);
  font-weight: var(--font-bold);
  color: var(--color-primary);
  line-height: 1.2;
}

.page-stat-label {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  margin-top: var(--space-1);
}

/* 课程网格 */
.courses-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
  gap: var(--space-6);
  margin-bottom: var(--space-8);
}

.course-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-5);
  box-shadow: var(--shadow-sm);
  cursor: pointer;
  transition: var(--duration-normal) var(--ease);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  border-width: 2px;
}

.course-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-lg);
}

.course-card.selected {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-primary);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-2);
}

.course-icon {
  color: var(--color-primary);
  display: flex;
  align-items: center;
}

.status-badge {
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
}

.status-badge.published { background: var(--color-success-light); color: var(--color-success-hover); }
.status-badge.draft { background: var(--color-warning-light); color: var(--color-warning-hover); }
.status-badge.archived { background: var(--color-surface-2); color: var(--color-text-secondary); }

.create-time {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.course-title {
  font-size: var(--text-lg);
  font-weight: var(--font-semibold);
  color: var(--color-text);
  margin: 0;
}

.course-desc {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: var(--leading-normal);
  margin: 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.course-meta {
  display: flex;
  gap: var(--space-4);
  flex-wrap: wrap;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.meta-item {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

.quick-stats {
  display: flex;
  gap: var(--space-4);
  padding: var(--space-3);
  background: var(--color-surface-2);
  border-radius: var(--radius-md);
}

.quick-stat-item {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.quick-stat-label {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
}

.quick-stat-value {
  font-size: var(--text-base);
  font-weight: var(--font-bold);
  color: var(--color-primary);
}

.card-footer {
  display: flex;
  gap: var(--space-3);
  margin-top: auto;
}

.action-btn {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  cursor: pointer;
  transition: var(--duration-normal) var(--ease);
  border: none;
}

.view-btn { background: var(--color-surface-2); color: var(--color-text-secondary); }
.view-btn:hover { background: var(--color-surface-3); }

.students-btn {
  background: var(--gradient-primary);
  color: var(--color-primary-foreground);
}

.students-btn:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-primary);
}

.publish-btn {
  background: var(--gradient-success);
  color: var(--color-primary-foreground);
}

.publish-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: var(--shadow-success);
}

.publish-btn:disabled { opacity: 0.6; cursor: not-allowed; }

.unpublish-btn {
  background: var(--gradient-warning);
  color: var(--color-primary-foreground);
}

.unpublish-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(245, 158, 11, 0.4);
}

.unpublish-btn:disabled { opacity: 0.6; cursor: not-allowed; }

.delete-btn {
  background: var(--gradient-danger);
  color: var(--color-primary-foreground);
}

.delete-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: var(--shadow-danger);
}

.delete-btn:disabled { opacity: 0.6; cursor: not-allowed; }

/* 加载和空状态 */
.loading-state, .empty-state {
  text-align: center;
  padding: var(--space-12) var(--space-5);
  color: var(--color-text-secondary);
}

.empty-icon {
  color: var(--color-text-muted);
  margin-bottom: var(--space-4);
}

.start-create-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-4);
  padding: var(--space-3) var(--space-7);
  background: var(--gradient-primary);
  color: var(--color-primary-foreground);
  text-decoration: none;
  border-radius: var(--radius-md);
  font-weight: var(--font-medium);
  transition: var(--duration-normal) var(--ease);
}

.start-create-btn:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-primary);
}

/* 学生面板 */
.student-panel {
  position: fixed;
  top: 0;
  right: 0;
  width: 70%;
  max-width: 900px;
  height: 100vh;
  background: var(--color-surface);
  box-shadow: var(--shadow-lg);
  z-index: var(--z-modal);
  overflow-y: auto;
  animation: slideIn var(--duration-slow) var(--ease);
}

@keyframes slideIn {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}

.panel-header {
  position: sticky;
  top: 0;
  background: var(--color-surface);
  padding: var(--space-5) var(--space-6);
  border-bottom: 1px solid var(--color-border);
  display: flex;
  justify-content: space-between;
  align-items: center;
  z-index: var(--z-dropdown);
}

.panel-header h3 {
  margin: 0;
  font-size: var(--text-lg);
  color: var(--color-text);
  flex: 1;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.close-btn {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-full);
  border: none;
  background: var(--color-surface-2);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-muted);
  transition: var(--transition-color);
}

.close-btn:hover { background: var(--color-danger-light); color: var(--color-danger-hover); }

.students-content {
  padding: var(--space-6);
}

/* 面板内统计卡片 */
.panel-stats-overview {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-4);
  margin-bottom: var(--space-6);
}

.panel-stat-card {
  text-align: center;
  padding: var(--space-4);
  background: var(--color-surface-2);
  border-radius: var(--radius-md);
}

.panel-stat-number {
  font-size: var(--text-2xl);
  font-weight: var(--font-bold);
  color: var(--color-primary);
}

.panel-stat-label {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  margin-top: var(--space-1);
}

/* 进度分布 */
.progress-distribution {
  margin-bottom: var(--space-6);
}

.progress-distribution h4 {
  font-size: var(--text-base);
  color: var(--color-text-secondary);
  margin: 0 0 var(--space-3) 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.chart-row {
  display: flex;
  gap: var(--space-6);
  align-items: center;
  padding: var(--space-4);
  background: var(--color-surface-2);
  border-radius: var(--radius-md);
}

.pie-chart-container {
  width: 220px;
  flex-shrink: 0;
}

.dist-list {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.dist-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
}

.dist-color-dot {
  width: 10px;
  height: 10px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

.dot-not_started { background: var(--color-border-hover); }
.dot-beginner { background: var(--color-info-light); }
.dot-intermediate { background: var(--color-secondary); }
.dot-advanced { background: var(--color-success-light); }
.dot-completed { background: var(--color-success); }

.dist-label {
  width: 48px;
  color: var(--color-text-secondary);
  font-weight: var(--font-medium);
  flex-shrink: 0;
}

.dist-bar-bg {
  flex: 1;
  height: 10px;
  background: var(--color-border);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.dist-bar-fill {
  height: 100%;
  border-radius: var(--radius-sm);
  transition: width var(--duration-slow) var(--ease);
}

.dist-not_started { background: var(--color-border-hover); }
.dist-beginner { background: var(--color-info-light); }
.dist-intermediate { background: var(--color-secondary); }
.dist-advanced { background: var(--color-success-light); }
.dist-completed { background: var(--color-success); }

.dist-count {
  width: 48px;
  text-align: right;
  color: var(--color-text-secondary);
  font-weight: var(--font-medium);
}

/* 节点进度区域 */
.node-progress-section {
  margin-bottom: var(--space-6);
}

.node-progress-section h4 {
  font-size: var(--text-base);
  color: var(--color-text-secondary);
  margin: 0 0 var(--space-3) 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.node-chart-container {
  width: 280px;
  margin: 0 auto var(--space-4);
}

.node-progress-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-4);
  background: var(--color-surface-2);
  border-radius: var(--radius-md);
  max-height: 400px;
  overflow-y: auto;
}

.node-progress-item {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.node-info-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.node-type-icon { color: var(--color-text-muted); flex-shrink: 0; }

.node-title-text {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  font-weight: var(--font-medium);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.key-point-badge {
  padding: 1px var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  background: var(--color-warning-light);
  color: var(--color-warning-hover);
  flex-shrink: 0;
}

.node-progress-bar-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.node-progress-bar-bg {
  flex: 1;
  height: 6px;
  background: var(--color-border);
  border-radius: var(--radius-full);
  overflow: hidden;
}

.node-progress-bar-fill {
  height: 100%;
  border-radius: var(--radius-full);
  transition: width var(--duration-normal) var(--ease);
}

.node-high { background: var(--color-success); }
.node-medium { background: var(--color-warning); }
.node-low { background: var(--color-danger); }
.node-none { background: var(--color-border-hover); }

.node-progress-text {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  font-weight: var(--font-medium);
  width: 36px;
  text-align: right;
}

.node-completed-count {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  width: 44px;
  text-align: right;
}

/* 学生列表 */
.students-list h4 {
  font-size: var(--text-base);
  color: var(--color-text-secondary);
  margin: 0 0 var(--space-3) 0;
}

.list-header-row {
  display: grid;
  grid-template-columns: 150px 1fr 120px 120px;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--color-bg);
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--color-text-secondary);
  border-radius: var(--radius-md) var(--radius-md) 0 0;
  border-bottom: 1px solid var(--color-border);
}

.student-row {
  display: grid;
  grid-template-columns: 150px 1fr 120px 120px;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-surface-2);
  align-items: center;
  transition: var(--transition-color);
}

.student-row:hover { background: var(--color-surface-2); }

.student-name {
  font-weight: var(--font-medium);
  color: var(--color-text);
}

.mini-progress-wrap {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.mini-progress-bar {
  flex: 1;
  height: 8px;
  background: var(--color-border);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.mini-progress-fill {
  height: 100%;
  border-radius: var(--radius-sm);
  transition: width var(--duration-normal) var(--ease);
}

.mini-progress-fill.high { background: var(--color-success); }
.mini-progress-fill.medium { background: var(--color-warning); }
.mini-progress-fill.low { background: var(--color-danger); }

.progress-text {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  font-weight: var(--font-medium);
  width: 40px;
  text-align: right;
}

.understanding-badge {
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
}

.level-excellent { background: var(--color-success-light); color: var(--color-success-hover); }
.level-high { background: var(--color-info-light); color: var(--color-info); }
.level-medium { background: var(--color-warning-light); color: var(--color-warning-hover); }
.level-low { background: var(--color-danger-light); color: var(--color-danger-hover); }
.level-unknown { background: var(--color-surface-2); color: var(--color-text-secondary); }

.no-students {
  text-align: center;
  padding: var(--space-10);
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.loading-state.small {
  padding: var(--space-10);
}

/* 响应式 */
@media (max-width: 1024px) {
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
    gap: var(--space-2);
  }

  .page-stats-overview {
    grid-template-columns: 1fr;
  }

  .card-footer {
    flex-wrap: wrap;
  }
}
</style>
