<script setup>
import { computed, onMounted, ref } from 'vue'
import request from '@/utils/request.js'
import { listFacadeCourses } from '@/api/facade.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

/**
 * 题目管理（教师，设计稿⑤的可行子集）。
 * 后端就绪：列表（全状态）/发布/归档/详情；**批量操作与导入导出无端点，不做**。
 * 编辑与新建走课程内既有的出题面板（本页提供跳转），不重复造表单。
 */
const courses = ref([])
const courseId = ref('')
const state = ref('loading')
const error = ref('')
const items = ref([])
const search = ref('')
const statusFilter = ref('')
const difficultyFilter = ref('')
const busyId = ref('')

const stats = computed(() => {
  const total = items.value.length
  const published = items.value.filter((i) => i.publish_status === 'published').length
  return { total, published, draft: total - published }
})

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
    const data = await request.get(`/experiments/course/${courseId.value}/definitions`)
    let rows = Array.isArray(data?.items) ? data.items : []
    if (search.value.trim()) {
      const kw = search.value.trim().toLowerCase()
      rows = rows.filter((i) => i.title.toLowerCase().includes(kw))
    }
    if (statusFilter.value) rows = rows.filter((i) => i.publish_status === statusFilter.value)
    if (difficultyFilter.value) rows = rows.filter((i) => i.difficulty === difficultyFilter.value)
    items.value = rows
    state.value = 'ready'
  } catch (caught) {
    error.value = caught?.message || '题目加载失败'
    state.value = 'error'
  }
}

async function changeStatus(item, action) {
  busyId.value = item.experiment_id
  try {
    await request.post(
      `/experiments/course/${courseId.value}/definitions/${item.experiment_id}/${action}`,
    )
    await load()
  } catch (caught) {
    error.value = caught?.message || '操作失败'
  } finally {
    busyId.value = ''
  }
}

function coursePanelPath() {
  // 课程内出题面板（创建/编辑/测试用例/发布的完整工作台）
  return `/app/course/${courseId.value}/experiments`
}

function statusLabel(value) {
  return { draft: '草稿', published: '已发布', archived: '已归档' }[value] || value
}

function statusTone(value) {
  return { draft: 'amber', published: 'green', archived: 'ink' }[value] || 'ink'
}

function difficultyLabel(value) {
  return { easy: '简单', medium: '中等', hard: '困难' }[value] || value || '—'
}

