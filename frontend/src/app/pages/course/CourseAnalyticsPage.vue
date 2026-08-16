<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import { Bar, Doughnut, Pie, Line } from 'vue-chartjs'
import {
  Chart as ChartJS,
  BarController, BarElement, CategoryScale, LinearScale,
  ArcElement, DoughnutController, PieController,
  LineController, LineElement, PointElement, Tooltip, Legend,
} from 'chart.js'
import { getLearningAnalytics, getStudentLearningAnalytics } from '@/api/facade.js'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'

ChartJS.register(
  BarController, BarElement, CategoryScale, LinearScale,
  ArcElement, DoughnutController, PieController,
  LineController, LineElement, PointElement, Tooltip, Legend,
)

const { courseId } = inject('courseContext')
const state = ref('loading')
const error = ref('')
const analytics = ref(null)
const selectedStudent = ref(null)
const studentDetail = ref(null)
const points = computed(() => analytics.value?.knowledge_points || [])
const students = computed(() => analytics.value?.students || [])

// 活力配色仅用于圆形图（饼图/环形图）；柱状/折线沿用页面朴素语义色
const VIVID = {
  notStarted: '#7C8BA5',   // 雾霾蓝 —— 比纯灰多一点蓝调，不显脏
  inProgress: '#E8A23A',   // 暖金琥珀
  completed: '#52B788',    // 薄荷翠绿
  pending: '#F08A4B',      // 珊瑚橙
  mastered: '#7B61FF',     // 紫罗兰
  notMastered: '#E76F51',  // 番茄红
  unknown: '#A0AEC0',      // 冷灰
}
// 柱状图中保持系统语义色
const STATUS_COLORS = {
  notStarted: '#8EA7BE',   // ink-300
  inProgress: '#C68B2C',   // amber-500
  completed: '#5E8C61',    // green-500
}

const kpi = computed(() => {
  const pts = points.value
  const avg = pts.length
    ? pts.reduce((s, p) => s + (Number(p.completion_rate) || 0), 0) / pts.length
    : 0
  const pending = pts.reduce((s, p) => s + (Number(p.pending_recommendation_count) || 0), 0)
  let mastered = 0
  for (const p of pts) mastered += Number(p.mastery_distribution?.['掌握'] || 0)
  return {
    students: analytics.value?.student_count || 0,
    points: pts.length,
    avgCompletion: avg,
    mastered,
    pending,
  }
})

const statusDistribution = computed(() => {
  let notStarted = 0, inProgress = 0, completed = 0, pending = 0, mastered = 0
  for (const p of points.value) {
    notStarted += Number(p.not_started || 0)
    inProgress += Number(p.in_progress || 0)
    completed += Number(p.completed || 0)
    pending += Number(p.pending_recommendation_count || 0)
    mastered += Number(p.mastery_distribution?.['掌握'] || 0)
  }
  return { notStarted, inProgress, completed, pending, mastered }
})

const barChartData = computed(() => ({
  labels: points.value.map(p => p.title),
  datasets: [
    { label: '未开始', data: points.value.map(p => p.not_started), backgroundColor: STATUS_COLORS.notStarted, borderRadius: 6, borderSkipped: 'bottom' },
    { label: '学习中', data: points.value.map(p => p.in_progress), backgroundColor: STATUS_COLORS.inProgress, borderRadius: 6, borderSkipped: 'bottom' },
    { label: '已完成', data: points.value.map(p => p.completed), backgroundColor: STATUS_COLORS.completed, borderRadius: 6, borderSkipped: 'bottom' },
  ],
}))

