<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft, Check, Copy, Languages, PanelRightClose, PanelRightOpen,
} from 'lucide-vue-next'
import { listExperimentCourses } from '@/api/labs.js'
import { getOJProblem, listOJProblems, listOJSubmissions } from '@/api/oj.js'
import { getCourseCapabilities } from '@/api/course_access.js'
import { getSandboxHealth, getSandboxLanguages } from '@/api/sandbox.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'
import CodeWorkbench from '@/components/codebench/CodeWorkbench.vue'
import { renderContent } from '@/utils/markdownRenderer.js'
import {
  buildProblemNoIndex,
  difficultyMeta,
  formatMemoryLimit,
  formatPassRate,
  formatTimeLimit,
} from './ojTheme.js'

/**
 * OJ 题目详情（复刻参考截图的详情页）。
 *
 * 布局：左 = 面包屑 / 题号标题 / 限制行 / 工具条 / 题面 / 输入输出样例；
 *       右 = CodeWorkbench（variant='oj'，单列）。
 *
 * ⚠️ 旧实现把题面渲染了两遍 —— 页面自己的左栏 + 工作台内置的左栏各一份。
 * 现在题面归页面所有，工作台传 hideProblemPanel 关闭内置左栏。
 *
 * ⚠️ 课程必须继承来源页（`?course=`）：学生可能有多门沙箱课，
 * 固定取 courses[0] 会导致「题库里有题、点进去却 404」（2026-09-12 线上实测）。
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
const problemNo = ref(String(route.query.no || ''))
const copiedKey = ref('')
/** 退出 IDE 模式：题面全宽阅读（截图工具条上的第三个入口）。 */
const ideHidden = ref(false)
// 是否学生身份：非学生（教师/助教/预览）只给「自测」，正式提交隐藏 ——
// 后端同样会 403 拦正式 attempt（PREVIEW_CANNOT_SUBMIT_FORMAL），这里是 UX 层。
const isStudent = ref(true)

const workbenchRef = ref(null)

const timeLimit = computed(() => formatTimeLimit(problem.value?.limits?.cpu_time_limit))
const memoryLimit = computed(() => formatMemoryLimit(problem.value?.limits?.memory_limit))
const difficulty = computed(() => difficultyMeta(problem.value?.difficulty))

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
  const fromQuery = String(route.query.course || '')
  courseId.value = (fromQuery && courses.value.some((c) => String(c.course_id) === fromQuery))
    ? fromQuery
    : (courses.value[0] ? String(courses.value[0].course_id) : '')
}

/** 题号：由未筛选的课程目录派生，与列表页同一套口径（ojTheme.buildProblemNoIndex）。 */
async function loadProblemNo() {
  try {
    const catalog = await listOJProblems(courseId.value, { page: 1, page_size: 100 })
    const items = Array.isArray(catalog?.items) ? catalog.items : []
    problemNo.value = buildProblemNoIndex(items).get(experimentId.value) || problemNo.value || '—'
  } catch {
    // 题号只是展示信息，取不到就用来源页带来的值，不因此把整页判失败
    if (!problemNo.value) problemNo.value = '—'
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
    const subs = await listOJSubmissions(courseId.value, {
      experiment_id: experimentId.value,
      limit: 5,
    }).catch(() => null)
    mySubmissions.value = Array.isArray(subs?.items) ? subs.items : []
    state.value = 'ready'
    await loadProblemNo()
  } catch (caught) {
    const status = caught?.response?.status
    error.value = status === 404 ? '题目不存在或未发布' : (caught?.message || '题目加载失败')
    state.value = 'error'
  }
}

async function writeClipboard(text, key) {
  try {
    await navigator.clipboard.writeText(String(text ?? ''))
  } catch {
    return false
  }
  copiedKey.value = key
  window.setTimeout(() => { if (copiedKey.value === key) copiedKey.value = '' }, 1800)
  return true
}

function copyMarkdown() {
  return writeClipboard(problem.value?.description || '', 'markdown')
}

function copySample(text, idx) {
  return writeClipboard(text, `sample-${idx}`)
}

/** 样例「运行」：把样例输入灌进工作台的自测标准输入，然后跑。 */
function runSample(sample) {
  const workbench = workbenchRef.value
  if (!workbench) return
  workbench.setStdin(sample?.input ?? '')
  if (!String(workbench.getCode?.() || '').trim()) {
    // 还没写代码：只把输入填好并亮出输入页签，别静默跑一个空程序
    workbench.setActiveTab('input')
    return
  }
  workbench.setActiveTab('output')
  workbench.run()
}