function difficultyTone(value) {
  return { easy: 'green', medium: 'amber', hard: 'red' }[value] || 'ink'
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
        <h1 class="sfx-t-title1">题目管理</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">
          课程内 OJ 题目。创建与完整编辑在课程出题面板完成，本页做状态管理与快速跳转。
        </p>
      </div>
      <SfxButton variant="primary" size="sm" @click="$router.push(coursePanelPath())">
        新建 / 编辑题目
      </SfxButton>
    </header>

    <label v-if="courses.length" class="oj-course-select sfx-t-ui">
      <span class="oj-course-label">课程</span>
      <select v-model="courseId" class="sfx-select" @change="load()">
        <option v-for="course in courses" :key="course.course_id" :value="String(course.course_id)">
          {{ course.title }}
        </option>
      </select>
    </label>

    <SfxSkeleton v-if="state === 'loading'" :lines="5" block />
    <SfxError v-else-if="state === 'error'" :description="error" @retry="load" />
    <SfxEmpty
      v-else-if="state === 'empty'"
      title="没有可管理的教学课程"
      description="题目管理跟随你在教的课程出现。"
    />
    <template v-else>
      <section class="oj-stats">
        <div class="sfx-panel oj-stat">
          <span class="sfx-t-caption sfx-t-secondary">题目总数</span>
          <strong class="oj-stat-num">{{ stats.total }}</strong>
        </div>
        <div class="sfx-panel oj-stat">
          <span class="sfx-t-caption sfx-t-secondary">已发布</span>
          <strong class="oj-stat-num">{{ stats.published }}</strong>
        </div>
        <div class="sfx-panel oj-stat">
          <span class="sfx-t-caption sfx-t-secondary">草稿 / 归档</span>
          <strong class="oj-stat-num">{{ stats.draft }}</strong>
        </div>
      </section>

      <section class="sfx-panel oj-filters">
        <input
          v-model="search"
          class="sfx-input oj-search"
          type="search"
          placeholder="搜索题目名称…"
          @keyup.enter="load()"
        />
        <select v-model="statusFilter" class="sfx-select" @change="load()">
          <option value="">全部状态</option>
          <option value="draft">草稿</option>
          <option value="published">已发布</option>
          <option value="archived">已归档</option>
        </select>
        <select v-model="difficultyFilter" class="sfx-select" @change="load()">
          <option value="">全部难度</option>
          <option value="easy">简单</option>
          <option value="medium">中等</option>
          <option value="hard">困难</option>
        </select>
        <SfxButton variant="primary" size="sm" @click="load()">筛选</SfxButton>
      </section>

      <SfxEmpty v-if="!items.length" title="没有符合条件的题目" />
      <section v-else class="sfx-panel oj-table-panel">
        <table class="oj-table">
          <thead>
            <tr><th>题目</th><th>难度</th><th>标签</th><th>状态</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="item in items" :key="item.experiment_id">
              <td class="oj-col-title sfx-t-ui">{{ item.title }}</td>
              <td>
                <SfxBadge :tone="difficultyTone(item.difficulty)">
                  {{ difficultyLabel(item.difficulty) }}
                </SfxBadge>
              </td>
              <td class="oj-col-tags">
                <span v-for="tag in (item.tags || []).slice(0, 3)" :key="tag" class="oj-tag">{{ tag }}</span>
              </td>
              <td>
                <SfxBadge :tone="statusTone(item.publish_status)">
                  {{ statusLabel(item.publish_status) }}
                </SfxBadge>
              </td>
              <td class="oj-actions">
                <span
                  v-if="item.publish_status === 'draft'"
                  role="button"
                  tabindex="0"
                  class="oj-action"
                  @click="changeStatus(item, 'publish')"
                >发布</span>
                <span
                  v-else-if="item.publish_status === 'published'"
                  role="button"
                  tabindex="0"
                  class="oj-action"
                  @click="changeStatus(item, 'archive')"
                >归档</span>
                <RouterLink
                  class="oj-action"
                  :to="`/app/oj/problems/${item.experiment_id}`"
                >预览</RouterLink>
              </td>
            </tr>
          </tbody>
        </table>
        <p class="sfx-t-caption sfx-t-secondary oj-hint">
          题面编辑、测试用例与参考解预览在课程出题面板完成（顶部按钮跳转）。
        </p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.oj-course-select { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-4); }
.oj-course-label { flex: 0 0 auto; white-space: nowrap; }
/* label 文本在 flex 里被压成一字一行（2026-09-12 云端截图发现）——nowrap 修 */
.oj-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: var(--space-4); margin-bottom: var(--space-5); }
.oj-stat { display: flex; flex-direction: column; gap: var(--space-1); }
.oj-stat-num { font-size: 22px; color: var(--ink-900); }
.oj-filters { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; margin-bottom: var(--space-5); }
.oj-search { min-width: 220px; }
.oj-table-panel { overflow-x: auto; }
.oj-table { width: 100%; border-collapse: collapse; }
.oj-table th, .oj-table td { text-align: left; padding: var(--space-3) var(--space-4); border-bottom: 1px solid var(--border-default); white-space: nowrap; }
.oj-table th { color: var(--text-secondary); font-size: var(--ui-sm-size); }
.oj-col-title { min-width: 220px; }
.oj-col-tags { max-width: 240px; }
.oj-tag { margin-right: var(--space-1); }
.oj-actions { display: flex; gap: var(--space-3); }
.oj-action { color: var(--text-secondary); cursor: pointer; font-size: var(--ui-sm-size); text-decoration: none; }
.oj-action:hover { color: var(--ink-900); }
.oj-hint { padding: var(--space-3) var(--space-4); }

/* 基础样式 .sfx-input/.sfx-select 是 width:100%（base.css）——横向行里必须
   显式约束宽度，否则每个控件各占一行（2026-09-11 截图复核发现）。 */
.oj-filters .sfx-input, .oj-filters .sfx-select { width: auto; flex: 0 0 auto; min-width: 150px; }
</style>
