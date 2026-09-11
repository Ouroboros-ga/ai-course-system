<script setup>
import { onMounted, ref } from 'vue'
import { listFacadeCourses } from '@/api/facade.js'
import { listOJCourseSubmissions, listOJProblems } from '@/api/oj.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

/**
 * 评测记录（教师，设计稿侧栏「评测记录」）：课程全量提交流水。
 * 与学生 façade 的 /submissions 分端点（教师视图带学生身份，configure 权限）。
 */
const courses = ref([])
const courseId = ref('')
const state = ref('loading')
const error = ref('')
const items = ref([])
const problems = ref([])
const problemFilter = ref('')
const outcomeFilter = ref('')

const outcomeOptions = [
  { value: 'accepted', label: '通过' },
  { value: 'wrong_answer', label: '答案错误' },
  { value: 'runtime_error', label: '运行错误' },
  { value: 'time_limit_exceeded', label: '超时' },
  { value: 'compile_error', label: '编译错误' },
  { value: 'pending', label: '评测中' },
]

function outcomeLabel(value) {
  return {
    accepted: '通过', wrong_answer: '答案错误', runtime_error: '运行错误',
    time_limit_exceeded: '超时', compile_error: '编译错误', pending: '评测中',
    internal_error: '系统错误', cancelled: '已取消',
  }[value] || value
}

function outcomeTone(value) {
  return value === 'accepted' ? 'green' : value === 'pending' ? 'amber' : 'red'
}

async function loadCourses() {
  const building = await listFacadeCourses('building').catch(() => [])
  courses.value = building || []
  courseId.value = courses.value[0] ? String(courses.value[0].course_id) : ''
  if (!courseId.value) state.value = 'empty'
}

async function load() {
  if (!courseId.value) return
  state.value = 'loading'
  error.value = ''
  try {
    const params = { limit: 200 }
    if (problemFilter.value) params.experiment_id = problemFilter.value
    if (outcomeFilter.value) params.outcome = outcomeFilter.value
    const [data, bank] = await Promise.all([
      listOJCourseSubmissions(courseId.value, params),
      listOJProblems(courseId.value, { page_size: 100 }).catch(() => null),
    ])
    items.value = Array.isArray(data?.items) ? data.items : []
    problems.value = Array.isArray(bank?.items) ? bank.items : []
    state.value = 'ready'
  } catch (caught) {
    error.value = caught?.message || '评测记录加载失败'
    state.value = 'error'
  }
}

function problemTitle(experimentId) {
  const found = problems.value.find((i) => i.experiment_id === experimentId)
  return found?.title || experimentId || '—'
}

onMounted(async () => {
  try {
    await loadCourses()
    await load()
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
        <h1 class="sfx-t-title1">评测记录</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">
          课程内全部提交流水（含学生归属）。学生本人视角在「我的提交」。
        </p>
      </div>
      <SfxButton variant="secondary" size="sm" @click="load">刷新</SfxButton>
    </header>

    <label v-if="courses.length" class="oj-course-select sfx-t-ui">
      课程
      <select v-model="courseId" class="sfx-select" @change="load()">
        <option v-for="course in courses" :key="course.course_id" :value="String(course.course_id)">
          {{ course.title }}
        </option>
      </select>
    </label>

    <section class="sfx-panel oj-filters">
      <select v-model="problemFilter" class="sfx-select" @change="load()">
        <option value="">全部题目</option>
        <option v-for="item in problems" :key="item.experiment_id" :value="item.experiment_id">
          {{ item.title }}
        </option>
      </select>
      <select v-model="outcomeFilter" class="sfx-select" @change="load()">
        <option value="">全部结果</option>
        <option v-for="opt in outcomeOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
      </select>
      <SfxButton variant="primary" size="sm" @click="load()">筛选</SfxButton>
    </section>

    <SfxSkeleton v-if="state === 'loading'" :lines="6" block />
    <SfxError v-else-if="state === 'error'" :description="error" @retry="load" />
    <SfxEmpty
      v-else-if="state === 'empty' || !items.length"
      title="还没有提交记录"
      description="学生提交运行后会出现在这里。"
    />
    <section v-else class="sfx-panel oj-table-panel">
      <table class="oj-table">
        <thead>
          <tr>
            <th>提交时间</th><th>学生</th><th>题目</th><th>结果</th>
            <th>语言</th><th>用例</th><th>用时</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in items" :key="row.run_id">
            <td class="sfx-t-ui">{{ row.submitted_at ? row.submitted_at.slice(0, 16).replace('T', ' ') : '—' }}</td>
            <td class="sfx-t-ui">{{ row.username }}</td>
            <td class="sfx-t-ui">{{ problemTitle(row.experiment_id) }}</td>
            <td><SfxBadge :tone="outcomeTone(row.outcome)">{{ outcomeLabel(row.outcome) }}</SfxBadge></td>
            <td class="sfx-t-ui">{{ row.language }}</td>
            <td class="sfx-t-ui">{{ row.passed_count }}/{{ row.total_count }}</td>
            <td class="sfx-t-ui">{{ row.cpu_time_ms === null ? '—' : `${row.cpu_time_ms} ms` }}</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<style scoped>
.oj-course-select { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-4); }
.oj-filters { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; margin-bottom: var(--space-5); }
.oj-table-panel { overflow-x: auto; }
.oj-table { width: 100%; border-collapse: collapse; }
.oj-table th, .oj-table td { text-align: left; padding: var(--space-3) var(--space-4); border-bottom: 1px solid var(--border-default); white-space: nowrap; }
.oj-table th { color: var(--text-secondary); font-size: var(--ui-sm-size); }

/* 基础样式 .sfx-input/.sfx-select 是 width:100%（base.css）——横向行里必须
   显式约束宽度，否则每个控件各占一行（2026-09-11 截图复核发现）。 */
.oj-filters .sfx-input, .oj-filters .sfx-select { width: auto; flex: 0 0 auto; min-width: 150px; }
</style>
