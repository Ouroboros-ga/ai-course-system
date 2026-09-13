<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { RefreshCw } from 'lucide-vue-next'
import { listExperimentCourses } from '@/api/labs.js'
import { listOJProblems } from '@/api/oj.js'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'
import OjFilterPanel from './components/OjFilterPanel.vue'
import OjProblemTable from './components/OjProblemTable.vue'
import {
  buildProblemNoIndex,
  difficultyRangeParams,
  formatPassRate,
  resolveProblemNo,
} from './ojTheme.js'

/**
 * OJ 题库列表（复刻参考截图的列表页）。
 *
 * 数据流：
 *  ① catalog —— **不打任何筛选**拉一次全量课程目录，用于①来源/年份的可选值
 *     ②顶部摘要 ③题号降级派生。
 *  ② problems —— 带筛选 + 排序 + 分页的服务端结果，是表格的唯一数据源。
 *
 * ⚠️ **排序一律在服务端做**（B1）。曾经前端对「当前页」排序，跨页时第一名是错的
 * —— 表头 tooltip 当时只能如实写「排序仅作用于当前页」。现在服务端在全量命中集上
 * 排好再分页，前端不得再插一层本地 sort。
 *
 * ⚠️ 题号优先用服务端下发的 `problem_no`；本地派生只是降级路径（接口未部署 /
 * 离线演示）。两条路径共用同一套规则（未筛选目录 + code-point 升序）。
 */
const router = useRouter()

const courses = ref([])
const courseId = ref('')
const state = ref('loading')
const error = ref('')
const problems = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

/** 全量课程目录（未筛选）—— 来源/年份可选值与摘要的唯一来源。 */
const catalog = ref([])
const catalogTotal = ref(0)
const CATALOG_PAGE_SIZE = 100

const activeSource = ref('')
const filters = ref({
  difficulty: '',
  year: '',
  status: '',
  search: '',
  searchInStatement: false,
  selectedTags: [],
  tagMode: 'or',
})
const sortBy = ref('no')
const sortOrder = ref('asc')
const selected = ref([])
const multiSelect = ref(true)

/** 题号降级索引：catalog → { experiment_id: '#015' }。 */
const problemNoIndex = computed(() => buildProblemNoIndex(catalog.value))
const problemNoOf = (problem) => resolveProblemNo(problem, problemNoIndex.value)

/** B1 已落地 → 「搜索题面」可用。 */
const statementSearchSupported = true

const sources = computed(() => {
  const seen = new Set()
  for (const item of catalog.value) {
    const value = String(item.source ?? '').trim()
    if (value) seen.add(value)
  }
  return [...seen].sort((a, b) => a.localeCompare(b, 'zh'))
})

const years = computed(() => {
  const seen = new Set()
  for (const item of catalog.value) {
    if (item.year !== null && item.year !== undefined) seen.add(Number(item.year))
  }
  return [...seen].sort((a, b) => b - a)
})

const tagOptions = computed(() => {
  const seen = new Set()
  for (const item of catalog.value) {
    for (const tag of item.tags || []) seen.add(tag)
  }
  return [...seen].sort((a, b) => a.localeCompare(b, 'zh'))
})

const summary = computed(() => {
  const items = catalog.value
  const solved = items.filter((item) => item.my_status === 'solved').length
  const attempted = items.filter((item) => item.my_status === 'attempted').length
  const rates = items
    .filter((item) => item.pass_rate !== null && item.pass_rate !== undefined)
    .map((item) => item.pass_rate)
  const avg = rates.length ? rates.reduce((sum, rate) => sum + rate, 0) / rates.length : null
  return {
    total: catalogTotal.value || items.length,
    solved,
    attempted,
    avg: formatPassRate(avg),
  }
})

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

/** 页码窗口：始终最多 7 个，避免几百页时把分页条撑爆。 */
const pageNumbers = computed(() => {
  const last = totalPages.value
  const current = page.value
  if (last <= 7) return Array.from({ length: last }, (_, i) => i + 1)
  const start = Math.max(1, Math.min(current - 3, last - 6))
  return Array.from({ length: 7 }, (_, i) => start + i)
})

