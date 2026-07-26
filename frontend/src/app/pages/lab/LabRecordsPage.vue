<script setup>
import SfxPlannedPanel from '@/app/ui/SfxPlannedPanel.vue'

/**
 * 学习记录（page-design §19.4）。
 * GET /lab/records 为 planned 契约：过程证据（首次测试结果、修改次数、
 * 提示层级、重复错误等）。学生看自己的完整过程；教师仅看课程任务范围内记录。
 */
</script>

<template>
  <div class="sfx-page sfx-page--narrow">
    <header class="sfx-page-header">
      <div>
        <h1 class="sfx-t-title1">学习记录</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">实验过程证据与结果轨迹</p>
      </div>
    </header>

    <SfxPlannedPanel
      contract-key="lab"
      title="学习记录 · 接口契约已冻结"
    >
      <p class="sfx-t-ui sfx-t-secondary">
        契约实现后记录（§19.4）：实验名、关联知识点、首次测试结果、修改次数、提示层级、
        最终结果、重复错误、完成时间与相关课程。学生可查看自己的完整过程；
        教师仅能查看课程任务范围内的必要记录。
      </p>
    </SfxPlannedPanel>
  </div>
</template>