function statusLabel(value) {
  return { solved: '已通过', attempted: '尝试过', not_attempted: '未尝试' }[value] || value
}

function statusTone(value) {
  return { solved: 'green', attempted: 'amber', not_attempted: 'ink' }[value] || 'ink'
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
  <div class="sfx-page oj-detail">
    <SfxSkeleton v-if="state === 'loading'" :lines="6" block />
    <SfxError v-else-if="state === 'error'" :description="error" @retry="load" />
    <SfxEmpty v-else-if="state === 'empty'" title="未找到题目" description="题目可能未发布或已下架。" />

    <template v-else>
      <div class="oj-detail-grid" :class="{ 'is-ide-hidden': ideHidden }">
        <!-- ══ 左：题面 ══ -->
        <section class="oj-statement">
          <nav class="oj-crumb" aria-label="面包屑">
            <span
              role="link"
              tabindex="0"
              class="oj-crumb-link"
              @click="backToBank"
              @keyup.enter="backToBank"
            >题目列表</span>
            <span class="oj-crumb-sep">/</span>
            <span class="oj-crumb-current">{{ problemNo }}</span>
          </nav>

          <h1 class="oj-statement-title">
            <span class="oj-statement-no">{{ problemNo }}</span>
            {{ problem.title }}
          </h1>

          <div class="oj-limits">
            <span v-if="timeLimit">时间限制: {{ timeLimit }}</span>
            <span v-if="memoryLimit">内存限制: {{ memoryLimit }}</span>
            <span
              class="oj-difficulty"
              :style="{ background: difficulty.color }"
              :title="`本系统难度：${difficulty.tier}`"
            >{{ difficulty.label }}</span>
            <span v-for="tag in problem.tags || []" :key="tag" class="oj-inline-tag">{{ tag }}</span>
          </div>

          <div class="oj-statement-tools">
            <span
              role="button"
              tabindex="0"
              class="oj-tool"
              @click="copyMarkdown"
              @keyup.enter="copyMarkdown"
            >
              <component :is="copiedKey === 'markdown' ? Check : Copy" :size="14" />
              {{ copiedKey === 'markdown' ? '已复制' : '复制 Markdown' }}
            </span>
            <span class="oj-tool is-static" title="当前题目只提供中文题面">
              <Languages :size="14" />
              中文
            </span>
            <span
              role="button"
              tabindex="0"
              class="oj-tool"
              @click="ideHidden = !ideHidden"
              @keyup.enter="ideHidden = !ideHidden"
            >
              <component :is="ideHidden ? PanelRightOpen : PanelRightClose" :size="14" />
              {{ ideHidden ? '进入 IDE 模式' : '退出 IDE 模式' }}
            </span>
            <SfxBadge
              v-if="problem.my_status"
              :tone="problem.my_status === 'solved' ? 'green' : 'ink'"
            >{{ statusLabel(problem.my_status) }}</SfxBadge>
            <SfxBadge v-if="activityId" tone="amber">作业作答 · 计入活动成绩</SfxBadge>
            <SfxBadge v-if="!isStudent" tone="ink">预览模式 · 正式提交仅学生可用</SfxBadge>
          </div>

          <!-- 题面是 markdown（教师出题面板以 md 书写）——必须渲染，不能源文本直出 -->
          <div
            class="oj-statement-body"
            v-html="renderContent(problem.description) || '<p>暂无题面描述。</p>'"
          ></div>

          <div v-if="problem.samples?.length" class="oj-samples">
            <div v-for="(sample, idx) in problem.samples" :key="idx" class="oj-sample">
              <div class="oj-sample-col">
                <div class="oj-sample-head">
                  <span class="oj-sample-name">输入 #{{ idx + 1 }}</span>
                  <span class="oj-sample-tools">
                    <span role="button" tabindex="0" class="oj-mini" @click="runSample(sample)" @keyup.enter="runSample(sample)">运行</span>
                    <span role="button" tabindex="0" class="oj-mini" @click="copySample(sample.input, `in-${idx}`)" @keyup.enter="copySample(sample.input, `in-${idx}`)">
                      {{ copiedKey === `in-${idx}` ? '已复制' : '复制' }}
                    </span>
                  </span>
                </div>
                <pre class="oj-sample-pre">{{ sample.input }}</pre>
              </div>
              <div class="oj-sample-col">
                <div class="oj-sample-head">
                  <span class="oj-sample-name">输出 #{{ idx + 1 }}</span>
                  <span class="oj-sample-tools">
                    <!-- 输出块不设"运行"：runSample 灌的是输入，放在输出块是重复控件 -->
                    <span role="button" tabindex="0" class="oj-mini" @click="copySample(sample.output, `out-${idx}`)" @keyup.enter="copySample(sample.output, `out-${idx}`)">
                      {{ copiedKey === `out-${idx}` ? '已复制' : '复制' }}
                    </span>
                  </span>
                </div>
                <pre class="oj-sample-pre">{{ sample.output }}</pre>
              </div>
            </div>
          </div>

          <div class="oj-mine">
            <h2 class="oj-section-title">我的作答</h2>
            <p class="oj-mine-line">
              <SfxBadge :tone="statusTone(problem.my_status)">{{ statusLabel(problem.my_status) }}</SfxBadge>
              <span v-if="problem.my_best_score !== null && problem.my_best_score !== undefined">
                最好得分 {{ Math.round(problem.my_best_score * 1000) / 10 }} 分
              </span>
              <span v-if="problem.stats">
                全班通过率 {{ formatPassRate(problem.stats.pass_rate) || '—' }}
                · {{ problem.stats.attempt_total }} 次提交
              </span>
            </p>
            <div v-if="mySubmissions.length" class="oj-mine-subs">
              <div v-for="sub in mySubmissions" :key="sub.run_id" class="oj-mine-sub">
                <SfxBadge :tone="sub.outcome === 'accepted' ? 'green' : 'amber'">{{ formatOutcome(sub.outcome) }}</SfxBadge>
                <span class="sfx-t-caption sfx-t-secondary">
                  {{ sub.passed_count }}/{{ sub.total_count }} 用例 ·
                  {{ sub.cpu_time_ms === null || sub.cpu_time_ms === undefined ? '—' : `${sub.cpu_time_ms} ms` }}
                </span>
              </div>
            </div>
          </div>
        </section>

        <!-- ══ 右：IDE ══ -->
        <section v-if="!ideHidden" class="oj-ide">
          <CodeWorkbench
            v-if="workbenchExperiment && languages.length"
            ref="workbenchRef"
            variant="oj"
            hide-problem-panel
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
/* 页面容器收窄：详情页是"工作台"，左右两栏铺满更接近 IDE 的观感 */
.oj-detail { max-width: 1600px; }

.oj-detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
  gap: var(--space-5);
  align-items: start;
}
/* 退出 IDE 模式 → 题面独占整行并限宽，长行不超过易读宽度 */
.oj-detail-grid.is-ide-hidden { grid-template-columns: minmax(0, 1fr); }
.oj-detail-grid.is-ide-hidden .oj-statement { max-width: 860px; }

