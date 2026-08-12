<script setup>
import { computed, onMounted, provide, reactive, toRefs } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from 'lucide-vue-next'
import { getCourseAccess, getCourseDetail } from '@/api/courses.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'
import { isCodeSandboxExperimentPlatformEnabled } from '@/app/lib/courseExperimentPlatform.js'

const route = useRoute()
const router = useRouter()
const courseId = computed(() => Number(route.params.courseId))

const state = reactive({
  status: 'loading', // loading | ready | error | notfound
  detail: null,
  access: null,
})

// 课程角色（page-design §1.3：角色属于「用户与课程的关系」）。
// 当前课程详情端点不返回 teacher_id，切片内用全局角色近似：教师/管理员
// 看到教师导航（其「学习」为学生视角预览，§10.3），学生看到学生导航。
const courseRole = computed(() => state.access?.course_role ?? null)
const allowed = computed(() => state.access?.allowed ?? {})
const capabilities = computed(() => state.access?.capabilities ?? {})
// analytics_eligible 来自后端 CourseAccessContext：仅「学生且未 excluded」为 true。
// owner/teacher/teaching_assistant/observer 均为 false（course_access_service.py
// _participation_mode：TEACHER_PREVIEW/STAFF_TEST/OBSERVER → analytics_eligible=False）。
// 子页面据此决定是否加载学生私有认知/推荐，避免教师预览触发 422。
const analyticsEligible = computed(() => Boolean(state.access?.analytics_eligible))

const course = computed(() => state.detail?.course ?? null)

// L2 导航（§10.2/§10.3）：学生 = 概览｜学习｜知识｜实验任务；
// 教师追加 = 建设｜成员｜设置。建设/成员/设置仅对有 course.edit 的角色显示
// （§1.5：完全无权访问的入口直接隐藏）。
const navItems = computed(() => {
  const base = [
    { key: 'overview', label: '概览', to: `/app/course/${courseId.value}/overview`, enabled: true },
    { key: 'learn', label: '学习', to: `/app/course/${courseId.value}/learn`, enabled: true },
    { key: 'analytics', label: '学习分析', to: `/app/course/${courseId.value}/analytics`, enabled: allowed.value['analytics.view_course'] },
    { key: 'knowledge', label: '知识', to: `/app/course/${courseId.value}/knowledge`, enabled: true },
    {
      key: 'experiments',
      label: '实验任务',
      to: `/app/course/${courseId.value}/experiments`,
      enabled: isCodeSandboxExperimentPlatformEnabled(capabilities.value),
    },
    {
      key: 'research',
      label: '科研',
      to: `/app/course/${courseId.value}/research`,
      // Keep the Research workspace discoverable for every active course
      // member. The backend still gates the actual paper search capability.
      enabled: allowed.value['course.view'],
      reason: '当前课程角色无研究检索权限',
    },
  ]
  if (allowed.value['course.edit']) {
    base.push(
      { key: 'build', label: '建设', to: `/app/course/${courseId.value}/build`, enabled: true },
      { key: 'members', label: '成员', to: `/app/course/${courseId.value}/members`, enabled: true },
      { key: 'settings', label: '设置', to: `/app/course/${courseId.value}/settings`, enabled: true },
    )
  }
  // Other unavailable entries retain their disabled explanation. The current
  // experiment implementation is code-sandbox-only, so it must disappear
  // entirely when that platform is not enabled for this course.
  return base.filter((item) => item.key !== 'experiments' || item.enabled)
})

const activeKey = computed(() => {
  if (route.path.endsWith('/learn')) return 'learn'
  if (route.path.includes('/analytics')) return 'analytics'
  if (route.path.includes('/knowledge')) return 'knowledge'
  if (route.path.includes('/visualize')) return 'learn'
  if (route.path.includes('/build')) return 'build'
  if (route.path.includes('/experiments')) return 'experiments'
  if (route.path.includes('/research')) return 'research'
  if (route.path.includes('/members')) return 'members'
  if (route.path.includes('/settings')) return 'settings'
  return 'overview'
})

// 返回按钮目标：建设子树回到「我建设的」，其余子页面回到「我学习的」。
const backTarget = computed(() => {
  if (route.path.includes('/build')) return '/app/courses/building'
  return '/app/courses/learning'
})

async function load() {
  state.status = 'loading'
  try {
    const [detail, access] = await Promise.all([
      getCourseDetail(courseId.value),
      getCourseAccess(courseId.value),
    ])
    state.detail = detail
    state.access = access
    state.status = 'ready'
  } catch (e) {
    state.status = /404|不存在/.test(String(e?.message || '')) ? 'notfound' : 'error'
  }
}