const barChartOptions = computed(() => ({
  responsive: true,
  maintainAspectRatio: false,
  interaction: { mode: 'index', intersect: false },
  animation: {
    duration: 900,
    easing: 'easeOutQuart',
    delay(ctx) {
      return ctx.dataIndex * 60
    },
  },
  scales: {
    x: {
      grid: { display: false },
      ticks: { color: '#7B8494', font: { size: 12 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 8 },
    },
    y: {
      beginAtZero: true,
      grace: '15%',
      ticks: { precision: 0, color: '#7B8494' },
      grid: { color: '#EDF0F3' },
    },
  },
  plugins: {
    legend: { position: 'bottom', labels: { boxWidth: 12, boxHeight: 12, color: '#4E5969', usePointStyle: true, padding: 16 } },
    tooltip: {
      backgroundColor: 'rgba(23, 32, 51, 0.92)',
      titleColor: '#FFFFFF',
      bodyColor: '#E8EDF2',
      padding: 10,
      borderRadius: 8,
      borderColor: 'rgba(255,255,255,0.1)',
      borderWidth: 1,
    },
  },
  datasets: {
    bar: {
      barPercentage: 0.55,
      categoryPercentage: 0.7,
    },
  },
}))

const masteryDonutData = computed(() => {
  const counts = {}
  for (const p of points.value) {
    for (const [level, c] of Object.entries(p.mastery_distribution || {})) {
      counts[level] = (counts[level] || 0) + Number(c || 0)
    }
  }
  const entries = Object.entries(counts)
  const colorFor = (level) => {
    if (level === '掌握') return VIVID.completed
    if (level === '未掌握') return VIVID.notMastered
    return VIVID.unknown
  }
  return {
    labels: entries.map(([l]) => l),
    datasets: [{
      data: entries.map(([, c]) => c),
      backgroundColor: entries.map(([l]) => colorFor(l)),
      borderWidth: 2,
      borderColor: '#FFFFFF',
    }],
  }
})

const statusPieData = computed(() => {
  const d = statusDistribution.value
  const slices = [
    { label: '未开始', value: d.notStarted, color: VIVID.notStarted },
    { label: '学习中', value: d.inProgress, color: VIVID.inProgress },
    { label: '已完成', value: d.completed, color: VIVID.completed },
    { label: '待干预', value: d.pending, color: VIVID.pending },
    { label: '已掌握', value: d.mastered, color: VIVID.mastered },
  ]
  return {
    labels: slices.map(s => s.label),
    datasets: [{
      data: slices.map(s => s.value),
      backgroundColor: slices.map(s => s.color),
      borderWidth: 2,
      borderColor: '#FFFFFF',
    }],
  }
})

const donutOptions = computed(() => ({
  responsive: true,
  maintainAspectRatio: false,
  cutout: '62%',
  animation: { animateRotate: true, animateScale: true, duration: 900, easing: 'easeOutQuart' },
  plugins: {
    legend: { position: 'bottom', labels: { boxWidth: 12, boxHeight: 12, color: '#4E5969', usePointStyle: true, padding: 12 } },
    tooltip: {
      backgroundColor: 'rgba(23, 32, 51, 0.92)',
      titleColor: '#FFFFFF',
      bodyColor: '#E8EDF2',
      padding: 10,
      borderRadius: 8,
      borderColor: 'rgba(255,255,255,0.1)',
      borderWidth: 1,
    },
  },
}))

const pieOptions = computed(() => ({
  responsive: true,
  maintainAspectRatio: false,
  animation: { animateRotate: true, animateScale: true, duration: 900, easing: 'easeOutQuart' },
  plugins: {
    legend: { position: 'bottom', labels: { boxWidth: 12, boxHeight: 12, color: '#4E5969', usePointStyle: true, padding: 12 } },
    tooltip: {
      backgroundColor: 'rgba(23, 32, 51, 0.92)',
      titleColor: '#FFFFFF',
      bodyColor: '#E8EDF2',
      padding: 10,
      borderRadius: 8,
      borderColor: 'rgba(255,255,255,0.1)',
      borderWidth: 1,
    },
  },
}))

// ---------- 折线趋势 ----------
const RANGE_OPTIONS = [
  { days: 7, label: '近 7 天' },
  { days: 14, label: '近 14 天' },
  { days: 30, label: '近 30 天' },
]
const TREND_TABS = [
  { key: 'mastery', label: '掌握度趋势', color: '#5E8C61', isPct: true },
  { key: 'activity', label: '活跃度趋势', color: '#355C7D', isPct: false },
  { key: 'questioning', label: '答题/提问趋势', color: '#C68B2C', isPct: false },
]
const trendDays = ref(7)
const activeTrend = ref('mastery')
const trendLoading = ref(false)
const trendData = computed(() => analytics.value?.trend || { dates: [], mastery: [], activity: [], questioning: [] })
const activeTab = computed(() => TREND_TABS.find(t => t.key === activeTrend.value) || TREND_TABS[0])

const trendChartData = computed(() => {
  const tab = activeTab.value
  const series = trendData.value[tab.key] || []
  return {
    labels: trendData.value.dates || [],
    datasets: [{
      label: tab.label,
      data: series,
      borderColor: tab.color,
      backgroundColor: tab.color + '1F',
      fill: true,
      tension: 0.4,
      spanGaps: true,
      borderWidth: 2,
      pointRadius: 3,
      pointBackgroundColor: tab.color,
    }],
  }
})

const trendChartOptions = computed(() => {
  const isPct = activeTab.value.isPct
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    animation: { duration: 900, easing: 'easeOutQuart' },
    scales: {
      x: { grid: { display: false }, ticks: { color: '#7B8494', font: { size: 12 } } },
      y: {
        beginAtZero: true,
        max: isPct ? 1 : undefined,
        ticks: {
          color: '#7B8494',
          callback: (v) => (isPct ? `${Math.round(v * 100)}%` : v),
        },
        grid: { color: '#EDF0F3' },
      },
    },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: 'rgba(23, 32, 51, 0.92)',
        titleColor: '#FFFFFF',
        bodyColor: '#E8EDF2',
        padding: 10,
        borderRadius: 8,
        borderColor: 'rgba(255,255,255,0.1)',
        borderWidth: 1,
        callbacks: {
          label: (ctx) => {
            const v = ctx.parsed.y
            return isPct ? `掌握度 ${Math.round(v * 100)}%` : `${activeTab.value.label.split('趋势')[0]} ${v}`
          },
        },
      },
    },
  }
})

