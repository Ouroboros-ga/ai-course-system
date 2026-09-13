<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from 'lucide-vue-next'
import { listExperimentCourses } from '@/api/labs.js'
import { getOJProblem, listOJSubmissions } from '@/api/oj.js'
import { getCourseCapabilities } from '@/api/course_access.js'
import { getSandboxHealth, getSandboxLanguages } from '@/api/sandbox.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'
import CodeWorkbench from '@/components/codebench/CodeWorkbench.vue'
import { renderContent } from '@/utils/markdownRenderer.js'

/**
 * OJ 题目详情（PR-10，设计稿②）。
 * 左：题面（描述 / 标签 / 限制 / 我的作答摘要）；右：CodeWorkbench
 * （复用既有 CodeMirror 判题链：运行 / 提交 / 诊断 / 讲解，不重复造）。
 * 详情不含 testcase —— 学生侧评测解读走 diagnosis 通道。
 */
const route = useRoute()
const router = useRouter()

const experimentId = computed(() => String(route.params.experimentId || ''))
// 活动归属：作业页带 ?activity= 进来；直达题库则为空（自由练习）。
const activityId = computed(() => String(route.query.activity || ''))
const courses = ref([])
const courseId = ref('')
const state = ref('loading')
const error = ref('')
const problem = ref(null)
const languages = ref([])
const mySubmissions = ref([])
// 是否学生身份：非学生（教师/助教/预览）只给"运行测试"，正式提交隐藏 ——
// 后端同样会 403 拦正式 attempt（PREVIEW_CANNOT_SUBMIT_FORMAL），这里是 UX 层。
// 身份拿不到时默认按学生渲染（后端是最终 enforcement）。
const isStudent = ref(true)

const workbenchExperiment = computed(() => {
  if (!problem.value) return null
  return {
    experiment_id: problem.value.experiment_id,
    title: problem.value.title,
    description: problem.value.description,
    starter_code: problem.value.starter_code || {},
    language_whitelist: problem.value.language_whitelist || [],
    default_version_id: null,
  }
})

async function loadCourses() {
  courses.value = await listExperimentCourses()
  // ⚠️ 课程必须继承来源页（题库/活动作业）选中的那门 —— 学生可能有多门
  // 沙箱课，固定取 courses[0] 会导致「题库里有题、点进去却 404」
  // （2026-09-12 用户实测：/app/oj/problems/e 点不进去）。
  const fromQuery = String(route.query.course || '')
  if (fromQuery && courses.value.some((c) => String(c.course_id) === fromQuery)) {
    courseId.value = fromQuery
  } else {
    courseId.value = courses.value[0] ? String(courses.value[0].course_id) : ''
  }
}

async function load() {
  if (!courseId.value || !experimentId.value) {
    state.value = 'empty'
    return
  }
  state.value = 'loading'
  error.value = ''
  try {
    const [detail, health, supported, access] = await Promise.all([
      getOJProblem(courseId.value, experimentId.value),
      getSandboxHealth().catch(() => null),
      getSandboxLanguages().catch(() => null),
      getCourseCapabilities(courseId.value).catch(() => null),
    ])
    problem.value = detail
    isStudent.value = (access?.course_role || 'student') === 'student'
    languages.value = Array.isArray(supported?.languages) ? supported.languages : []
    // 我的最近提交（用于摘要；评测解读由 Workbench 内的 diagnosis 通道负责）
    const subs = await listOJSubmissions(courseId.value, {
      experiment_id: experimentId.value,
      limit: 5,
    }).catch(() => null)
    mySubmissions.value = Array.isArray(subs?.items) ? subs.items : []
    state.value = 'ready'
  } catch (caught) {
    const status = caught?.response?.status
    if (status === 404) {
      error.value = '题目不存在或未发布'
    } else {
      error.value = caught?.message || '题目加载失败'
    }
    state.value = 'error'
  }
}

function statusLabel(value) {
  return { solved: '已通过', attempted: '尝试过', not_attempted: '未尝试' }[value] || value
}

function statusTone(value) {
  return { solved: 'green', attempted: 'amber', not_attempted: 'ink' }[value] || 'ink'
}