/* ── 面包屑 ── */
.oj-crumb {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--ui-sm-size);
  color: var(--text-secondary);
  margin-bottom: var(--space-3);
}
.oj-crumb-link { cursor: pointer; color: var(--text-link); }
.oj-crumb-link:hover { text-decoration: underline; }
.oj-crumb-sep { color: var(--text-disabled); }
.oj-crumb-current { color: var(--text-secondary); font-family: var(--font-mono); }

.oj-statement-title {
  font-size: 26px;
  line-height: 34px;
  font-weight: var(--title-1-weight);
  color: var(--text-primary);
  margin: 0 0 var(--space-2);
  overflow-wrap: anywhere;
}
.oj-statement-no { color: var(--text-muted); font-family: var(--font-mono); font-weight: 500; }

.oj-limits {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-3);
  font-size: var(--ui-sm-size);
  color: var(--text-secondary);
  margin-bottom: var(--space-3);
}
.oj-difficulty {
  display: inline-block;
  padding: 1px var(--space-2);
  border-radius: var(--radius-xs);
  font-size: 12px;
  line-height: 18px;
  color: #fff;
}
.oj-inline-tag {
  padding: 1px var(--space-2);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-xs);
  font-size: var(--ui-sm-size);
  color: var(--text-secondary);
}

/* ── 工具条（截图：复制 Markdown / 中文 / 退出 IDE 模式） ── */
.oj-statement-tools {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
  padding: var(--space-2) 0;
  border-top: 1px solid var(--border-subtle);
  border-bottom: 1px solid var(--border-subtle);
  margin-bottom: var(--space-5);
}
.oj-tool {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: 3px var(--space-2);
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  font-size: var(--ui-sm-size);
  color: var(--text-link);
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
}
.oj-tool:hover { background: var(--ink-100); }
.oj-tool.is-static { color: var(--text-secondary); cursor: default; }
.oj-tool.is-static:hover { background: transparent; }

