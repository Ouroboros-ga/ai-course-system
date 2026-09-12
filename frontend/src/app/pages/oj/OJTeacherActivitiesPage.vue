<script setup>
import { computed, onMounted, ref } from 'vue'
import request from '@/utils/request.js'
import { listFacadeCourses } from '@/api/facade.js'
import {
  addOJActivityProblem, archiveOJActivity, createOJActivity,
  listOJActivities, publishOJActivity, removeOJActivityProblem, setOJActivityScopes,
} from '@/api/oj.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

/**
 * 活动管理（教师，PR-08 端点的管理页；设计稿⑧的作业形态，contest 未做）。
 * 防作弊设置 / icpc 排行规则后端未实现，表单里不出现（不做假开关）。
 */
const courses = ref([])
const courseId = ref('')
const state = ref('loading')
const error = ref('')
const message = ref('')
const activities = ref([])
const definitions = ref([])
const busy = ref(false)

const form = ref({
  title: '',
  description_md: '',
  start_at: '',
  end_at: '',
  allow_late_submit: false,
  max_submissions: 0,
})
const scopeWholeCourse = ref(true)
const selectedActivityId = ref('')
const problemPick = ref('')

const selectedActivity = computed(() =>
  activities.value.find((a) => a.activity_id === selectedActivityId.value) || null
)
const detail = ref(null)

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
  message.value = ''
  try {
    const [acts, defs] = await Promise.all([
      listOJActivities(courseId.value),
      request.get(`/experiments/course/${courseId.value}/definitions`).catch(() => null),
    ])
    activities.value = Array.isArray(acts?.items) ? acts.items : []
    definitions.value = Array.isArray(defs?.items) ? defs.items : []
    if (!selectedActivityId.value && activities.value.length) {
      selectedActivityId.value = activities.value[0].activity_id
    }
    await loadDetail()
    state.value = activities.value.length ? 'ready' : 'empty'
  } catch (caught) {
    error.value = caught?.message || '活动加载失败'
    state.value = 'error'
  }
}

async function loadDetail() {
  if (!selectedActivityId.value) {
    detail.value = null
    return
  }
  detail.value = await request.get(
    `/experiments/course/${courseId.value}/activities/${selectedActivityId.value}`,
  )
}

async function createActivity() {
  if (!form.value.title.trim()) {
    error.value = '请填写活动标题'
    return
  }
  busy.value = true
  error.value = ''
  try {
    const payload = {
      title: form.value.title.trim(),
      description_md: form.value.description_md,
      allow_late_submit: form.value.allow_late_submit,
      max_submissions: form.value.max_submissions,
    }
    if (form.value.start_at) payload.start_at = form.value.start_at
    if (form.value.end_at) payload.end_at = form.value.end_at
    const created = await createOJActivity(courseId.value, payload)
    message.value = `活动「${created.title}」已创建（草稿）`
    form.value = { title: '', description_md: '', start_at: '', end_at: '', allow_late_submit: false, max_submissions: 0 }
    selectedActivityId.value = created.activity_id
    await load()
  } catch (caught) {
    error.value = caught?.message || '创建失败'
  } finally {
    busy.value = false
  }
}

async function doAction(activity, action) {
  busy.value = true
  error.value = ''
  try {
    if (action === 'publish') await publishOJActivity(courseId.value, activity.activity_id)
    if (action === 'archive') await archiveOJActivity(courseId.value, activity.activity_id)
    message.value = '操作完成'
    await load()
  } catch (caught) {
    error.value = caught?.message || '操作失败'
  } finally {
    busy.value = false
  }
}

async function attachProblem() {
  if (!problemPick.value || !selectedActivityId.value) return
  busy.value = true
  try {
    await addOJActivityProblem(courseId.value, selectedActivityId.value, {
      problem_definition_id: problemPick.value,
    })
    problemPick.value = ''
    await load()
  } catch (caught) {
    error.value = caught?.message || '挂题失败'
  } finally {
    busy.value = false
  }
}

async function detachProblem(ordinal) {
  busy.value = true
  try {
    await removeOJActivityProblem(courseId.value, selectedActivityId.value, ordinal)
    await load()
  } catch (caught) {
    error.value = caught?.message || '移除失败'
  } finally {
    busy.value = false
  }
}