function difficultyLabel(value) {
  return { easy: '简单', medium: '中等', hard: '困难' }[value] || value || '—'
}

function formatRate(rate) {
  return rate === null || rate === undefined ? '—' : `${Math.round(rate * 1000) / 10}%`
}

function formatOutcome(value) {
  return {
    accepted: '通过', wrong_answer: '答案错误', runtime_error: '运行错误',
    time_limit_exceeded: '超时', compile_error: '编译错误', pending: '评测中',
  }[value] || value
}

function backToBank() {
  router.push('/app/oj/bank')
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
    <header class="oj-detail-header">
      <span
        role="button"
        tabindex="0"
        class="oj-back"
        @click="backToBank"
        @keyup.enter="backToBank"
      ><ArrowLeft :size="16" /> 返回题库</span>
      <SfxBadge
        v-if="problem"
        :tone="problem.my_status === 'solved' ? 'green' : 'ink'"
      >{{ statusLabel(problem.my_status) }}</SfxBadge>
      <SfxBadge v-if="activityId" tone="amber">作业作答 · 提交计入活动成绩</SfxBadge>
      <SfxBadge v-if="!isStudent" tone="ink">预览模式 · 可运行测试，正式提交仅学生可用</SfxBadge>
    </header>

    <SfxSkeleton v-if="state === 'loading'" :lines="6" block />
    <SfxError v-else-if="state === 'error'" :description="error" @retry="load" />
    <SfxEmpty v-else-if="state === 'empty'" title="未找到题目" description="题目可能未发布或已下架。" />

    <template v-else>
      <header class="sfx-page-header">
        <div>
          <h1 class="sfx-t-title1">{{ problem.title }}</h1>
          <div class="oj-meta">
            <SfxBadge
              :tone="{ easy: 'green', medium: 'amber', hard: 'red' }[problem.difficulty] || 'ink'"
            >{{ difficultyLabel(problem.difficulty) }}</SfxBadge>
            <span v-for="tag in problem.tags" :key="tag" class="oj-tag">{{ tag }}</span>
            <span v-if="problem.stats" class="sfx-t-caption sfx-t-secondary">
              全班通过率 {{ formatRate(problem.stats.pass_rate) }} · {{ problem.stats.attempt_total }} 次提交
            </span>
          </div>
        </div>
      </header>

      <div class="oj-detail-grid">
        <section class="sfx-panel oj-problem-panel">
          <div class="oj-limits sfx-t-caption sfx-t-secondary" v-if="problem.limits">
            <span v-if="problem.limits.cpu_time_limit">时间 {{ problem.limits.cpu_time_limit }}s</span>
            <span v-if="problem.limits.memory_limit">内存 {{ problem.limits.memory_limit }} KB</span>
            <span v-if="problem.limits.wall_time_limit">总时限 {{ problem.limits.wall_time_limit }}s</span>
            <span v-if="problem.language_whitelist?.length">
              语言 {{ problem.language_whitelist.join(' / ') }}
            </span>
          </div>
          <!-- 题面是 markdown（教师出题面板以 md 书写）——必须渲染，不能源文本直出 -->
          <div
            class="oj-description"
            v-html="renderContent(problem.description) || '暂无题面描述。'"
          ></div>

          <div v-if="problem.samples?.length" class="oj-samples">
            <h2 class="oj-section-title">样例</h2>
            <div v-for="(sample, idx) in problem.samples" :key="idx" class="oj-sample">
              <p class="sfx-t-caption sfx-t-secondary">
                {{ sample.name || `样例 ${idx + 1}` }}
              </p>
              <div class="oj-sample-io">
                <div class="oj-sample-block">
                  <span class="sfx-t-caption sfx-t-secondary">输入</span>
                  <pre>{{ sample.input }}</pre>
                </div>
                <div class="oj-sample-block">
                  <span class="sfx-t-caption sfx-t-secondary">输出</span>
                  <pre>{{ sample.output }}</pre>
                </div>
              </div>
            </div>
          </div>

          <div class="oj-mine sfx-t-ui">
            <h2 class="oj-section-title">我的作答</h2>
            <p>
              状态：<SfxBadge :tone="statusTone(problem.my_status)">
                {{ statusLabel(problem.my_status) }}
              </SfxBadge>
              <template v-if="problem.my_best_score !== null && problem.my_best_score !== undefined">
                最好得分 {{ Math.round(problem.my_best_score * 1000) / 10 }} 分
              </template>
            </p>
            <div v-if="mySubmissions.length" class="oj-mine-subs">
              <div
                v-for="sub in mySubmissions"
                :key="sub.run_id"
                class="oj-mine-sub"
              >
                <SfxBadge
                  :tone="sub.outcome === 'accepted' ? 'green' : 'amber'"
                >{{ formatOutcome(sub.outcome) }}</SfxBadge>
                <span class="sfx-t-caption sfx-t-secondary">
                  {{ sub.passed_count }}/{{ sub.total_count }} 用例 ·
                  {{ sub.cpu_time_ms === null ? '—' : `${sub.cpu_time_ms} ms` }}
                </span>
              </div>
            </div>
          </div>
        </section>

        <section class="oj-workbench">
          <CodeWorkbench
            v-if="workbenchExperiment && languages.length"
            :experiment="workbenchExperiment"
            :course-id="courseId"
            :languages="languages"
            :activity-id="activityId"
            :mode="isStudent ? 'both' : 'free'"
            @submit-complete="load"
          />
          <SfxEmpty
            v-else
            title="判题环境未就绪"
            description="代码沙箱语言列表加载失败，答题区暂不可用。"
          >
            <SfxButton variant="secondary" size="sm" @click="load">重试</SfxButton>
          </SfxEmpty>
        </section>
      </div>
    </template>
  </div>
</template>

<style scoped>
.oj-detail-header {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  margin-bottom: var(--space-2);
}
.oj-back {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--text-secondary);
  cursor: pointer;
  font-size: var(--ui-sm-size);
}
.oj-back:hover { color: var(--ink-900); }
.oj-meta { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); margin-top: var(--space-2); }
.oj-tag {
  padding: 1px var(--space-2);
  border: 1px solid var(--border-default);
  font-size: var(--ui-sm-size);
  color: var(--text-secondary);
}
.oj-detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
  gap: var(--space-5);
  align-items: start;
  margin-top: var(--space-4);
}
.oj-problem-panel { display: flex; flex-direction: column; gap: var(--space-4); }
.oj-limits { display: flex; flex-wrap: wrap; gap: var(--space-4); }
.oj-description { font-size: var(--ui-md-size); line-height: 1.7; overflow-wrap: anywhere; }
/* markdown 渲染产物的标题/代码块间距（无全局 markdown 皮肤，就地补最小样式） */
.oj-description :deep(h1),
.oj-description :deep(h2),
.oj-description :deep(h3) { margin: var(--space-4) 0 var(--space-2); color: var(--ink-900); }
.oj-description :deep(pre) {
  background: var(--surface-subtle, rgba(0, 0, 0, 0.03));
  padding: var(--space-3); overflow-x: auto;
  font-family: var(--font-mono, monospace); font-size: var(--ui-sm-size);
}
.oj-description :deep(code) { font-family: var(--font-mono, monospace); }
.oj-section-title {
  font-size: var(--ui-sm-size);
  font-weight: var(--ui-md-weight);
  color: var(--text-secondary);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: var(--space-2);
}
.oj-mine-subs { display: flex; flex-direction: column; gap: var(--space-2); margin-top: var(--space-2); }
.oj-samples { display: flex; flex-direction: column; gap: var(--space-3); }
.oj-sample-io { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-3); }
.oj-sample-block { display: flex; flex-direction: column; gap: var(--space-1); }
.oj-sample-block pre {
  background: var(--surface-subtle, rgba(0, 0, 0, 0.03));
  padding: var(--space-2) var(--space-3); margin: 0;
  font-family: var(--font-mono, monospace); font-size: var(--ui-sm-size);
  white-space: pre-wrap; overflow-wrap: anywhere;
}
.oj-mine-sub { display: flex; align-items: center; gap: var(--space-3); }
.oj-workbench { min-width: 0; }
@media (max-width: 1024px) {
  .oj-detail-grid { grid-template-columns: 1fr; }
}
</style>
