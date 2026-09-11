<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { listExperimentCourses } from '@/api/labs.js'
import { listOJProblems } from '@/api/oj.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

/**
 * OJ 题库列表（PR-10，设计稿①）。
 * 只列已发布题；筛选：搜索 / 难度 / 我的状态 / 标签；显示全班通过率与我的状态。
 * 我的「已通过」口径 = 存在 passed 的正式尝试（与正式学习证据同口径）。
 */
const router = useRouter()

const courses = ref([])
const courseId = ref('')
const state = ref('loading')
const error = ref('')
const problems = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20

const search = ref('')
const difficulty = ref('')
const status = ref('')
const activeTag = ref('')

const difficulties = ['easy', 'medium', 'hard']
const statusOptions = [
  { value: 'not_attempted', label: '未尝试' },
  { value: 'attempted', label: '尝试过' },
  { value: 'solved', label: '已通过' },
]

const allTags = computed(() => {
  const seen = new Set()
  for (const item of problems.value) {
    for (const tag of item.tags || []) seen.add(tag)
  }
  return [...seen].sort((a, b) => a.localeCompare(b, 'zh'))
})

const visibleTags = computed(() => {
  if (!activeTag.value) return allTags.value
  return allTags.value
})

async function loadCourses() {
  courses.value = await listExperimentCourses()
  courseId.value = courses.value[0] ? String(courses.value[0].course_id) : ''
}

async function load() {
  if (!courseId.value) {
    state.value = 'empty'
    return
  }
  state.value = 'loading'
  error.value = ''
  try {
    const params = { page: page.value, page_size: pageSize }
    if (search.value.trim()) params.search = search.value.trim()
    if (difficulty.value) params.difficulty = difficulty.value
    if (status.value) params.status = status.value
    if (activeTag.value) params.tags = activeTag.value
    const data = await listOJProblems(courseId.value, params)
    problems.value = Array.isArray(data?.items) ? data.items : []
    total.value = Number(data?.total || 0)
    state.value = 'ready'
  } catch (caught) {
    error.value = caught?.message || '题库加载失败'
    state.value = 'error'
  }
}

function toggleTag(tag) {
  activeTag.value = activeTag.value === tag ? '' : tag
  page.value = 1
  load()
}

function resetFilters() {
  search.value = ''
  difficulty.value = ''
  status.value = ''
  activeTag.value = ''
  page.value = 1
  load()
}

function totalPages() {
  return Math.max(1, Math.ceil(total.value / pageSize))
}

function gotoPage(next) {
  if (next < 1 || next > totalPages() || next === page.value) return
  page.value = next
  load()
}

function difficultyLabel(value) {
  return { easy: '简单', medium: '中等', hard: '困难' }[value] || value || '—'
}

function difficultyTone(value) {
  return { easy: 'green', medium: 'amber', hard: 'red' }[value] || 'ink'
}

function statusLabel(value) {
  return { solved: '已通过', attempted: '尝试过', not_attempted: '未尝试' }[value] || value
}

function statusTone(value) {
  return { solved: 'green', attempted: 'amber', not_attempted: 'ink' }[value] || 'ink'
}

function formatRate(rate) {
  return rate === null || rate === undefined ? '—' : `${Math.round(rate * 1000) / 10}%`
}

function openProblem(item) {
  router.push(`/app/oj/problems/${item.experiment_id}`)
}

onMounted(async () => {
  try {
    await loadCourses()
    await load()
  } catch (caught) {
    error.value = caught?.message || '课程加载失败'
    state.value = 'error'
  }
})
</script>

