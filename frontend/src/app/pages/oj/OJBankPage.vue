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
import { buildProblemNoIndex, formatPassRate, sortProblems } from './ojTheme.js'

/**
 * OJ 题库列表（复刻参考截图的列表页）。
 *
 * 数据流：
 *  ① catalog —— **不打任何筛选**拉一次全量课程目录，只用于①题号派生②顶部摘要。
 *     ⚠️ 题号必须由它派生：用筛选后的结果编号，一筛选整列题号就会平移
 *     （ojTheme.test.js 有专门的反向验证用例钉住这点）。
 *  ② problems —— 带筛选 + 分页的服务端结果，是表格的唯一数据源。
 *
 * 学生身份下只列已发布题（PUBLISHED + course_catalog），由后端 façade 保证。
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

/** 全量课程目录（未筛选）—— 题号与摘要的唯一来源。 */
const catalog = ref([])
const catalogTotal = ref(0)
const CATALOG_PAGE_SIZE = 100

const filters = ref({
  difficulty: '',
  status: '',
  search: '',
  searchInStatement: false,
  selectedTags: [],
})
const sortBy = ref('default')
const sortOrder = ref('asc')
const selected = ref([])
// 默认开启多选（参考截图里每行可见勾选框）；关掉时清空选中，避免留下不可见的"幽灵选择"
const multiSelect = ref(true)

/** 题号索引：catalog → { experiment_id: '#015' }。 */
const problemNoIndex = computed(() => buildProblemNoIndex(catalog.value))
const problemNoOf = (problem) => problemNoIndex.value.get(String(problem?.experiment_id)) || '—'

/** 后端是否支持按题面正文检索（接口规范 B1 的 search_in）。 */
const statementSearchSupported = false

const banks = computed(() => courses.value.map((course) => ({
  key: String(course.course_id),
  label: course.title || `课程 ${course.course_id}`,
})))

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
  const rates = items.filter((item) => item.pass_rate !== null && item.pass_rate !== undefined).map((item) => item.pass_rate)
  const avg = rates.length ? rates.reduce((sum, rate) => sum + rate, 0) / rates.length : null
  return {
    total: catalogTotal.value || items.length,
    solved,
    attempted,
    avg: formatPassRate(avg),
  }
})

const sortedProblems = computed(() => sortProblems(problems.value, {
  sortBy: sortBy.value,
  sortOrder: sortOrder.value,
  problemNoOf: (problem) => problemNoOf(problem),
}))

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

/** 页码窗口：始终最多 7 个，避免几百页时把分页条撑爆。 */
const pageNumbers = computed(() => {
  const last = totalPages.value
  const current = page.value
  if (last <= 7) return Array.from({ length: last }, (_, i) => i + 1)
  const start = Math.max(1, Math.min(current - 3, last - 6))
  return Array.from({ length: 7 }, (_, i) => start + i)
})

function buildParams(extra = {}) {
  const params = { page: page.value, page_size: pageSize.value, ...extra }
  const search = filters.value.search.trim()
  if (search) params.search = search
  if (filters.value.difficulty) params.difficulty = filters.value.difficulty
  if (filters.value.status) params.status = filters.value.status
  if (filters.value.selectedTags.length) params.tags = filters.value.selectedTags.join(',')
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
  filters.value = { difficulty: '', status: '', search: '', searchInStatement: false, selectedTags: [] }
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
  // 带上当前选中课程：详情页用同一课程查题，否则多课学生会 404
  router.push({
    path: `/app/oj/problems/${problem.experiment_id}`,
    query: { course: courseId.value },
  })
}

watch(courseId, () => {
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
      v-model:active-bank="courseId"
      v-model:difficulty="filters.difficulty"
      v-model:status="filters.status"
      v-model:search="filters.search"
      v-model:search-in-statement="filters.searchInStatement"
      v-model:selected-tags="filters.selectedTags"
      :banks="banks"
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
        :problems="sortedProblems"
        :problem-no-of="problemNoOf"
        :loading="state === 'loading'"
        @open="openProblem"
      />

      <div v-if="totalPages > 1" class="oj-pager">
        <span class="oj-pager-info">共 {{ total }} 题 · 第 {{ page }} / {{ totalPages }} 页</span>
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
        题号按课程目录顺序派生，当前仅覆盖前 {{ catalog.length }} 题；剩余题目题号显示为「—」。
      </p>
    </template>
  </div>
</template>

<style scoped>
.oj-head-actions { flex-wrap: wrap; justify-content: flex-end; }
.oj-head-summary { font-size: var(--ui-sm-size); color: var(--text-secondary); white-space: nowrap; }
.oj-head-summary strong { color: var(--text-primary); }

.oj-pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--space-3);
  margin-top: var(--space-5);
}
.oj-pager-info { display: inline-flex; align-items: center; gap: var(--space-2); font-size: var(--ui-sm-size); color: var(--text-secondary); }
/* 基础 .sfx-select 是 width:100%（base.css）—— 行内必须显式约束宽度 */
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
