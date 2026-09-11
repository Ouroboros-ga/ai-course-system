<script setup>
import { computed, onMounted, ref } from 'vue'
import { listExperimentCourses } from '@/api/labs.js'
import { getOJAnalytics, getOJScoreboard, listOJActivities, listOJProblems } from '@/api/oj.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

/**
 * 学情分析 · OJ 数据看板（PR-11 教师端，家良拍板并入既有学情二级菜单）。
 * **刻意缩范围**（PR-14 缩水版）：只呈现现有数据源可确定计算的三块 ——
 * ① 各活动作业榜（finalized 口径，可重算）；② 题库通过率；③ 活动概览。
 * 热力图 / 知识雷达 / 题目质量反馈需要新数据采集，明确**不做假数据**。
 */
const courses = ref([])
const courseId = ref('')
const state = ref('loading')
const error = ref('')

const activities = ref([])
const problems = ref([])
const selectedActivityId = ref('')
const board = ref(null)
const boardState = ref('idle')
const analytics = ref(null)

const selectedActivity = computed(() =>
  activities.value.find((a) => a.activity_id === selectedActivityId.value) || null
)

async function loadCourses() {
  courses.value = await listExperimentCourses()
  courseId.value = courses.value[0] ? String(courses.value[0].course_id) : ''
}

async function loadActivities() {
  if (!courseId.value) {
    state.value = 'empty'
    return
  }
  state.value = 'loading'
  error.value = ''
  try {
    const [acts, bank] = await Promise.all([
      listOJActivities(courseId.value).catch(() => null),
      listOJProblems(courseId.value, { page_size: 100 }).catch(() => null),
    ])
    activities.value = Array.isArray(acts?.items) ? acts.items : []
    analytics.value = await getOJAnalytics(courseId.value).catch(() => null)
    problems.value = Array.isArray(bank?.items) ? bank.items : []
    if (activities.value.length) {
      selectedActivityId.value = activities.value[0].activity_id
      await loadBoard()
    } else {
      selectedActivityId.value = ''
      board.value = null
    }
    state.value = 'ready'
  } catch (caught) {
    error.value = caught?.message || '学情数据加载失败'
    state.value = 'error'
  }
}

async function loadBoard() {
  if (!selectedActivityId.value) return
  boardState.value = 'loading'
  try {
    board.value = await getOJScoreboard(courseId.value, selectedActivityId.value)
    boardState.value = 'ready'
  } catch (caught) {
    // 榜可能因活动未挂题而 409 —— 如实呈现，不伪造
    board.value = null
    boardState.value = 'error'
    error.value = caught?.message || '作业榜加载失败'
  }
}

function statusLabel(value) {
  return { draft: '草稿', published: '已发布', archived: '已归档' }[value] || value
}

function statusTone(value) {
  return { draft: 'amber', published: 'green', archived: 'ink' }[value] || 'ink'
}

function difficultyLabel(value) {
  return { easy: '简单', medium: '中等', hard: '困难' }[value] || value
}

function formatRate(rate) {
  return rate === null || rate === undefined ? '—' : `${Math.round(rate * 1000) / 10}%`
}

onMounted(async () => {
  try {
    await loadCourses()
    await loadActivities()
  } catch (caught) {
    error.value = caught?.message || '加载失败'
    state.value = 'error'
  }
})
</script>

