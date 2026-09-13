<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import request from '@/utils/request.js'
import { listFacadeCourseItems } from '@/api/facade.js'
import { getOJAnalytics } from '@/api/oj.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

/**
 * 题目管理（教师，设计稿⑤的可行子集）。
 * 后端就绪：列表（全状态）/ 发布 / 归档 / 快速改元数据（来源 / 年份）；
 * 完整题面编辑在课程出题面板完成（顶部按钮跳转）。
 *
 * ⚠️ 课程列表必须经 `listFacadeCourseItems` 解包 —— `/facade/courses` 返回的是
 * `{items, total, ...}` 信封而不是裸数组。曾经直接赋值导致 `courseId` 恒为空，
 * 顶部按钮于是拼出 `/app/course//experiments`，点击后落到首页
 * （2026-09-13 实测复现）。
 */
const router = useRouter()
const courses = ref([])
const courseId = ref('')
const state = ref('loading')
const error = ref('')
const items = ref([])
const search = ref('')
const statusFilter = ref('')
const difficultyFilter = ref('')
const busyId = ref('')
const usageByExp = ref({})
/** 行内元数据编辑（来源 / 年份）—— 只改这两个字段，走 PATCH 语义的 PUT。 */
const metaDraft = ref({})
const metaBusy = ref('')

const stats = computed(() => {
  const total = items.value.length
  const published = items.value.filter((i) => i.publish_status === 'published').length
  return { total, published, draft: total - published }
})

async function loadCourses() {
  courses.value = await listFacadeCourseItems('building').catch(() => [])
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
    // 使用次数 = 尝试计数（看板聚合端点 problem_stats 的逐题统计）
    const analytics = await getOJAnalytics(courseId.value).catch(() => null)
    const statsMap = {}
    for (const stat of analytics?.problem_stats || []) {
      statsMap[stat.experiment_id] = stat.attempt_total
    }
    usageByExp.value = statsMap
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

/** 课程内出题面板（创建 / 编辑 / 测试用例 / 发布的完整工作台）。 */
const coursePanelPath = computed(() => (
  courseId.value ? `/app/course/${courseId.value}/experiments` : ''
))

function openCoursePanel() {
  // 没有课程就没有可跳转的面板 —— 早退，而不是拼一个不存在的路径。
  // 曾经这里无条件 push(`/app/course/${courseId}/experiments`)，courseId 为空时
  // 得到 `/app/course//experiments`，路由不匹配 → 用户被丢到首页
  // （2026-09-13 实测复现）。
  if (!coursePanelPath.value) return
  router.push(coursePanelPath.value)
}

/** 展开某行的来源 / 年份输入。 */
function editMeta(item) {
  metaDraft.value = {
    ...metaDraft.value,
    [item.experiment_id]: { source: item.source ?? '', year: item.year ?? '' },
  }
}

/**
 * 行内保存来源 / 年份。
 *
 * PATCH 语义：`source` 空串 = 清空；`year` 传 `0` = 清空（后端 `CLEAR_YEAR`）。
 * 不传的字段保持原值 —— 只改这两列，不会顺手把难度/标签重置。
 */
async function saveMeta(item) {
  const draft = metaDraft.value[item.experiment_id]
  if (!draft) return
  metaBusy.value = item.experiment_id
  error.value = ''
  try {
    const yearText = String(draft.year ?? '').trim()
    await request.put(
      `/experiments/course/${courseId.value}/definitions/${item.experiment_id}`,
      {
        source: String(draft.source ?? '').trim(),
        year: yearText === '' ? 0 : Number(yearText),
      },
    )
    const next = { ...metaDraft.value }
    delete next[item.experiment_id]
    metaDraft.value = next
    await load()
  } catch (caught) {
    error.value = caught?.message || '来源 / 年份保存失败'
  } finally {
    metaBusy.value = ''
  }
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
      <SfxButton
        variant="primary"
        size="sm"
        :disabled="!coursePanelPath"
        :title="coursePanelPath
          ? '打开课程出题面板（题面 / 测试用例 / 发布）'
          : '还没有在教课程，无法进入出题面板'"
        @click="openCoursePanel"
      >
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
            <tr><th>题目</th><th>难度</th><th>标签</th><th>来源 / 年份</th><th>使用次数</th><th>状态</th><th>操作</th></tr>
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
              <td class="oj-col-meta">
                <template v-if="metaDraft[item.experiment_id]">
                  <input
                    v-model="metaDraft[item.experiment_id].source"
                    class="sfx-input oj-meta-source"
                    type="text"
                    placeholder="来源"
                    aria-label="题目来源"
                  />
                  <input
                    v-model="metaDraft[item.experiment_id].year"
                    class="sfx-input oj-meta-year"
                    type="number"
                    placeholder="年份"
                    aria-label="题目年份"
                  />
                  <span
                    role="button"
                    tabindex="0"
                    class="oj-action"
                    @click="saveMeta(item)"
                    @keyup.enter="saveMeta(item)"
                  >{{ metaBusy === item.experiment_id ? '保存中…' : '保存' }}</span>
                </template>
                <template v-else>
                  <span class="oj-meta-text">{{ item.source || '未填来源' }}</span>
                  <span class="oj-meta-text">{{ item.year || '未填年份' }}</span>
                  <span
                    role="button"
                    tabindex="0"
                    class="oj-action"
                    @click="editMeta(item)"
                    @keyup.enter="editMeta(item)"
                  >修改</span>
                </template>
              </td>
              <td class="sfx-t-ui">{{ usageByExp[item.experiment_id] || 0 }} 次</td>
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
                  :to="`/app/oj/problems/${item.experiment_id}?course=${courseId}`"
                >预览</RouterLink>
              </td>
            </tr>
          </tbody>
        </table>
        <p class="sfx-t-caption sfx-t-secondary oj-hint">
          来源与年份可在本页行内修改（题库列表按来源筛选用）；题面、测试用例与参考解预览在课程出题面板完成（顶部按钮跳转）。
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
.oj-col-meta { display: flex; align-items: center; gap: var(--space-2); }
/* 表格单元格里的 .sfx-input 是 width:100%（base.css）—— 必须显式收窄，
   否则两个输入框各占整行、把表格撑歪 */
.oj-meta-source { width: 116px; }
.oj-meta-year { width: 88px; }
.oj-meta-text { color: var(--text-secondary); font-size: var(--ui-sm-size); }
.oj-tag { margin-right: var(--space-1); }
.oj-actions { display: flex; gap: var(--space-3); }
.oj-action { color: var(--text-secondary); cursor: pointer; font-size: var(--ui-sm-size); text-decoration: none; }
.oj-action:hover { color: var(--ink-900); }
.oj-hint { padding: var(--space-3) var(--space-4); }

/* 基础样式 .sfx-input/.sfx-select 是 width:100%（base.css）——横向行里必须
   显式约束宽度，否则每个控件各占一行（2026-09-11 截图复核发现）。 */
.oj-filters .sfx-input, .oj-filters .sfx-select { width: auto; flex: 0 0 auto; min-width: 150px; }
</style>
