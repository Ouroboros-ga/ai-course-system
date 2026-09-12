<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { listExperimentCourses } from '@/api/labs.js'
import { listOJStudentActivities } from '@/api/oj.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

/**
 * 活动作业（PR-12，设计稿④「待完成的任务」区）。
 * 窗口状态由服务端算好（window_status + can_submit），前端不猜时间；
 * 点题目进详情页作答（Workbench 提交走正式 attempt/run 链）。
 */
const router = useRouter()

const courses = ref([])
const courseId = ref('')
const state = ref('loading')
const error = ref('')
const activities = ref([])

const windowLabels = {
  open: { label: '进行中', tone: 'green' },
  late: { label: '迟交窗口', tone: 'amber' },
  not_started: { label: '未开始', tone: 'ink' },
  ended: { label: '已截止', tone: 'red' },
}

const sorted = computed(() => activities.value)

function windowLabel(status) {
  return windowLabels[status]?.label || status
}

function windowTone(status) {
  return windowLabels[status]?.tone || 'ink'
}

function formatDate(value) {
  return value ? value.slice(0, 16).replace('T', ' ') : '不限'
}

function openProblem(activity, problem) {
  router.push(`/app/oj/problems/${problem.problem_definition_id}`)
}

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
    const data = await listOJStudentActivities(courseId.value)
    activities.value = Array.isArray(data?.items) ? data.items : []
    state.value = 'ready'
  } catch (caught) {
    error.value = caught?.message || '活动加载失败'
    state.value = 'error'
  }
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
        <h1 class="sfx-t-title1">活动作业</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">
          教师发布的作业与练习。截止时间以服务端为准。
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

    <SfxSkeleton v-if="state === 'loading'" :lines="5" block />
    <SfxError v-else-if="state === 'error'" :description="error" @retry="load" />
    <SfxEmpty
      v-else-if="state === 'empty' || !activities.length"
      title="暂无进行中的作业"
      description="教师发布作业后，这里会出现可作答的活动。"
    />
    <section v-else class="oj-assignment-grid">
      <article
        v-for="activity in sorted"
        :key="activity.activity_id"
        class="sfx-panel oj-assignment-card"
      >
        <header class="oj-card-head">
          <h2 class="sfx-t-title3">{{ activity.title }}</h2>
          <SfxBadge :tone="windowTone(activity.window_status)">
            {{ windowLabel(activity.window_status) }}
          </SfxBadge>
        </header>
        <p class="sfx-t-ui sfx-t-secondary oj-desc">
          {{ activity.description_md || '教师未填写说明。' }}
        </p>
        <dl class="oj-facts sfx-t-caption sfx-t-secondary">
          <div><dt>题目</dt><dd>{{ activity.problem_count }} 题</dd></div>
          <div><dt>总分</dt><dd>{{ activity.total_score }}</dd></div>
          <div><dt>开始</dt><dd>{{ formatDate(activity.start_at) }}</dd></div>
          <div><dt>截止</dt><dd>{{ formatDate(activity.end_at) }}</dd></div>
        </dl>
        <div class="oj-problems">
          <span
            v-for="problem in activity.problems"
            :key="problem.ordinal"
            role="button"
            tabindex="0"
            class="oj-problem-chip"
            :class="{ 'is-disabled': !activity.can_submit }"
            @click="activity.can_submit && openProblem(activity, problem)"
            @keyup.enter="activity.can_submit && openProblem(activity, problem)"
          >
            {{ problem.label || problem.ordinal }}. {{ problem.max_score }} 分
          </span>
        </div>
        <p v-if="activity.window_status === 'late'" class="sfx-t-caption">
          已过截止时间，仍可提交（迟交会计入记录）。
        </p>
        <p v-else-if="activity.window_status === 'ended'" class="sfx-t-caption sfx-t-secondary">
          已截止，不可再提交。
        </p>
      </article>
    </section>
  </div>
</template>

<style scoped>
.oj-course-select { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-4); }
.oj-course-label { flex: 0 0 auto; white-space: nowrap; }
/* label 文本在 flex 里被压成一字一行（2026-09-12 云端截图发现）——nowrap 修 */
.oj-assignment-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: var(--space-4); }
.oj-assignment-card { display: flex; flex-direction: column; gap: var(--space-3); }
.oj-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-3); }
.oj-desc { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.oj-facts { display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--space-2); }
.oj-facts div { border-left: 1px solid var(--border-default); padding-left: var(--space-2); }
.oj-problems { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.oj-problem-chip {
  padding: var(--space-1) var(--space-3);
  border: 1px solid var(--border-default);
  font-size: var(--ui-sm-size);
  cursor: pointer;
  color: var(--ink-900);
}
.oj-problem-chip:hover { border-color: var(--ink-900); }
.oj-problem-chip.is-disabled { cursor: not-allowed; color: var(--text-secondary); }
.oj-problem-chip.is-disabled:hover { border-color: var(--border-default); }
@media (max-width: 760px) {
  .oj-assignment-grid { grid-template-columns: 1fr; }
}
</style>
