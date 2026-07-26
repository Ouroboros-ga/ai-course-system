<script setup>
import SfxPlannedPanel from '@/app/ui/SfxPlannedPanel.vue'

/**
 * 系统任务（page-design §21.3）。
 * GET /tasks?view=system 为 planned 契约：文档解析、TTS、数字人、AI PPT、
 * 索引构建、图谱候选、泛雅同步、沙箱环境创建。
 * 失败任务必须提供：明确原因、影响范围、重试、降级方案、返回相关页面、日志入口。
 */
</script>

<template>
  <div class="sfx-page sfx-page--narrow">
    <header class="sfx-page-header">
      <div>
        <h1 class="sfx-t-title1">系统任务</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">平台异步任务的进度与失败处理</p>
      </div>
    </header>

    <SfxPlannedPanel
      contract-key="tasks"
      title="系统任务 · 接口契约已冻结"
      available-note="TTS 与视频生成任务的真实进度、失败原因和重试次数已在「课程 → 建设 → 媒体生成」展示。"
    >
      <p class="sfx-t-ui sfx-t-secondary">
        任务类型（§21.3）：文档解析、TTS、数字人、AI PPT、索引构建、图谱候选、泛雅同步、沙箱环境创建。
        失败任务必须提供：明确原因、影响范围、重试、降级方案、返回相关页面、日志或审计入口。
        任务中心优先使用列表而不是卡片墙（design.md 4.8）。
      </p>
    </SfxPlannedPanel>
  </div>
</template>