// 通过 provide 向子页面（概览/学习）共享课程上下文，避免重复请求
provide('courseContext', {
  ...toRefs(state),
  courseId,
  course,
  courseRole,
  allowed,
  capabilities,
  analyticsEligible,
  reload: load,
})

onMounted(load)
</script>

<template>
  <div class="sfx-course-layout">
    <div v-if="state.status === 'ready' && course" class="sfx-l2nav">
      <div class="sfx-l2nav-inner">
        <div class="sfx-l2nav-left">
          <button type="button" class="sfx-l2nav-back" aria-label="返回我的课程"
                  @click="router.push(backTarget)">
            <ArrowLeft :size="17" />
          </button>
          <div class="sfx-l2nav-course">
            <span class="sfx-l2nav-title sfx-t-ui">{{ course.title }}</span>
            <SfxBadge :tone="courseRole === 'owner' || courseRole === 'teacher' ? 'ink' : 'green'">
              {{ courseRole === 'owner' ? '课程所有者' : courseRole === 'teacher' ? '教师' : courseRole === 'teaching_assistant' ? '助教' : courseRole === 'observer' ? '观察者' : '学员' }}
            </SfxBadge>
            <SfxBadge v-if="course.status !== 'published'" tone="amber">
              {{ course.status === 'draft' ? '草稿' : course.status }}
            </SfxBadge>
          </div>
        </div>

        <nav class="sfx-l2nav-links" aria-label="课程导航">
          <template v-for="item in navItems" :key="item.key">
            <RouterLink
              v-if="item.enabled"
              :to="item.to"
              class="sfx-l2nav-link"
              :class="{ 'is-active': activeKey === item.key }"
            >{{ item.label }}</RouterLink>
            <span
              v-else
              class="sfx-l2nav-link is-disabled"
              :title="item.reason"
              aria-disabled="true"
            >{{ item.label }}</span>
          </template>
        </nav>
      </div>
    </div>

    <SfxSkeleton v-if="state.status === 'loading'" :lines="4" block />

    <SfxError
      v-else-if="state.status === 'notfound'"
      variant="error"
      title="课程不存在"
      description="该课程可能已被删除，或你访问的课程编号有误。"
      :retryable="false"
    />

    <SfxError
      v-else-if="state.status === 'error'"
      description="课程信息暂时无法读取，请稍后重试。"
      @retry="load"
    />

    <router-view v-else v-slot="{ Component }">
      <Transition name="sfx-page" mode="out-in">
        <component :is="Component" />
      </Transition>
    </router-view>
  </div>
</template>

<style scoped>
.sfx-course-layout {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.sfx-l2nav {
  height: var(--nav-l2-height);
  background: var(--surface-panel);
  border-bottom: 1px solid var(--border-default);
  flex-shrink: 0;
  position: sticky;
  top: 0;
  z-index: 30;
}

.sfx-l2nav-inner {
  height: 100%;
  max-width: var(--content-max-width);
  margin: 0 auto;
  padding: 0 var(--space-6);
  display: flex;
  align-items: center;
  gap: var(--space-6);
}

.sfx-l2nav-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}

.sfx-l2nav-back {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
}

.sfx-l2nav-back:hover {
  background: var(--surface-cool);
  color: var(--ink-700);
}

.sfx-l2nav-course {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.sfx-l2nav-title {
  color: var(--text-primary);
  font-weight: 600;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sfx-l2nav-links {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  height: 100%;
  flex: 1;
  min-width: 0;
  overflow-x: auto;
  scrollbar-width: none;
}

.sfx-l2nav-links::-webkit-scrollbar { display: none; }

.sfx-l2nav-link {
  position: relative;
  display: inline-flex;
  align-items: center;
  height: 100%;
  padding: 0 var(--space-4);
  color: var(--text-secondary);
  font-size: var(--ui-md-size);
  font-weight: var(--ui-md-weight);
}

.sfx-l2nav-link:hover:not(.is-disabled) {
  color: var(--ink-700);
}

.sfx-l2nav-link.is-active {
  color: var(--ink-900);
}

.sfx-l2nav-link.is-active::after {
  content: '';
  position: absolute;
  left: var(--space-4);
  right: var(--space-4);
  bottom: -1px;
  height: 2px;
  background: var(--ink-900);
}

.sfx-l2nav-link.is-disabled {
  color: var(--text-disabled);
  cursor: not-allowed;
}
</style>