<template>
  <div class="sfx-page">
    <header class="sfx-page-header">
      <div>
        <h1 class="sfx-t-title1">题库列表</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">
          课程已发布的编程题目。作答、提交与评测解读都在题目详情页完成。
        </p>
      </div>
      <SfxButton variant="secondary" size="sm" @click="load">刷新</SfxButton>
    </header>

    <label v-if="courses.length" class="oj-course-select sfx-t-ui">
      课程
      <select v-model="courseId" class="sfx-select" @change="page = 1; load()">
        <option v-for="course in courses" :key="course.course_id" :value="String(course.course_id)">
          {{ course.title }}
        </option>
      </select>
    </label>

    <section class="sfx-panel oj-filters">
      <div class="oj-filters-row">
        <input
          v-model="search"
          class="sfx-input oj-search"
          type="search"
          placeholder="搜索题目名称…"
          @keyup.enter="page = 1; load()"
        />
        <select v-model="difficulty" class="sfx-select" @change="page = 1; load()">
          <option value="">全部难度</option>
          <option v-for="d in difficulties" :key="d" :value="d">{{ difficultyLabel(d) }}</option>
        </select>
        <select v-model="status" class="sfx-select" @change="page = 1; load()">
          <option value="">全部状态</option>
          <option v-for="opt in statusOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
        </select>
        <SfxButton variant="secondary" size="sm" @click="resetFilters">重置</SfxButton>
        <SfxButton variant="primary" size="sm" @click="page = 1; load()">筛选</SfxButton>
      </div>
      <div v-if="visibleTags.length" class="oj-tag-row">
        <span
          v-for="tag in visibleTags"
          :key="tag"
          role="button"
          tabindex="0"
          class="oj-tag"
          :class="{ 'is-active': activeTag === tag }"
          @click="toggleTag(tag)"
          @keyup.enter="toggleTag(tag)"
        >{{ tag }}</span>
      </div>
    </section>

    <SfxSkeleton v-if="state === 'loading'" :lines="6" block />
    <SfxError v-else-if="state === 'error'" :description="error" @retry="load" />
    <SfxEmpty
      v-else-if="state === 'empty' || !problems.length"
      title="没有符合条件的题目"
      description="调整筛选条件，或等教师发布新题目。"
    />
    <section v-else class="sfx-panel oj-table-panel">
      <table class="oj-table">
        <thead>
          <tr>
            <th class="oj-col-title">题目</th>
            <th>难度</th>
            <th>标签</th>
            <th>通过率</th>
            <th>我的状态</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="item in problems"
            :key="item.experiment_id"
            class="oj-row"
            role="button"
            tabindex="0"
            @click="openProblem(item)"
            @keyup.enter="openProblem(item)"
          >
            <td class="oj-col-title">
              <span class="oj-problem-title">{{ item.title }}</span>
            </td>
            <td>
              <SfxBadge :tone="difficultyTone(item.difficulty)">
                {{ difficultyLabel(item.difficulty) }}
              </SfxBadge>
            </td>
            <td class="oj-col-tags">
              <span v-for="tag in (item.tags || []).slice(0, 3)" :key="tag" class="oj-tag oj-tag-static">{{ tag }}</span>
              <span v-if="(item.tags || []).length > 3" class="sfx-t-caption sfx-t-secondary">
                +{{ item.tags.length - 3 }}
              </span>
            </td>
            <td class="sfx-t-ui">{{ formatRate(item.pass_rate) }}</td>
            <td>
              <SfxBadge :tone="statusTone(item.my_status)">{{ statusLabel(item.my_status) }}</SfxBadge>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-if="totalPages() > 1" class="oj-pager sfx-t-ui">
        <span>共 {{ total }} 题</span>
        <span
          v-for="p in totalPages()"
          :key="p"
          role="button"
          tabindex="0"
          class="oj-page-num"
          :class="{ 'is-active': p === page }"
          @click="gotoPage(p)"
          @keyup.enter="gotoPage(p)"
        >{{ p }}</span>
      </div>
    </section>
  </div>
</template>

<style scoped>
.oj-course-select { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-4); }
.oj-filters { display: flex; flex-direction: column; gap: var(--space-3); margin-bottom: var(--space-5); }
.oj-filters-row { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; }
.oj-search { flex: 1; min-width: 200px; }
.oj-tag-row { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.oj-tag {
  padding: 2px var(--space-3);
  border: 1px solid var(--border-default);
  font-size: var(--ui-sm-size);
  color: var(--text-secondary);
  cursor: pointer;
  user-select: none;
}
.oj-tag:hover { color: var(--ink-900); border-color: var(--ink-700); }
.oj-tag.is-active { background: var(--ink-900); border-color: var(--ink-900); color: var(--surface-panel); }
.oj-tag-static { cursor: default; }
.oj-tag-static:hover, .oj-tag-static:active { color: var(--text-secondary); border-color: var(--border-default); }
.oj-table-panel { padding: 0; overflow-x: auto; }
.oj-table { width: 100%; border-collapse: collapse; font-size: var(--ui-md-size); }
.oj-table th, .oj-table td { text-align: left; padding: var(--space-3) var(--space-4); border-bottom: 1px solid var(--border-default); white-space: nowrap; }
.oj-table th { color: var(--text-secondary); font-weight: var(--ui-md-weight); font-size: var(--ui-sm-size); }
.oj-row { cursor: pointer; }
.oj-row:hover { background: var(--surface-subtle, rgba(0, 0, 0, 0.02)); }
.oj-col-title { min-width: 220px; }
.oj-problem-title { color: var(--ink-900); }
.oj-col-tags { max-width: 260px; overflow: hidden; text-overflow: ellipsis; }
.oj-pager { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-3) var(--space-4); color: var(--text-secondary); }
.oj-page-num { padding: 2px var(--space-2); cursor: pointer; border: 1px solid transparent; }
.oj-page-num.is-active { border-color: var(--ink-900); color: var(--ink-900); }
</style>
