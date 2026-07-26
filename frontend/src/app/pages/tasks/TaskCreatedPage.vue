<script setup>
import SfxPlannedPanel from '@/app/ui/SfxPlannedPanel.vue'

/**
 * 我发起的（page-design §21.2）。
 * GET /tasks?view=created 为 planned 契约：展示用户创建或触发的任务，
 * 例如媒体生成、课程发布、成员同步。
 */
</script>

<template>
  <div class="sfx-page sfx-page--narrow">
    <header class="sfx-page-header">
      <div>
        <h1 class="sfx-t-title1">我发起的</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">你创建或触发的任务</p>
      </div>
    </header>

    <SfxPlannedPanel
      contract-key="tasks"
      title="我发起的任务 · 接口契约已冻结"
      available-note="课程内媒体生成任务已在「课程 → 建设 → 媒体生成」真实展示进度与失败原因。"
    >
      <p class="sfx-t-ui sfx-t-secondary">
        将聚合你触发的任务（§21.2）：媒体生成、课程发布、成员同步等，
        支持取消、重试与确认已读（cancel / retry / acknowledge）。
      </p>
    </SfxPlannedPanel>
  </div>
</template>