function selectTrendDays(days) {
  if (days === trendDays.value) return
  trendDays.value = days
  loadTrend()
}

async function loadTrend() {
  trendLoading.value = true
  try {
    const response = await getLearningAnalytics(courseId.value, { days: trendDays.value })
    const data = response?.data ?? response
    if (data?.trend) {
      analytics.value = {
        ...analytics.value,
        trend: data.trend,
        core_metrics: data.core_metrics,
      }
    }
  } catch (e) {
    // 切换时间范围失败时保留旧数据，不打断整页
  } finally {
    trendLoading.value = false
  }
}

// ---------- 核心指标 ----------
const coreMetrics = computed(() => analytics.value?.core_metrics || {})
function formatDuration(seconds) {
  const s = Number(seconds) || 0
  if (s < 60) return `${s} 秒`
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (h > 0) return `${h} 小时 ${m} 分`
  return `${m} 分钟`
}
const coreMetricItems = computed(() => {
  const c = coreMetrics.value
  return [
    { label: 'AI 使用率', value: c.ai_success_rate != null ? `${Math.round(c.ai_success_rate * 100)}%` : '—', sub: `共 ${c.ai_calls ?? 0} 次调用` },
    { label: 'AI 平均耗时', value: c.ai_avg_latency_ms != null ? `${c.ai_avg_latency_ms} ms` : '—', sub: '每次回答延迟' },
    { label: '提问次数', value: c.question_count ?? 0, sub: '学生提问深度记录' },
    { label: 'AI 互动', value: c.interaction_count ?? 0, sub: '教学智能体响应' },
    { label: '学习时长', value: formatDuration(c.total_study_seconds), sub: `人均 ${formatDuration(c.avg_study_seconds)}` },
    { label: '答题正确率', value: c.answer_accuracy != null ? `${Math.round(c.answer_accuracy * 100)}%` : '—', sub: `共 ${c.answer_count ?? 0} 题` },
    { label: '活跃学生', value: c.active_students ?? 0, sub: '有学习行为的学生' },
  ]
})

function barPct(value, total) {
  const t = Number(total) || 1
  return `${Math.min(100, (Number(value) || 0) / t * 100)}%`
}

function reasonText(cognition) {
  const codes = Array.isArray(cognition?.reason_codes) ? cognition.reason_codes : []
  return codes.length ? codes.join('、') : '暂无原因码'
}

