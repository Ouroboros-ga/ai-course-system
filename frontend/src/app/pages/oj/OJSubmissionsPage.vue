<script setup>
import { computed, onMounted, ref } from 'vue'
import { listExperimentCourses } from '@/api/labs.js'
import { getOJProblem, listOJProblems, listOJSubmissions } from '@/api/oj.js'
import { getExperimentRun } from '@/api/experiments.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

/**
 * 我的提交（PR-10，设计稿③）：左列提交记录，右列单条详情。
 * 数据按 token 学生过滤；他人提交不可见（后端 404）。
 * 评测解读走题目详情页 Workbench 的 diagnosis 通道，本页只做记录回看。
 */
const courses = ref([])
const courseId = ref('')
const state = ref('loading')
const error = ref('')

const problems = ref([])
const problemFilter = ref('')
const outcomeFilter = ref('')
const languageFilter = ref('')
const dateFrom = ref('')
const dateTo = ref('')

const submissions = ref([])
const selected = ref(null)
const detailState = ref('idle')
const detailError = ref('')
const runDetail = ref(null)
const runDetailState = ref('idle')
const activeTab = ref('cases')

const testResults = computed(() => {
  const rows = runDetail.value?.test_results
  return Array.isArray(rows) ? rows : []
})

const outcomeOptions = [
  { value: 'accepted', label: '通过' },
  { value: 'wrong_answer', label: '答案错误' },
  { value: 'runtime_error', label: '运行错误' },
  { value: 'time_limit_exceeded', label: '超时' },
  { value: 'compile_error', label: '编译错误' },
]

const problemTitles = computed(() => {
  const map = new Map()
  for (const item of problems.value) map.set(item.experiment_id, item.title)
  return map
})

async function loadCourses() {
  courses.value = await listExperimentCourses()
  courseId.value = courses.value[0] ? String(courses.value[0].course_id) : ''
}

async function loadProblems() {
  if (!courseId.value) return
  const data = await listOJProblems(courseId.value, { page_size: 100 }).catch(() => null)
  problems.value = Array.isArray(data?.items) ? data.items : []
}

async function loadSubmissions() {
  if (!courseId.value) {
    state.value = 'empty'
    return
  }
  state.value = 'loading'
  error.value = ''
  try {
    const params = { limit: 100 }
    if (problemFilter.value) params.experiment_id = problemFilter.value
    if (outcomeFilter.value) params.outcome = outcomeFilter.value
    if (languageFilter.value) params.language = languageFilter.value
    if (dateFrom.value) params.date_from = dateFrom.value
    if (dateTo.value) params.date_to = dateTo.value
    const data = await listOJSubmissions(courseId.value, params)
    submissions.value = Array.isArray(data?.items) ? data.items : []
    if (submissions.value.length) {
      await selectRun(submissions.value[0])
    } else {
      selected.value = null
    }
    state.value = 'ready'
  } catch (caught) {
    error.value = caught?.message || '提交记录加载失败'
    state.value = 'error'
  }
}

async function selectRun(run) {
  detailState.value = 'loading'
  detailError.value = ''
  selected.value = null
  runDetail.value = null
  activeTab.value = 'cases'
  try {
    selected.value = await getOJSubmission(courseId.value, run.run_id)
    detailState.value = 'ready'
    // 逐用例结果 / 源代码 / 编译输出 —— 复用既有 run 资源端点
    // （后端已对学生做隐藏用例脱敏；本人的代码与输出可见）
    runDetailState.value = 'loading'
    try {
      runDetail.value = await getExperimentRun(courseId.value, run.run_id)
      runDetailState.value = 'ready'
    } catch {
      runDetail.value = null
      runDetailState.value = 'error'
    }
  } catch (caught) {
    detailError.value = caught?.message || '详情加载失败'
    detailState.value = 'error'
  }
}

function formatMs(value) {
  return value === null || value === undefined ? '—' : `${value} ms`
}

function problemTitle(experimentId) {
  return problemTitles.value.get(experimentId) || experimentId || '—'
}

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