async function saveScopes() {
  if (!selectedActivityId.value) return
  busy.value = true
  try {
    const scopes = scopeWholeCourse.value
      ? [{ scope_type: 'course', scope_id: Number(courseId.value) }]
      : []
    await setOJActivityScopes(courseId.value, selectedActivityId.value, scopes)
    await load()
    message.value = scopeWholeCourse.value ? '已对全课程开放' : '已清空可见范围'
  } catch (caught) {
    error.value = caught?.message || '保存失败'
  } finally {
    busy.value = false
  }
}

function statusLabel(value) {
  return { draft: '草稿', published: '已发布', archived: '已归档' }[value] || value
}

function statusTone(value) {
  return { draft: 'amber', published: 'green', archived: 'ink' }[value] || 'ink'
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
        <h1 class="sfx-t-title1">活动管理</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">
          创建作业 / 练习，挂题并发布。contest 按产品拍板暂不提供。
        </p>
      </div>
      <SfxButton variant="secondary" size="sm" @click="load">刷新</SfxButton>
    </header>

    <label v-if="courses.length" class="oj-course-select sfx-t-ui">
      <span class="oj-course-label">课程</span>
      <select v-model="courseId" class="sfx-select" @change="load()">
        <option v-for="course in courses" :key="course.course_id" :value="String(course.course_id)">
          {{ course.title }}
        </option>
      </select>
    </label>

    <SfxError v-if="error" :description="error" />
    <p v-if="message" class="sfx-t-ui oj-message">{{ message }}</p>

    <SfxSkeleton v-if="state === 'loading'" :lines="5" block />
    <SfxEmpty
      v-else-if="state === 'empty'"
      title="没有可管理的教学课程"
      description="活动管理跟随你在教的课程出现。"
    />
    <template v-else>
      <section class="sfx-panel oj-form">
        <h2 class="oj-section-title">创建活动（草稿）</h2>
        <div class="oj-form-row">
          <input v-model="form.title" class="sfx-input oj-grow" type="text" placeholder="活动标题 *" />
          <label class="sfx-t-ui oj-check">
            <input v-model="form.allow_late_submit" type="checkbox" /> 允许迟交
          </label>
          <label class="sfx-t-ui oj-check">
            每题最大尝试 <input v-model.number="form.max_submissions" class="sfx-input oj-num" type="number" min="0" />
          </label>
        </div>
        <textarea
          v-model="form.description_md"
          class="sfx-input oj-textarea"
          rows="2"
          placeholder="活动说明（可选）"
        ></textarea>
        <div class="oj-form-row">
          <label class="sfx-t-ui">开始 <input v-model="form.start_at" class="sfx-input" type="datetime-local" /></label>
          <label class="sfx-t-ui">截止 <input v-model="form.end_at" class="sfx-input" type="datetime-local" /></label>
          <SfxButton variant="primary" size="sm" :disabled="busy" @click="createActivity">创建</SfxButton>
        </div>
      </section>

      <SfxEmpty v-if="!activities.length" title="还没有活动" description="用上方表单创建第一个作业。" />
      <template v-else>
        <section class="sfx-panel">
          <h2 class="oj-section-title">活动列表</h2>
          <div
            v-for="a in activities"
            :key="a.activity_id"
            role="button"
            tabindex="0"
            class="oj-act-row"
            :class="{ 'is-active': selectedActivityId === a.activity_id }"
            @click="selectedActivityId = a.activity_id; loadDetail()"
            @keyup.enter="selectedActivityId = a.activity_id; loadDetail()"
          >
            <span class="oj-act-title">{{ a.title }}</span>
            <SfxBadge :tone="statusTone(a.status)">{{ statusLabel(a.status) }}</SfxBadge>
            <span
              v-if="a.status === 'draft'"
              role="button"
              tabindex="0"
              class="oj-action"
              @click.stop="doAction(a, 'publish')"
            >发布</span>
            <span
              v-if="a.status !== 'archived'"
              role="button"
              tabindex="0"
              class="oj-action"
              @click.stop="doAction(a, 'archive')"
            >归档</span>
          </div>
        </section>

        <section v-if="detail" class="sfx-panel oj-detail">
          <h2 class="oj-section-title">题目与可见范围 · {{ detail.title }}</h2>
          <div class="oj-form-row">
            <select v-model="problemPick" class="sfx-select oj-grow">
              <option value="">选择要挂入的题目（草稿态才可变更）…</option>
              <option v-for="d in definitions" :key="d.experiment_id" :value="d.experiment_id">
                {{ d.title }}（{{ d.publish_status === 'published' ? '已发布' : '草稿' }}）
              </option>
            </select>
            <SfxButton variant="secondary" size="sm" :disabled="busy || !problemPick" @click="attachProblem">
              挂入活动
            </SfxButton>
          </div>
          <table class="oj-table">
            <thead>
              <tr><th>#</th><th>题目</th><th>版本</th><th>满分</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="p in detail.problems" :key="p.ordinal">
                <td class="sfx-t-ui">{{ p.ordinal }}</td>
                <td class="sfx-t-ui">{{ p.problem_definition_id }}</td>
                <td class="sfx-t-caption sfx-t-secondary">{{ p.problem_version_id }}</td>
                <td class="sfx-t-ui">{{ p.max_score }}</td>
                <td>
                  <span
                    v-if="detail.status === 'draft'"
                    role="button"
                    tabindex="0"
                    class="oj-action"
                    @click="detachProblem(p.ordinal)"
                  >移除</span>
                  <span v-else class="sfx-t-caption sfx-t-secondary">已冻结</span>
                </td>
              </tr>
            </tbody>
          </table>

          <div class="oj-form-row oj-scope-row">
            <label class="sfx-t-ui oj-check">
              <input v-model="scopeWholeCourse" type="checkbox" /> 对全课程学生可见
            </label>
            <SfxButton variant="secondary" size="sm" :disabled="busy" @click="saveScopes">
              保存可见范围
            </SfxButton>
            <span class="sfx-t-caption sfx-t-secondary">
              class / user 级范围可写入但行为未实现；学生侧解析只认 course。
            </span>
          </div>
        </section>
      </template>
    </template>
  </div>
</template>

<style scoped>
.oj-course-select { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-4); }
.oj-course-label { flex: 0 0 auto; white-space: nowrap; }
/* label 文本在 flex 里被压成一字一行（2026-09-12 云端截图发现）——nowrap 修 */
.oj-message { margin-bottom: var(--space-3); color: var(--ink-900); }
.oj-section-title {
  font-size: var(--ui-sm-size);
  font-weight: var(--ui-md-weight);
  color: var(--text-secondary);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: var(--space-3);
}
.oj-form { display: flex; flex-direction: column; gap: var(--space-3); margin-bottom: var(--space-5); }
.oj-form-row { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; }
.oj-grow { flex: 1; min-width: 220px; }
.oj-num { width: 90px; }
.oj-textarea { width: 100%; resize: vertical; }
.oj-check { display: inline-flex; align-items: center; gap: var(--space-2); }
.oj-act-row {
  display: flex; align-items: center; gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--border-default); cursor: pointer;
}
.oj-act-row:hover { background: var(--surface-subtle, rgba(0, 0, 0, 0.02)); }
.oj-act-row.is-active { box-shadow: inset 2px 0 0 var(--ink-900); }
.oj-act-title { flex: 1; color: var(--ink-900); }
.oj-action { color: var(--text-secondary); cursor: pointer; font-size: var(--ui-sm-size); }
.oj-action:hover { color: var(--ink-900); }
.oj-detail { display: flex; flex-direction: column; gap: var(--space-4); }
.oj-scope-row { border-top: 1px solid var(--border-default); padding-top: var(--space-3); }
.oj-table { width: 100%; border-collapse: collapse; }
.oj-table th, .oj-table td { text-align: left; padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--border-default); }

/* 基础样式 .sfx-input/.sfx-select 是 width:100%（base.css）——横向行里必须
   显式约束宽度，否则每个控件各占一行（2026-09-11 截图复核发现）。 */
.oj-form-row .sfx-input, .oj-form-row .sfx-select { width: auto; flex: 0 0 auto; min-width: 150px; }
</style>
