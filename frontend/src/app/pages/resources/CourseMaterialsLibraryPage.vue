<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { BookOpen, FileText } from 'lucide-vue-next'
import { listFacadeCourses } from '@/api/facade.js'
import { listBuildMaterials } from '@/api/course_build.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

const status = ref('loading')
const courses = ref([])
const keyword = ref('')
const router = useRouter()

const visibleCourses = computed(() => {
  const term = keyword.value.trim().toLowerCase()
  if (!term) return courses.value
  return courses.value.filter((course) => String(course.title || '').toLowerCase().includes(term))
})

async function load() {
  status.value = 'loading'
  try {
    const results = await Promise.allSettled([
      listFacadeCourses('building'),
      listFacadeCourses('learning'),
    ])
    if (results.every((result) => result.status === 'rejected')) throw results[0].reason
    const merged = new Map()
    for (const result of results) {
      const items = result.status === 'fulfilled' ? result.value?.items || [] : []
      for (const item of items) {
      if (item?.course_id != null) merged.set(String(item.course_id), { ...item, materials: null })
      }
    }
    const entries = [...merged.values()]
    await Promise.all(entries.map(async (course) => {
      try {
        const data = await listBuildMaterials(course.course_id)
        course.materials = data?.items || []
      } catch {
        // A course may be readable without build permission; keep the card visible.
        course.materials = null
      }
    }))
    courses.value = entries
    status.value = entries.length ? 'ready' : 'empty'
  } catch {
    status.value = 'error'
  }
}

function openCourse(course) {
  router.push(`/app/course/${course.course_id}/build/materials`)
}

onMounted(load)
</script>

<template>
  <div class="sfx-page sfx-page--narrow">
    <header class="sfx-page-header">
      <div>
        <h1 class="sfx-t-title1">课程资料</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">集中查看有权限访问的课程资料，编辑仍在对应课程建设空间完成。</p>
      </div>
      <input v-model="keyword" class="sfx-toolbar-input course-search" placeholder="搜索课程" aria-label="搜索课程" />
    </header>

    <SfxSkeleton v-if="status === 'loading'" :lines="5" block />
    <SfxError v-else-if="status === 'error'" description="课程资料暂时无法读取，请稍后重试。" @retry="load" />
    <SfxEmpty v-else-if="status === 'empty'" title="暂无可访问的课程资料" description="加入课程或创建课程后，资料会显示在这里。">
      <template #icon><FileText :size="28" :stroke-width="1.8" /></template>
    </SfxEmpty>
    <p v-else-if="!visibleCourses.length" class="empty-filter">没有匹配的课程。</p>
    <div v-else class="course-list">
      <article v-for="course in visibleCourses" :key="course.course_id" class="course-card">
        <div class="course-icon"><BookOpen :size="20" /></div>
        <div class="course-main">
          <div class="course-title-row">
            <h2 class="sfx-t-title3">{{ course.title }}</h2>
            <SfxBadge tone="neutral">{{ course.role || '课程成员' }}</SfxBadge>
            <SfxBadge v-if="course.status" tone="ink">{{ course.status }}</SfxBadge>
          </div>
          <p class="sfx-t-ui sfx-t-secondary">{{ course.materials == null ? '当前角色仅可浏览课程入口' : `已关联 ${course.materials.length} 份资料` }}</p>
        </div>
        <SfxButton variant="tertiary" size="sm" @click="openCourse(course)">查看课程资料</SfxButton>
      </article>
    </div>
  </div>
</template>

<style scoped>
.course-search { width: 180px; height: var(--control-height); border: 1px solid var(--border-default); border-radius: var(--radius-md); padding: 0 var(--space-3); }
.course-list { display: flex; flex-direction: column; gap: var(--space-3); }
.course-card { display: flex; align-items: center; gap: var(--space-4); padding: var(--space-5); border: 1px solid var(--border-default); border-radius: var(--radius-lg); background: var(--surface-panel); }
.course-icon { display: grid; place-items: center; width: 40px; height: 40px; border-radius: var(--radius-md); background: var(--ink-100); color: var(--ink-700); flex: 0 0 auto; }
.course-main { flex: 1; min-width: 0; }
.course-title-row { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; }
.course-title-row h2 { margin: 0; }
.empty-filter { padding: var(--space-8); text-align: center; color: var(--text-secondary); }
@media (max-width: 640px) { .sfx-page-header { gap: var(--space-3); align-items: stretch; } .course-search { width: 100%; } .course-card { align-items: flex-start; flex-wrap: wrap; } }
</style>