function evidenceText(cognition) {
  const evidence = Array.isArray(cognition?.evidence) ? cognition.evidence : []
  if (!evidence.length) return '暂无正式证据'
  return evidence.map(item => `${item.evidence_id} / ${item.type}`).join('；')
}

async function load() {
  state.value = 'loading'
  error.value = ''
  try {
    const response = await getLearningAnalytics(courseId.value, { days: trendDays.value })
    analytics.value = response?.data ?? response
    state.value = 'ready'
  } catch (e) {
    // 课程尚未发布时后端返回 RELEASE_NOT_FOUND。这并非加载故障，而是
    // 学习分析按当前发布版本统计、无发布版本可统计；页面内显示未发布
    // 空态而非错误卡片，也不触发全局错误提示。
    if (e?.message === 'RELEASE_NOT_FOUND') {
      state.value = 'unpublished'
      return
    }
    error.value = e?.message || '学习统计加载失败'
    state.value = 'error'
  }
}

async function inspectStudent(studentId) {
  selectedStudent.value = studentId
  const response = await getStudentLearningAnalytics(courseId.value, studentId)
  studentDetail.value = response?.data ?? response
}

onMounted(load)
</script>

<template>
  <div class="sfx-page sfx-analytics-page">
    <SfxSkeleton v-if="state === 'loading'" :lines="5" block />
    <SfxEmpty
      v-else-if="state === 'unpublished'"
      title="课程尚未发布"
      description="学习分析按当前发布版本统计；课程正式发布后，这里将展示知识点学习进度与认知分析。"
    />
    <SfxError v-else-if="state === 'error'" :description="error" @retry="load" />
    <template v-else>
      <header class="sfx-page-head">
        <div>
          <p class="sfx-t-kicker">LEARNING ANALYTICS</p>
          <h1 class="sfx-t-title2">学习进度与认知分析</h1>
          <p class="sfx-t-secondary">按当前发布版本统计知识点学习状态；掌握度评定基于已确认的学习记录。</p>
        </div>
      </header>

      <section class="sfx-kpi-grid">
        <div class="sfx-kpi-card">
          <span class="sfx-kpi-label">学生数</span>
          <strong class="sfx-kpi-value">{{ kpi.students }}</strong>
          <span class="sfx-kpi-caption">课程学习者</span>
        </div>
        <div class="sfx-kpi-card">
          <span class="sfx-kpi-label">知识点</span>
          <strong class="sfx-kpi-value">{{ kpi.points }}</strong>
          <span class="sfx-kpi-caption">当前发布版本</span>
        </div>
        <div class="sfx-kpi-card">
          <span class="sfx-kpi-label">平均完成率</span>
          <strong class="sfx-kpi-value">{{ Math.round(kpi.avgCompletion * 100) }}%</strong>
          <span class="sfx-kpi-caption">全部知识点</span>
        </div>
        <div class="sfx-kpi-card">
          <span class="sfx-kpi-label">已掌握</span>
          <strong class="sfx-kpi-value">{{ kpi.mastered }}</strong>
          <span class="sfx-kpi-caption">基于已确认证据</span>
        </div>
        <div class="sfx-kpi-card sfx-kpi-card--warn">
          <span class="sfx-kpi-label">待干预</span>
          <strong class="sfx-kpi-value">{{ kpi.pending }}</strong>
          <span class="sfx-kpi-caption">需教师关注</span>
        </div>
      </section>

      <template v-if="points.length">
        <section class="sfx-chart-grid">
          <div class="sfx-panel sfx-chart-panel">
            <h2 class="sfx-panel-title">知识点完成情况</h2>
            <p class="sfx-t-caption sfx-t-muted">各知识点的学生进度构成（未开始 / 学习中 / 已完成）</p>
            <div class="sfx-chart-box">
              <Bar :data="barChartData" :options="barChartOptions" />
            </div>
          </div>
          <div class="sfx-panel sfx-chart-panel">
            <h2 class="sfx-panel-title">课程状态全景</h2>
            <p class="sfx-t-caption sfx-t-muted">进度（未开始/学习中/已完成）+ 预警（待干预）+ 掌握（已掌握）</p>
            <div class="sfx-chart-box">
              <Pie :data="statusPieData" :options="pieOptions" />
            </div>
          </div>
        </section>

        <section class="sfx-chart-grid sfx-trend-grid">
          <div class="sfx-panel sfx-chart-panel">
            <div class="sfx-trend-head">
              <div>
                <h2 class="sfx-panel-title">学习趋势</h2>
                <p class="sfx-t-caption sfx-t-muted">切换图表查看不同维度的近期趋势</p>
              </div>
              <div class="sfx-trend-actions">
                <span v-if="trendLoading" class="sfx-trend-loading"><i class="sfx-trend-dot" />加载中</span>
                <div class="sfx-range-group">
                  <button
                    v-for="opt in RANGE_OPTIONS"
                    :key="opt.days"
                    type="button"
                    class="sfx-range-btn"
                    :class="{ 'sfx-range-btn--active': trendDays === opt.days }"
                    @click="selectTrendDays(opt.days)"
                  >{{ opt.label }}</button>
                </div>
              </div>
            </div>
            <div class="sfx-trend-tabs">
              <button
                v-for="tab in TREND_TABS"
                :key="tab.key"
                type="button"
                class="sfx-trend-tab"
                :class="{ 'sfx-trend-tab--active': activeTrend === tab.key }"
                @click="activeTrend = tab.key"
              >{{ tab.label }}</button>
            </div>
            <div class="sfx-chart-box">
              <Line :data="trendChartData" :options="trendChartOptions" />
            </div>
          </div>
          <div class="sfx-panel sfx-chart-panel">
            <h2 class="sfx-panel-title">核心指标</h2>
            <p class="sfx-t-caption sfx-t-muted">课程累计的系统级数据</p>
            <div class="sfx-metrics-grid">
              <div v-for="item in coreMetricItems" :key="item.label" class="sfx-metric-card">
                <span class="sfx-metric-label">{{ item.label }}</span>
                <strong class="sfx-metric-value">{{ item.value }}</strong>
                <span class="sfx-metric-sub">{{ item.sub }}</span>
              </div>
            </div>
          </div>
        </section>

        <section class="sfx-chart-grid">
          <div class="sfx-panel sfx-chart-panel">
            <h2 class="sfx-panel-title">掌握等级分布</h2>
            <p class="sfx-t-caption sfx-t-muted">按已确认认知证据汇总的各掌握等级学生人次</p>
            <div v-if="masteryDonutData.labels.length" class="sfx-chart-box sfx-chart-box--sm">
              <Doughnut :data="masteryDonutData" :options="donutOptions" />
            </div>
            <div v-else class="sfx-mastery-empty">
              <SfxEmpty title="暂无正式认知证据" description="学生开始学习并产生确认记录后，将在此生成掌握等级分析。" />
            </div>
          </div>
          <div class="sfx-panel sfx-chart-panel sfx-detail-panel">
            <h2 class="sfx-panel-title">知识点完成情况明细</h2>
            <div class="sfx-detail-list">
              <div v-for="point in points" :key="point.outline_node_id" class="sfx-detail-row">
                <div class="sfx-detail-name" :title="point.title">{{ point.title }}</div>
                <div class="sfx-detail-bar">
                  <div class="sfx-detail-bar-track">
                    <span class="sfx-bar-seg sfx-bar-seg--done" :style="{ width: barPct(point.completed, point.total_students) }" />
                    <span class="sfx-bar-seg sfx-bar-seg--prog" :style="{ width: barPct(point.in_progress, point.total_students) }" />
                  </div>
                  <span class="sfx-detail-pct">{{ Math.round(point.completion_rate * 100) }}%</span>
                </div>
                <div class="sfx-detail-meta">
                  <span class="sfx-tag sfx-tag--muted">{{ point.unknown_mastery_count }} 未知</span>
                  <span class="sfx-tag sfx-tag--amber" v-if="point.low_confidence_count > 0">{{ point.low_confidence_count }} 低置信</span>
                  <span class="sfx-tag sfx-tag--warn" v-if="point.pending_recommendation_count > 0">{{ point.pending_recommendation_count }} 待干预</span>
                </div>
              </div>
            </div>
          </div>
        </section>
      </template>
      <div v-else class="sfx-panel">
        <SfxEmpty title="暂无知识点数据" description="当前发布版本没有可统计的知识点。" />
      </div>

      <section class="sfx-panel">
        <h2 class="sfx-panel-title">学生下钻</h2>
        <div class="sfx-analytics-students">
          <div v-for="student in students" :key="student.student_id" class="sfx-analytics-student-row">
            <span>学生 {{ student.student_id }}</span>
            <span>{{ student.completed }} / {{ student.total }} 已完成</span>
            <span>{{ Math.round(student.completion_rate * 100) }}%</span>
            <SfxButton size="sm" variant="secondary" @click="inspectStudent(student.student_id)">查看矩阵</SfxButton>
          </div>
          <p v-if="!students.length" class="sfx-t-secondary">当前发布版本没有可统计的学生。</p>
        </div>
      </section>

      <section v-if="studentDetail" class="sfx-panel">
        <h2 class="sfx-panel-title">学生 {{ selectedStudent }} 学习明细</h2>
        <div v-for="item in studentDetail.items" :key="item.outline_node_id" class="sfx-analytics-student-detail">
          <div><strong>{{ item.title }}</strong><span>{{ item.learning.status }} · {{ Math.round(item.learning.completion_ratio * 100) }}%</span></div>
          <div><span>认知：{{ item.cognition.mastery_level || item.cognition.status }}</span><span>置信度：{{ item.cognition.evidence_confidence ?? '—' }}</span></div>
          <div class="sfx-t-caption">原因：{{ reasonText(item.cognition) }}</div>
          <div class="sfx-t-caption">证据：{{ evidenceText(item.cognition) }}</div>
          <div class="sfx-t-caption">推荐：{{ item.recommendation?.status || 'not_available' }}{{ item.recommendation?.title ? ` · ${item.recommendation.title}` : '' }}</div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.sfx-kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: var(--space-6);
  margin-bottom: var(--space-6);
}
.sfx-kpi-card {
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.sfx-kpi-label { font-size: var(--ui-sm-size); color: var(--text-secondary); font-weight: 500; }
.sfx-kpi-value { font-size: 30px; line-height: 1.1; color: var(--text-primary); font-weight: 700; }
.sfx-kpi-caption { font-size: var(--ui-sm-size); color: var(--text-muted); }
.sfx-kpi-card--warn .sfx-kpi-value { color: var(--amber-700); }

.sfx-chart-grid {
  display: grid;
  grid-template-columns: 1.6fr 1fr;
  gap: var(--space-6);
  margin-bottom: var(--space-6);
  align-items: stretch;
}
.sfx-chart-panel {
  display: flex;
  flex-direction: column;
  /* 覆盖 base.css 的 .sfx-panel + .sfx-panel { margin-top }，
     避免 grid 两列中右侧面板被 margin 下推导致顶部不对齐 */
  margin-top: 0 !important;
}
.sfx-chart-panel h2 { margin-bottom: 2px; }
.sfx-chart-box { height: 300px; margin-top: 16px; position: relative; }
.sfx-chart-box--sm { height: 240px; }
.sfx-chart-empty { display: flex; align-items: center; justify-content: center; height: 300px; }
.sfx-mastery-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 16px;
  min-height: 240px;
}

