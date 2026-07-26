<script setup>
import { computed, inject } from 'vue'
import { Network, Quote, ListChecks, History } from 'lucide-vue-next'
import SfxLocalRail from '@/app/ui/SfxLocalRail.vue'

/**
 * 课程知识空间布局（page-design §15.1）。
 * Local Rail：教师 = 结构视图｜原文引用｜候选审核｜版本记录；
 * 学生 = 结构视图｜原文引用（候选审核与版本记录直接隐藏，不留禁用入口）。
 */
const courseContext = inject('courseContext')
const courseId = computed(() => courseContext.courseId.value)
const canEdit = computed(() => Boolean(courseContext.allowed.value['course.edit']))

const railItems = computed(() => {
  const base = `/app/course/${courseId.value}/knowledge`
  const items = [
    { key: 'graph', label: '结构视图', to: `${base}/graph`, icon: Network },
    { key: 'evidence', label: '原文引用', to: `${base}/evidence`, icon: Quote },
  ]
  if (canEdit.value) {
    items.push(
      { key: 'reviews', label: '候选审核', to: `${base}/reviews`, icon: ListChecks },
      { key: 'snapshots', label: '版本记录', to: `${base}/snapshots`, icon: History },
    )
  }
  return items
})
</script>

<template>
  <div class="sfx-knowledge-layout">
    <SfxLocalRail :items="railItems" aria-label="知识空间工作区" storage-key="knowledge" />
    <div class="sfx-knowledge-main">
      <router-view />
    </div>
  </div>
</template>

<style scoped>
.sfx-knowledge-layout {
  display: flex;
  flex: 1;
  min-height: 0;
}

.sfx-knowledge-main {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
</style>
