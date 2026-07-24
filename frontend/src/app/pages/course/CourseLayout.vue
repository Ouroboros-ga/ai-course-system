<script setup>
import { computed, onMounted, provide, reactive, toRefs } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from 'lucide-vue-next'
import { getCourseAccess, getCourseDetail } from '@/api/courses.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

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

const course = computed(() => state.detail?.course ?? null)

// L2 导航（§10.2/§10.3）。本切片只有 概览/学习 是真实页面；其余按
// §1.5「暂时不可用但用户需要知道的可以禁用并说明」渲染为禁用态。
const navItems = computed(() => {
  const base = [
    { key: 'overview', label: '概览', to: `/app/course/${courseId.value}/overview`, enabled: true },
    { key: 'learn', label: '学习', to: `/app/course/${courseId.value}/learn`, enabled: true },
    { key: 'knowledge', label: '知识', enabled: false, reason: '知识空间将在后续切片上线' },
    { key: 'experiments', label: '实验任务', enabled: false, reason: '课程实验将在后续切片上线' },
  ]
  if (allowed.value['course.edit']) {
    base.push(
      { key: 'build', label: '建设', enabled: false, reason: '课程建设将在后续切片上线' },
      { key: 'members', label: '成员', enabled: false, reason: '成员管理将在后续切片上线' },
      { key: 'settings', label: '设置', enabled: false, reason: '课程设置将在后续切片上线' },
    )
  }
  return base
})

const activeKey = computed(() => {
  if (route.path.endsWith('/learn')) return 'learn'
  return 'overview'
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
                  @click="router.push('/app/courses/learning')">
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

    <router-view v-else />
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
}

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