/* ── 知识点明细列表（替代旧表格） ── */
.sfx-detail-panel { padding-bottom: 20px; }
.sfx-detail-list {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 16px;
  overflow-y: auto;
  min-height: 0;
}
.sfx-detail-row {
  display: grid;
  grid-template-columns: minmax(120px, 1.4fr) 2fr auto;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  background: var(--surface-cool);
  border-radius: var(--radius-lg);
}
.sfx-detail-name {
  font-size: var(--ui-sm-size);
  color: var(--text-primary);
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sfx-detail-bar {
  display: flex;
  align-items: center;
  gap: 8px;
}
.sfx-detail-bar-track {
  flex: 1;
  height: 8px;
  background: var(--border-subtle);
  border-radius: 999px;
  overflow: hidden;
  display: flex;
}
.sfx-bar-seg {
  height: 100%;
  transition: width .6s ease;
}
.sfx-bar-seg--done { background: var(--green-500); }
.sfx-bar-seg--prog { background: var(--amber-500); }
.sfx-detail-pct {
  font-size: var(--ui-sm-size);
  color: var(--text-secondary);
  font-weight: 600;
  min-width: 36px;
  text-align: right;
}
.sfx-detail-meta {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.sfx-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  white-space: nowrap;
}
.sfx-tag--muted { background: var(--surface-soft); color: var(--text-muted); }
.sfx-tag--amber { background: var(--amber-100); color: var(--amber-700); }
.sfx-tag--warn { background: var(--red-100); color: var(--red-700); }

.sfx-trend-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-4);
  flex-wrap: wrap;
}
.sfx-trend-actions {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}
.sfx-trend-loading {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--ui-sm-size);
  color: var(--text-muted);
}
.sfx-trend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-brand);
  animation: sfx-trend-pulse 1s ease-in-out infinite;
}
@keyframes sfx-trend-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.35; transform: scale(0.7); }
}
.sfx-range-group {
  display: inline-flex;
  gap: 2px;
  padding: 3px;
  background: var(--surface-cool);
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
}
.sfx-range-btn {
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--ui-sm-size);
  padding: 5px 12px;
  border-radius: 999px;
  cursor: pointer;
  transition: background .15s ease, color .15s ease;
}
.sfx-range-btn:hover { color: var(--text-primary); }
.sfx-range-btn--active {
  background: var(--surface-panel);
  color: var(--color-brand);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(16, 26, 49, 0.12);
}
.sfx-trend-tabs {
  display: flex;
  gap: 4px;
  margin-top: 14px;
  border-bottom: 1px solid var(--border-subtle);
}
.sfx-trend-tab {
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: var(--ui-sm-size);
  padding: 8px 14px;
  margin-bottom: -1px;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: color .15s ease, border-color .15s ease;
}
.sfx-trend-tab:hover { color: var(--text-primary); }
.sfx-trend-tab--active {
  color: var(--color-brand);
  font-weight: 600;
  border-bottom-color: var(--color-brand);
}