onMounted(async () => {
  try {
    await loadCourses()
    await Promise.all([loadProblems(), loadSubmissions()])
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
        <h1 class="sfx-t-title1">我的提交</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">
          历史提交与评测结果回看。按题目 / 结果 / 语言筛选。
        </p>
      </div>
      <SfxButton variant="secondary" size="sm" @click="loadSubmissions">刷新</SfxButton>
    </header>

    <label v-if="courses.length" class="oj-course-select sfx-t-ui">
      <span class="oj-course-label">课程</span>
      <select v-model="courseId" class="sfx-select" @change="loadProblems(); loadSubmissions()">
        <option v-for="course in courses" :key="course.course_id" :value="String(course.course_id)">
          {{ course.title }}
        </option>
      </select>
    </label>

    <section class="sfx-panel oj-filters">
      <select v-model="problemFilter" class="sfx-select" @change="loadSubmissions()">
        <option value="">全部题目</option>
        <option v-for="item in problems" :key="item.experiment_id" :value="item.experiment_id">
          {{ item.title }}
        </option>
      </select>
      <select v-model="outcomeFilter" class="sfx-select" @change="loadSubmissions()">
        <option value="">全部结果</option>
        <option v-for="opt in outcomeOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
      </select>
      <input
        v-model="languageFilter"
        class="sfx-input"
        type="search"
        placeholder="语言，如 python3"
        @keyup.enter="loadSubmissions()"
      />
      <label class="sfx-t-ui oj-date-label">从 <input v-model="dateFrom" class="sfx-input" type="date" @change="loadSubmissions()" /></label>
      <label class="sfx-t-ui oj-date-label">至 <input v-model="dateTo" class="sfx-input" type="date" @change="loadSubmissions()" /></label>
      <SfxButton variant="primary" size="sm" @click="loadSubmissions()">筛选</SfxButton>
    </section>

    <SfxSkeleton v-if="state === 'loading'" :lines="6" block />
    <SfxError v-else-if="state === 'error'" :description="error" @retry="loadSubmissions" />
    <SfxEmpty
      v-else-if="state === 'empty' || !submissions.length"
      title="还没有提交记录"
      description="到题库列表挑一道题开始作答吧。"
    />

    <div v-else class="oj-sub-grid">
      <section class="sfx-panel oj-sub-list">
        <div
          v-for="item in submissions"
          :key="item.run_id"
          role="button"
          tabindex="0"
          class="oj-sub-row"
          :class="{ 'is-active': selected?.run_id === item.run_id }"
          @click="selectRun(item)"
          @keyup.enter="selectRun(item)"
        >
          <div class="oj-sub-row-head">
            <span class="oj-problem-title">{{ problemTitle(item.experiment_id) }}</span>
            <SfxBadge :tone="outcomeTone(item.outcome)">{{ outcomeLabel(item.outcome) }}</SfxBadge>
          </div>
          <div class="sfx-t-caption sfx-t-secondary">
            {{ item.language }} · {{ item.passed_count }}/{{ item.total_count }} 用例 ·
            {{ item.cpu_time_ms === null ? '—' : `${item.cpu_time_ms} ms` }}
            <template v-if="item.submitted_at"> · {{ item.submitted_at.slice(0, 16).replace('T', ' ') }}</template>
          </div>
        </div>
      </section>

      <section class="sfx-panel oj-sub-detail">
        <SfxSkeleton v-if="detailState === 'loading'" :lines="5" block />
        <SfxError v-else-if="detailState === 'error'" :description="detailError" @retry="selectRun(selected || submissions[0])" />
        <SfxEmpty v-else-if="!selected" title="选择左侧一条提交查看详情" />
        <template v-else>
          <div class="oj-sub-detail-head">
            <h2 class="sfx-t-title3">{{ problemTitle(selected.experiment_id) }}</h2>
            <SfxBadge :tone="outcomeTone(selected.outcome)">{{ outcomeLabel(selected.outcome) }}</SfxBadge>
          </div>
          <dl class="oj-sub-facts sfx-t-ui">
            <div><dt>语言</dt><dd>{{ selected.language }}</dd></div>
            <div><dt>用例</dt><dd>{{ selected.passed_count }} / {{ selected.total_count }}</dd></div>
            <div><dt>得分</dt><dd>{{ selected.score === null ? '—' : selected.score }}</dd></div>
            <div><dt>运行时间</dt><dd>{{ selected.cpu_time_ms === null ? '—' : `${selected.cpu_time_ms} ms` }}</dd></div>
            <div><dt>内存</dt><dd>{{ selected.memory_kb === null ? '—' : `${selected.memory_kb} KB` }}</dd></div>
            <div><dt>状态</dt><dd>{{ selected.run_state }}</dd></div>
          </dl>
          <div class="oj-tabs" role="tablist">
            <span
              v-for="tab in [
                ['cases', `评测详情（${testResults.length}）`],
                ['code', '代码'],
                ['output', '执行输出'],
              ]"
              :key="tab[0]"
              role="tab"
              tabindex="0"
              class="oj-tab"
              :class="{ 'is-active': activeTab === tab[0] }"
              @click="activeTab = tab[0]"
              @keyup.enter="activeTab = tab[0]"
            >{{ tab[1] }}</span>
          </div>

          <SfxSkeleton v-if="runDetailState === 'loading'" :lines="3" block />

          <template v-else-if="runDetailState === 'ready' && runDetail">
            <div v-if="activeTab === 'cases'" class="oj-cases">
              <p v-if="!testResults.length" class="sfx-t-caption sfx-t-secondary">
                暂无逐用例数据（隐藏用例只显示通过与否）。
              </p>
              <table v-else class="oj-table">
                <thead>
                  <tr><th>#</th><th>结果</th><th>用时</th><th>内存</th></tr>
                </thead>
                <tbody>
                  <tr v-for="(row, idx) in testResults" :key="idx">
                    <td class="sfx-t-ui">{{ idx + 1 }}{{ row.is_hidden ? '（隐藏）' : '' }}</td>
                    <td>
                      <SfxBadge :tone="row.passed ? 'green' : 'red'">
                        {{ row.passed ? '通过' : '未通过' }}
                      </SfxBadge>
                    </td>
                    <td class="sfx-t-ui">{{ formatMs(row.time_ms) }}</td>
                    <td class="sfx-t-ui">{{ row.memory_kb === null || row.memory_kb === undefined ? '—' : `${row.memory_kb} KB` }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <pre v-else-if="activeTab === 'code'" class="oj-code">{{ runDetail.source_code || '（无源代码记录）' }}</pre>

            <div v-else class="oj-output sfx-t-ui">
              <p><strong>编译信息</strong></p>
              <pre class="oj-output-pre">{{ runDetail.compile_message || '（无）' }}</pre>
              <p><strong>运行输出</strong></p>
              <pre class="oj-output-pre">{{ runDetail.runtime_message || '（无）' }}</pre>
            </div>
          </template>

          <p class="sfx-t-caption sfx-t-secondary">
            逐题诊断与讲解在题目详情页的 Workbench 内查看（diagnosis 通道）。
          </p>
        </template>
      </section>
    </div>
  </div>
</template>

<style scoped>
.oj-course-select { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-4); }
.oj-course-label { flex: 0 0 auto; white-space: nowrap; }
/* label 文本在 flex 里被压成一字一行（2026-09-12 云端截图发现）——nowrap 修 */
.oj-filters { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; margin-bottom: var(--space-5); }
.oj-filters .sfx-input { min-width: 180px; }
.oj-sub-grid {
  display: grid;
  grid-template-columns: minmax(0, 7fr) minmax(0, 5fr);
  gap: var(--space-5);
  align-items: start;
}
.oj-sub-list { display: flex; flex-direction: column; padding: 0; max-height: 560px; overflow-y: auto; }
.oj-sub-row {
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--border-default);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.oj-sub-row:hover { background: var(--surface-subtle, rgba(0, 0, 0, 0.02)); }
.oj-sub-row.is-active { box-shadow: inset 2px 0 0 var(--ink-900); }
.oj-sub-row-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); }
.oj-problem-title { color: var(--ink-900); }
.oj-sub-detail { display: flex; flex-direction: column; gap: var(--space-4); }
.oj-sub-detail-head { display: flex; align-items: center; gap: var(--space-3); }
.oj-sub-facts { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: var(--space-3); }
.oj-sub-facts div { border-left: 1px solid var(--border-default); padding-left: var(--space-3); }
.oj-sub-facts dt { color: var(--text-secondary); font-size: var(--ui-sm-size); }
.oj-sub-facts dd { margin: 0; color: var(--ink-900); }
@media (max-width: 1024px) {
  .oj-sub-grid { grid-template-columns: 1fr; }
}