function buildParams() {
  const params = {
    page: page.value,
    page_size: pageSize.value,
    // 排序下沉到服务端：它排的是**全量命中集**，不是当前页。
    sort_by: sortBy.value,
    sort_order: sortOrder.value,
  }
  const keyword = filters.value.search.trim()
  if (keyword) params.search = keyword
  if (filters.value.searchInStatement) params.search_in = 'both'
  Object.assign(params, difficultyRangeParams(filters.value.difficulty))
  if (filters.value.status) params.status = filters.value.status
  if (filters.value.selectedTags.length) params.tags = filters.value.selectedTags.join(',')
  // 单选标签时 and 与 or 等价，不必多传一个参数
  if (filters.value.selectedTags.length > 1) params.tag_mode = filters.value.tagMode
  if (activeSource.value) params.source = activeSource.value
  if (filters.value.year) params.year = Number(filters.value.year)
  return params
}

async function loadCatalog() {
  const data = await listOJProblems(courseId.value, { page: 1, page_size: CATALOG_PAGE_SIZE })
  catalog.value = Array.isArray(data?.items) ? data.items : []
  catalogTotal.value = Number(data?.total || catalog.value.length)
}

async function load() {
  if (!courseId.value) {
    state.value = 'empty'
    return
  }
  state.value = 'loading'
  error.value = ''
  try {
    const [data] = await Promise.all([
      listOJProblems(courseId.value, buildParams()),
      loadCatalog(),
    ])
    problems.value = Array.isArray(data?.items) ? data.items : []
    total.value = Number(data?.total || 0)
    // 换页/换课后旧的勾选会指向上页的题 —— 直接清掉比留下"幽灵选中"更诚实
    selected.value = []
    state.value = 'ready'
  } catch (caught) {
    error.value = caught?.message || '题库加载失败'
    state.value = 'error'
  }
}

function resetPageAndLoad() {
  page.value = 1
  load()
}

function clearAll() {
  activeSource.value = ''
  filters.value = {
    difficulty: '', year: '', status: '', search: '',
    searchInStatement: false, selectedTags: [], tagMode: 'or',
  }
  sortBy.value = 'no'
  sortOrder.value = 'asc'
  resetPageAndLoad()
}

function gotoPage(next) {
  if (next < 1 || next > totalPages.value || next === page.value) return
  page.value = next
  load()
}

function openProblem(problem) {
  // 带上当前选中课程与题号：详情页用同一课程查题，否则多课学生会 404
  router.push({
    path: `/app/oj/problems/${problem.experiment_id}`,
    query: { course: courseId.value, no: problemNoOf(problem) },
  })
}

watch(courseId, () => {
  page.value = 1
  activeSource.value = ''
  load()
})

watch(multiSelect, (on) => {
  if (!on) selected.value = []
})

// 排序是服务端行为 → 改排序必须回源，不能在本地重排当前页
watch([sortBy, sortOrder], () => {
  page.value = 1
  load()
})

watch([pageSize], () => {
  page.value = 1
  load()
})

onMounted(async () => {
  try {
    courses.value = await listExperimentCourses()
    courseId.value = courses.value[0] ? String(courses.value[0].course_id) : ''
    if (!courseId.value) {
      state.value = 'empty'
      return
    }
    await load()
  } catch (caught) {
    error.value = caught?.message || '课程加载失败'
    state.value = 'error'
  }
})
</script>