.sfx-metrics-grid {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 1fr;
  align-content: center;
  gap: 12px;
  margin-top: 16px;
  min-height: 0;
}
.sfx-metric-card {
  border: 1px solid var(--border-subtle);
  background: var(--surface-cool);
  border-radius: var(--radius-lg);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
}
.sfx-metric-label { font-size: var(--ui-sm-size); color: var(--text-secondary); font-weight: 500; }
.sfx-metric-value { font-size: 22px; line-height: 1.15; color: var(--text-primary); font-weight: 700; }
.sfx-metric-sub { font-size: var(--ui-sm-size); color: var(--text-muted); }

/* ── 平板及以下：图表行堆叠，避免左右挤压 ── */
@media (max-width: 1080px) {
  .sfx-chart-grid { grid-template-columns: 1fr; }
  .sfx-metrics-grid { grid-template-columns: 1fr 1fr; }
}

/* ── 手机端：进一步压缩边距/图表高度，指标单列，明细行紧凑 ── */
@media (max-width: 640px) {
  .sfx-kpi-grid { grid-template-columns: repeat(2, 1fr); }
  .sfx-chart-box { height: 260px; }
  .sfx-chart-box--sm { height: 220px; }
  .sfx-chart-empty { height: 260px; }
  .sfx-metrics-grid { grid-template-columns: 1fr; }
  .sfx-trend-head { flex-direction: column; align-items: stretch; }
  .sfx-range-group { align-self: flex-start; }
  .sfx-trend-tabs { overflow-x: auto; }
  .sfx-analytics-student-row { grid-template-columns: 1fr 1fr; gap: 6px; }
  .sfx-detail-row { grid-template-columns: 1fr; gap: 6px; }
  .sfx-detail-meta { justify-content: flex-start; }
}

.sfx-analytics-student-row {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr 1fr;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid var(--border-subtle);
  color: var(--text-secondary);
}
.sfx-analytics-student-detail {
  display: grid;
  gap: 4px;
  padding: 12px 0;
  border-bottom: 1px solid var(--border-subtle);
  color: var(--text-secondary);
}
.sfx-analytics-student-detail > div {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.sfx-analytics-student-detail strong { color: var(--text-primary); min-width: 220px; }
</style>