<template>
  <div class="sfx-page">
    <header class="sfx-page-header">
      <div>
        <h1 class="sfx-t-title1">OJ 数据看板</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">
          作业榜与题库通过率。口径 = 已终结尝试，随时可重算。
        </p>
      </div>
      <SfxButton variant="secondary" size="sm" @click="loadActivities">刷新</SfxButton>
    </header>

    <label v-if="courses.length" class="oj-course-select sfx-t-ui">
      课程
      <select v-model="courseId" class="sfx-select" @change="loadActivities()">
        <option v-for="course in courses" :key="course.course_id" :value="String(course.course_id)">
          {{ course.title }}
        </option>
      </select>
    </label>

    <SfxSkeleton v-if="state === 'loading'" :lines="6" block />
    <SfxError v-else-if="state === 'error'" :description="error" @retry="loadActivities" />
    <SfxEmpty
      v-else-if="state === 'empty' || !activities.length"
      title="还没有活动"
      description="先在活动管理里创建并发布作业/练习，这里才会有学情数据。"
    />

    <template v-else>
      <section class="sfx-panel oj-act-panel">
        <h2 class="oj-section-title">活动</h2>
        <div class="oj-act-row">
          <span
            v-for="a in activities"
            :key="a.activity_id"
            role="button"
            tabindex="0"
            class="oj-act-chip"
            :class="{ 'is-active': selectedActivityId === a.activity_id }"
            @click="selectedActivityId = a.activity_id; loadBoard()"
            @keyup.enter="selectedActivityId = a.activity_id; loadBoard()"
          >
            {{ a.title }}
            <SfxBadge :tone="statusTone(a.status)">{{ statusLabel(a.status) }}</SfxBadge>
          </span>
        </div>
      </section>

      <section v-if="analytics" class="oj-kpis">
        <div class="sfx-panel oj-kpi">
          <span class="sfx-t-caption sfx-t-secondary">学生数</span>
          <strong class="oj-kpi-num">{{ analytics.student_count }}</strong>
        </div>
        <div class="sfx-panel oj-kpi">
          <span class="sfx-t-caption sfx-t-secondary">提交次数</span>
          <strong class="oj-kpi-num">{{ analytics.submission_count }}</strong>
        </div>
        <div class="sfx-panel oj-kpi">
          <span class="sfx-t-caption sfx-t-secondary">终结 / 通过</span>
          <strong class="oj-kpi-num">
            {{ analytics.finalized_total }} / {{ analytics.finalized_passed }}
          </strong>
        </div>
        <div class="sfx-panel oj-kpi">
          <span class="sfx-t-caption sfx-t-secondary">通过率</span>
          <strong class="oj-kpi-num">
            {{ analytics.pass_rate === null ? '—' : formatRate(analytics.pass_rate) }}
          </strong>
        </div>
      </section>

      <section v-if="analytics?.trend?.length" class="sfx-panel oj-trend">
        <h2 class="oj-section-title">提交趋势（近 {{ analytics.trend.length }} 天）</h2>
        <div class="oj-trend-bars">
          <div
            v-for="day in analytics.trend"
            :key="day.date"
            class="oj-trend-col"
            :title="`${day.date}：提交 ${day.submissions} / 通过 ${day.accepted}`"
          >
            <div class="oj-trend-bar-wrap">
              <div
                class="oj-trend-bar"
                :style="{ height: `${Math.min(100, day.submissions * 8)}%` }"
              ></div>
            </div>
            <span class="oj-trend-date">{{ day.date.slice(5) }}</span>
          </div>
        </div>
      </section>

      <div v-if="analytics?.high_frequency_wrong?.length" class="oj-two-col">
        <section class="sfx-panel">
          <h2 class="oj-section-title">高频错题（非通过运行数）</h2>
          <div
            v-for="(item, idx) in analytics.high_frequency_wrong"
            :key="item.experiment_id"
            class="oj-wrong-row sfx-t-ui"
          >
            <span class="oj-wrong-rank">{{ idx + 1 }}</span>
            <span class="oj-wrong-title">{{ item.title }}</span>
            <span class="oj-wrong-count">{{ item.wrong_count }}</span>
          </div>
        </section>
        <section class="sfx-panel">
          <h2 class="oj-section-title">错误类型分布（diagnosis 实录）</h2>
          <div
            v-for="(count, cls) in analytics.error_class_counts"
            :key="cls"
            class="oj-wrong-row sfx-t-ui"
          >
            <span>{{ cls }}</span>
            <span class="oj-wrong-count">{{ count }}</span>
          </div>
          <p v-if="!Object.keys(analytics.error_class_counts).length" class="sfx-t-caption sfx-t-secondary">
            暂无 diagnosis 记录。
          </p>
        </section>
      </div>

      <section
        v-if="analytics?.students_needing_attention?.length"
        class="sfx-panel oj-table-panel"
      >
        <h2 class="oj-section-title">需要关注的学生（零通过或 ≥7 天无终结）</h2>
        <table class="oj-table">
          <thead>
            <tr><th>学生 ID</th><th>终结次数</th><th>通过题数</th><th>距上次终结</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in analytics.students_needing_attention" :key="row.student_id">
              <td class="sfx-t-ui">{{ row.student_id }}</td>
              <td class="sfx-t-ui">{{ row.finalized_count }}</td>
              <td class="sfx-t-ui">{{ row.passed_count }}</td>
              <td class="sfx-t-ui">{{ row.idle_days === null ? '从未终结' : `${row.idle_days} 天` }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <SfxSkeleton v-if="boardState === 'loading'" :lines="5" block />
      <SfxError v-else-if="boardState === 'error'" :description="error" @retry="loadBoard" />
      <SfxEmpty
        v-else-if="!board || !board.rows.length"
        title="该活动还没有已终结的作答"
        description="学生提交并终结后，这里会出现可重算的成绩榜。"
      />
      <section v-else class="sfx-panel oj-table-panel">
        <h2 class="oj-section-title">作业榜 · {{ selectedActivity?.title }}</h2>
        <table class="oj-table">
          <thead>
            <tr>
              <th>学生</th>
              <th v-for="(p, idx) in board.rows[0]?.per_problem || []" :key="idx">题 {{ p.ordinal }}</th>
              <th>总分</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in board.rows" :key="row.student_id">
              <td class="sfx-t-ui">{{ row.student_id }}</td>
              <td v-for="(p, idx) in row.per_problem" :key="idx" class="sfx-t-ui">
                {{ p.score }} / {{ p.max }}
              </td>
              <td class="oj-total sfx-t-ui">{{ row.total }} / {{ row.max_total }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section v-if="problems.length" class="sfx-panel oj-table-panel">
        <h2 class="oj-section-title">题库通过率</h2>
        <table class="oj-table">
          <thead>
            <tr><th>题目</th><th>难度</th><th>提交数</th><th>通过率</th></tr>
          </thead>
          <tbody>
            <tr v-for="item in problems" :key="item.experiment_id">
              <td class="sfx-t-ui">{{ item.title }}</td>
              <td><SfxBadge tone="ink">{{ difficultyLabel(item.difficulty) }}</SfxBadge></td>
              <td class="sfx-t-ui">{{ item.attempt_total }}</td>
              <td class="sfx-t-ui">{{ formatRate(item.pass_rate) }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>
  </div>
</template>

<style scoped>
.oj-course-select { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-4); }
.oj-section-title {
  font-size: var(--ui-sm-size);
  font-weight: var(--ui-md-weight);
  color: var(--text-secondary);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: var(--space-3);
}
.oj-act-panel { margin-bottom: var(--space-5); }
.oj-act-row { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.oj-act-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border-default);
  cursor: pointer;
  user-select: none;
  font-size: var(--ui-md-size);
}
.oj-act-chip:hover { border-color: var(--ink-700); }
.oj-act-chip.is-active { border-color: var(--ink-900); box-shadow: inset 0 -2px 0 var(--ink-900); }
.oj-table-panel { margin-bottom: var(--space-5); overflow-x: auto; }
.oj-table { width: 100%; border-collapse: collapse; }
.oj-table th, .oj-table td { text-align: left; padding: var(--space-3) var(--space-4); border-bottom: 1px solid var(--border-default); white-space: nowrap; }
.oj-table th { color: var(--text-secondary); font-size: var(--ui-sm-size); font-weight: var(--ui-md-weight); }
.oj-total { color: var(--ink-900); font-weight: var(--ui-md-weight); }

/* 基础样式 .sfx-input/.sfx-select 是 width:100%（base.css）——横向行里必须
   显式约束宽度，否则每个控件各占一行（2026-09-11 截图复核发现）。 */
.oj-course-select .sfx-select { width: auto; flex: 0 0 auto; min-width: 150px; }
</style>

<style scoped>
.oj-course-select { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-4); }
.oj-section-title {
  font-size: var(--ui-sm-size);
  font-weight: var(--ui-md-weight);
  color: var(--text-secondary);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: var(--space-3);
}
.oj-kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: var(--space-4); margin-bottom: var(--space-5); }
.oj-kpi { display: flex; flex-direction: column; gap: var(--space-1); }
.oj-kpi-num { font-size: 22px; color: var(--ink-900); }
.oj-trend { margin-bottom: var(--space-5); }
.oj-trend-bars { display: flex; align-items: flex-end; gap: var(--space-1); overflow-x: auto; padding-bottom: var(--space-2); }
.oj-trend-col { display: flex; flex-direction: column; align-items: center; gap: var(--space-1); min-width: 22px; }
.oj-trend-bar-wrap { height: 80px; display: flex; align-items: flex-end; width: 100%; }
.oj-trend-bar { width: 100%; background: var(--ink-900); opacity: 0.8; min-height: 2px; }
.oj-trend-date { font-size: 10px; color: var(--text-secondary); white-space: nowrap; }
.oj-two-col { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-5); margin-bottom: var(--space-5); }
.oj-wrong-row { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-2) 0; border-bottom: 1px solid var(--border-default); }
.oj-wrong-rank { color: var(--text-secondary); width: 16px; }
.oj-wrong-title { flex: 1; }
.oj-wrong-count { color: var(--ink-900); }
.oj-table-panel { margin-bottom: var(--space-5); overflow-x: auto; }
.oj-table { width: 100%; border-collapse: collapse; }
.oj-table th, .oj-table td { text-align: left; padding: var(--space-3) var(--space-4); border-bottom: 1px solid var(--border-default); white-space: nowrap; }
.oj-table th { color: var(--text-secondary); font-size: var(--ui-sm-size); }
@media (max-width: 900px) { .oj-two-col { grid-template-columns: 1fr; } }
</style>