/* ── 题面正文 ── */
.oj-statement-body { font-size: var(--body-md-size); line-height: 1.75; overflow-wrap: anywhere; }
.oj-statement-body :deep(h1),
.oj-statement-body :deep(h2),
.oj-statement-body :deep(h3) {
  margin: var(--space-6) 0 var(--space-3);
  font-size: 18px;
  line-height: 26px;
  font-weight: var(--title-3-weight);
  color: var(--text-primary);
}
.oj-statement-body :deep(h1:first-child),
.oj-statement-body :deep(h2:first-child),
.oj-statement-body :deep(h3:first-child) { margin-top: 0; }
.oj-statement-body :deep(p) { margin: 0 0 var(--space-3); }
.oj-statement-body :deep(ul),
.oj-statement-body :deep(ol) { margin: 0 0 var(--space-3); padding-left: var(--space-6); }
.oj-statement-body :deep(li) { margin: var(--space-1) 0; }
.oj-statement-body :deep(pre) {
  margin: 0 0 var(--space-3);
  padding: var(--space-3);
  background: var(--surface-soft);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  overflow-x: auto;
  font-family: var(--font-mono);
  font-size: var(--ui-sm-size);
  line-height: 1.65;
}
.oj-statement-body :deep(code) { font-family: var(--font-mono); font-size: 0.94em; }
.oj-statement-body :deep(blockquote) {
  margin: 0 0 var(--space-3);
  padding: var(--space-2) var(--space-4);
  border-left: 3px solid var(--ink-300);
  background: var(--surface-cool);
  color: var(--text-secondary);
}
.oj-statement-body :deep(table) { width: 100%; border-collapse: collapse; margin-bottom: var(--space-3); }
.oj-statement-body :deep(th),
.oj-statement-body :deep(td) {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border-default);
  text-align: left;
}

/* ── 输入输出样例（截图：左右两栏，各带 运行 / 复制） ── */
.oj-samples { display: flex; flex-direction: column; gap: var(--space-5); margin-top: var(--space-6); }
.oj-sample { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: var(--space-4); }
.oj-sample-col { min-width: 0; }
.oj-sample-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  margin-bottom: var(--space-1);
}
.oj-sample-name { font-size: var(--ui-md-size); font-weight: var(--ui-md-weight); color: var(--text-primary); }
.oj-sample-tools { display: inline-flex; align-items: center; gap: var(--space-1); }
.oj-mini {
  padding: 1px var(--space-2);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-xs);
  background: var(--surface-panel);
  font-size: var(--ui-sm-size);
  color: var(--text-link);
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
}
.oj-mini:hover { border-color: var(--border-strong); background: var(--surface-cool); }
.oj-sample-pre {
  margin: 0;
  padding: var(--space-3);
  min-height: 96px;
  background: var(--surface-cool);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: var(--ui-sm-size);
  line-height: 1.6;
  color: var(--text-primary);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

/* ── 我的作答 ── */
.oj-mine { margin-top: var(--space-8); padding-top: var(--space-4); border-top: 1px solid var(--border-subtle); }
.oj-section-title {
  font-size: var(--ui-sm-size);
  font-weight: var(--ui-md-weight);
  color: var(--text-secondary);
  letter-spacing: 0.08em;
  margin-bottom: var(--space-3);
}
.oj-mine-line {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-3);
  margin: 0;
  font-size: var(--ui-sm-size);
  color: var(--text-secondary);
}
.oj-mine-subs { display: flex; flex-direction: column; gap: var(--space-2); margin-top: var(--space-3); }
.oj-mine-sub { display: flex; align-items: center; gap: var(--space-3); }

/* ── 右栏 IDE：粘住视口，左栏长题面滚动时编辑器不跟着跑 ──
   ⚠️ 不用「根 height:100% + overflow:hidden」那种做法 —— 那个组合会让超一屏内容
   被永久裁掉（本项目在实验任务页踩过 P0）。这里只给右栏定高，页面照常滚动。 */
.oj-ide {
  position: sticky;
  top: calc(var(--nav-l1-height) + var(--nav-l2-height) + var(--space-4));
  height: calc(100vh - var(--nav-l1-height) - var(--nav-l2-height) - var(--space-10));
  min-height: 440px;
  min-width: 0;
}

@media (max-width: 1280px) {
  .oj-detail-grid { grid-template-columns: minmax(0, 1fr); }
  .oj-ide { position: static; height: 620px; }
}

@media (max-width: 760px) {
  .oj-statement-title { font-size: 22px; line-height: 30px; }
  .oj-sample { grid-template-columns: minmax(0, 1fr); }
  .oj-ide { height: 520px; }
}
</style>