<template>
  <div class="sfx-page oj-bank">
    <header class="sfx-page-header">
      <div>
        <h1 class="sfx-t-title1">题目列表</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">
          课程已发布的编程题目。点开题目即进入作答页，运行与评测都在那里完成。
        </p>
      </div>
      <div class="sfx-page-actions oj-head-actions">
        <label v-if="courses.length" class="oj-head-course sfx-t-ui">
          <span class="oj-head-course-label">课程</span>
          <select v-model="courseId" class="sfx-select oj-head-course-select" aria-label="课程">
            <option v-for="course in courses" :key="course.course_id" :value="String(course.course_id)">
              {{ course.title }}
            </option>
          </select>
        </label>
        <span v-if="state === 'ready'" class="oj-head-summary">
          已通过 <strong>{{ summary.solved }}</strong>
          · 尝试过 <strong>{{ summary.attempted }}</strong>
          · 平均通过率 <strong>{{ summary.avg || '—' }}</strong>
        </span>
        <SfxButton variant="secondary" size="sm" :loading="state === 'loading'" @click="load">
          <template #icon><RefreshCw :size="14" /></template>
          刷新
        </SfxButton>
      </div>
    </header>

    <OjFilterPanel
      v-model:active-source="activeSource"
      v-model:difficulty="filters.difficulty"
      v-model:year="filters.year"
      v-model:status="filters.status"
      v-model:search="filters.search"
      v-model:search-in-statement="filters.searchInStatement"
      v-model:selected-tags="filters.selectedTags"
      v-model:tag-mode="filters.tagMode"
      :sources="sources"
      :years="years"
      :tag-options="tagOptions"
      :total="total"
      :loading="state === 'loading'"
      :statement-search-supported="statementSearchSupported"
      @search="resetPageAndLoad"
      @clear-all="clearAll"
    />

    <SfxSkeleton v-if="state === 'loading' && !problems.length" :lines="6" block />
    <SfxError v-else-if="state === 'error'" :description="error" @retry="load" />
    <template v-else>
      <OjProblemTable
        v-model:sort-by="sortBy"
        v-model:sort-order="sortOrder"
        v-model:selected="selected"
        v-model:multi-select="multiSelect"
        :problems="problems"
        :problem-no-of="problemNoOf"
        :loading="state === 'loading'"
        server-sort
        @open="openProblem"
      />

      <div v-if="totalPages > 1" class="oj-pager">
        <span class="oj-pager-info">
          共 {{ total }} 题 · 第 {{ page }} / {{ totalPages }} 页
          <select v-model.number="pageSize" class="sfx-select oj-pager-size" aria-label="每页条数">
            <option :value="10">10 条/页</option>
            <option :value="20">20 条/页</option>
            <option :value="50">50 条/页</option>
          </select>
        </span>
        <div class="oj-pager-pages">
          <span
            role="button"
            tabindex="0"
            class="oj-page-btn"
            :class="{ 'is-disabled': page <= 1 }"
            aria-label="上一页"
            @click="gotoPage(page - 1)"
            @keyup.enter="gotoPage(page - 1)"
          >上一页</span>
          <span
            v-for="p in pageNumbers"
            :key="p"
            role="button"
            tabindex="0"
            class="oj-page-num"
            :class="{ 'is-active': p === page }"
            :aria-current="p === page ? 'page' : undefined"
            @click="gotoPage(p)"
            @keyup.enter="gotoPage(p)"
          >{{ p }}</span>
          <span
            role="button"
            tabindex="0"
            class="oj-page-btn"
            :class="{ 'is-disabled': page >= totalPages }"
            aria-label="下一页"
            @click="gotoPage(page + 1)"
            @keyup.enter="gotoPage(page + 1)"
          >下一页</span>
        </div>
      </div>

      <p v-if="catalogTotal > catalog.length" class="oj-pager-note">
        来源 / 年份的可选值与题号仅覆盖前 {{ catalog.length }} 题；课程目录超过该数量时请用关键词定位。
      </p>
    </template>
  </div>
</template>

<style scoped>
.oj-head-actions { flex-wrap: wrap; justify-content: flex-end; align-items: center; }
.oj-head-summary { font-size: var(--ui-sm-size); color: var(--text-secondary); white-space: nowrap; }
.oj-head-summary strong { color: var(--text-primary); }
.oj-head-course { display: inline-flex; align-items: center; gap: var(--space-2); white-space: nowrap; }
.oj-head-course-label { color: var(--text-secondary); }
/* 基础 .sfx-select 是 width:100%（base.css）—— 行内必须显式约束宽度 */
.oj-head-course-select { width: auto; flex: 0 0 auto; min-height: 32px; font-size: var(--ui-sm-size); max-width: 320px; }

.oj-pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--space-3);
  margin-top: var(--space-5);
}
.oj-pager-info { display: inline-flex; align-items: center; gap: var(--space-2); font-size: var(--ui-sm-size); color: var(--text-secondary); }
.oj-pager-size { width: auto; flex: 0 0 auto; min-height: 32px; font-size: var(--ui-sm-size); }
.oj-pager-pages { display: flex; align-items: center; gap: var(--space-1); }
.oj-page-btn,
.oj-page-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 32px;
  height: 32px;
  padding: 0 var(--space-2);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-panel);
  font-size: var(--ui-sm-size);
  color: var(--text-secondary);
  cursor: pointer;
  user-select: none;
}
.oj-page-btn:hover,
.oj-page-num:hover { border-color: var(--border-strong); color: var(--ink-900); }
.oj-page-num.is-active {
  background: var(--ink-900);
  border-color: var(--ink-900);
  color: var(--text-inverse);
}
.oj-page-btn.is-disabled { color: var(--text-disabled); cursor: not-allowed; border-color: var(--border-subtle); }

.oj-pager-note { margin: var(--space-3) 0 0; font-size: var(--ui-sm-size); color: var(--text-muted); }

@media (max-width: 760px) {
  .oj-head-actions { justify-content: flex-start; }
  .oj-pager { flex-direction: column; align-items: flex-start; }
}
</style>
