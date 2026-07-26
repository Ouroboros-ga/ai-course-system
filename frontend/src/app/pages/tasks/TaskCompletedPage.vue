<script setup>
import SfxPlannedPanel from '@/app/ui/SfxPlannedPanel.vue'

/**
 * 已完成（page-design §21.4）。
 * GET /tasks?view=completed 为 planned 契约：保留可追溯历史，
 * 不与当前待办混合。
 */
</script>

<template>
  <div class="sfx-page sfx-page--narrow">
    <header class="sfx-page-header">
      <div>
        <h1 class="sfx-t-title1">已完成</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">可追溯的任务历史</p>
      </div>
    </header>

    <SfxPlannedPanel
      contract-key="tasks"
      title="已完成任务 · 接口契约已冻结"
    >
      <p class="sfx-t-ui sfx-t-secondary">
        保留可追溯历史，不与当前待办混合（§21.4）；
        每条记录保留任务类型、完成时间、结果与关联资源入口。
      </p>
    </SfxPlannedPanel>
  </div>
</template>
