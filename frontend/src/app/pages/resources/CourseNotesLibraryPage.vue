<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { BookOpen, StickyNote } from 'lucide-vue-next'
import { listNoteSummaries } from '@/api/note.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

/**
 * 资源库「课程笔记」课程列表（page-design §20）。
 * 以课程为单位聚合当前学生自己保存的笔记：列出有笔记的课程，
 * 点进课程后查看该课程下的全部笔记。不设全局一级菜单。
 */
const status = ref('loading')
const items = ref([])
const router = useRouter()

function formatDate(iso) {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return ''
  }
}

async function load() {
  status.value = 'loading'
  try {
    const data = await listNoteSummaries()
    items.value = data?.items ?? []
    status.value = items.value.length ? 'ready' : 'empty'
  } catch {
    status.value = 'error'
  }
}

function openCourseNotes(course) {
  router.push({ path: `/app/resources/notes/${course.course_id}`, query: { title: course.course_title } })
}

onMounted(load)
</script>

<template>
  <div class="sfx-page sfx-page--narrow">
    <header class="sfx-page-header">
      <div>
        <h1 class="sfx-t-title1">课程笔记</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">以课程为单位查看自己保存的笔记，点开课程即可回顾。</p>
      </div>
    </header>

    <SfxSkeleton v-if="status === 'loading'" :lines="5" block />
    <SfxError v-else-if="status === 'error'" description="课程笔记暂时无法读取，请稍后重试。" @retry="load" />
    <SfxEmpty v-else-if="status === 'empty'" title="还没有课程笔记" description="在学习页的「做笔记」中记录理解与问题后，会按课程汇总到这里。">
      <template #icon><StickyNote :size="28" :stroke-width="1.8" /></template>
    </SfxEmpty>

    <div v-else class="course-list">
      <article v-for="course in items" :key="course.course_id" class="course-card">
        <div class="course-icon"><BookOpen :size="20" /></div>
        <div class="course-main">
          <div class="course-title-row">
            <h2 class="sfx-t-title3">{{ course.course_title }}</h2>
            <SfxBadge tone="neutral">{{ course.note_count }} 条笔记</SfxBadge>
          </div>
          <p class="sfx-t-ui sfx-t-secondary">{{ course.last_updated_at ? `最近更新 ${formatDate(course.last_updated_at)}` : '' }}</p>
        </div>
        <SfxButton variant="tertiary" size="sm" @click="openCourseNotes(course)">查看笔记</SfxButton>
      </article>
    </div>
  </div>
</template>

<style scoped>
.course-list { display: flex; flex-direction: column; gap: var(--space-3); }
.course-card { display: flex; align-items: center; gap: var(--space-4); padding: var(--space-5); border: 1px solid var(--border-default); border-radius: var(--radius-lg); background: var(--surface-panel); }
.course-icon { display: grid; place-items: center; width: 40px; height: 40px; border-radius: var(--radius-md); background: var(--ink-100); color: var(--ink-700); flex: 0 0 auto; }
.course-main { flex: 1; min-width: 0; }
.course-title-row { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; }
.course-title-row h2 { margin: 0; }
@media (max-width: 640px) { .course-card { align-items: flex-start; flex-wrap: wrap; } }
</style>
