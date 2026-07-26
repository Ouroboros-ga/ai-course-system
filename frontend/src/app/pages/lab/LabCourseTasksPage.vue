<script setup>
import SfxPlannedPanel from '@/app/ui/SfxPlannedPanel.vue'

/**
 * 课程任务聚合（page-design §19.2）。
 * GET /lab/course-tasks 为 planned 契约；条目必须显示课程来源，
 * 避免与自主实验混淆。
 */
</script>

<template>
  <div class="sfx-page sfx-page--narrow">
    <header class="sfx-page-header">
      <div>
        <h1 class="sfx-t-title1">课程任务</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">聚合所有课程的实验任务</p>
      </div>
    </header>

    <SfxPlannedPanel
      contract-key="lab"
      title="课程任务聚合 · 接口契约已冻结"
      available-note="单门课程的实验入口已就绪：进入课程 → 实验任务，可查看沙箱真实状态。"
    >
      <p class="sfx-t-ui sfx-t-secondary">
        契约实现后支持按课程、截止时间、状态、实验类型筛选（§19.2）；
        每个条目都会标明来源课程，与自主实验明确区分。
      </p>
    </SfxPlannedPanel>
  </div>
</template>