.oj-tabs { display: flex; gap: var(--space-1); border-bottom: 1px solid var(--border-default); }
.oj-tab { padding: var(--space-2) var(--space-3); cursor: pointer; color: var(--text-secondary); font-size: var(--ui-md-size); }
.oj-tab.is-active { color: var(--ink-900); box-shadow: inset 0 -2px 0 var(--ink-900); }
.oj-cases { overflow-x: auto; }
.oj-table { width: 100%; border-collapse: collapse; }
.oj-table th, .oj-table td { text-align: left; padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--border-default); }
.oj-code, .oj-output-pre {
  background: var(--surface-subtle, rgba(0, 0, 0, 0.03));
  padding: var(--space-3);
  font-family: var(--font-mono, monospace);
  font-size: var(--ui-sm-size);
  overflow-x: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  margin: 0;
}
.oj-output { display: flex; flex-direction: column; gap: var(--space-2); }

/* 基础样式 .sfx-input/.sfx-select 是 width:100%（base.css）——横向行里必须
   显式约束宽度，否则每个控件各占一行（2026-09-11 截图复核发现）。 */
.oj-filters .sfx-input, .oj-filters .sfx-select { width: auto; flex: 0 0 auto; min-width: 150px; }
.oj-date-label { display: inline-flex; align-items: center; gap: var(--space-2); }
.oj-date-label .sfx-input { width: auto; }
</style>
