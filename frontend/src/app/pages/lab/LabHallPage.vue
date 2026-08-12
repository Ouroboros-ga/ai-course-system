<script setup>
import { FlaskConical } from 'lucide-vue-next'
import { useRouter } from 'vue-router'
import SfxButton from '@/app/ui/SfxButton.vue'

const router = useRouter()
</script>

<template>
  <div class="sfx-page sfx-page--narrow">
    <header class="sfx-page-header"><div><h1 class="sfx-t-title1">实验大厅</h1><p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">实验室是课程编程实验的发现与结果投影，不提供独立创建或加入流程。</p></div></header>
    <section class="sfx-panel sfx-hall"><FlaskConical :size="28" /><div><h2 class="sfx-panel-title">从课程进入实验</h2><p class="sfx-t-ui sfx-t-secondary">已发布实验会在「课程任务」中按课程显示；开始、提交和异步评测都发生在课程实验页。</p><SfxButton variant="primary" @click="router.push('/app/lab/course-tasks')">查看课程任务</SfxButton></div></section>
  </div>
</template>

<style scoped>.sfx-hall{display:flex;align-items:flex-start;gap:var(--space-3)}.sfx-hall div{display:flex;flex-direction:column;align-items:flex-start;gap:var(--space-2)}</style>
