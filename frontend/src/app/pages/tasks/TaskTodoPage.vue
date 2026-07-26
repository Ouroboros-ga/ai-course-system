<script setup>
import SfxPlannedPanel from '@/app/ui/SfxPlannedPanel.vue'

/**
 * 我的待办（page-design §21.1）。
 * GET /tasks?view=todo 为 planned 契约：学生（继续课程/测验/实验/补学/补充材料），
 * 教师（审核加入申请/确认知识候选/补充原文引用/处理失败媒体/审核实验提交/发布课程）。
 */
</script>

<template>
  <div class="sfx-page sfx-page--narrow">
    <header class="sfx-page-header">
      <div>
        <h1 class="sfx-t-title1">我的待办</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">需要你亲自完成的任务</p>
      </div>
    </header>

    <SfxPlannedPanel
      contract-key="tasks"
      title="任务中心 · 接口契约已冻结"
      available-note="知识候选审核已在「课程 → 知识 → 候选审核」真实可用；媒体失败任务可在「课程 → 建设 → 媒体生成」查看真实状态。"
    >
      <p class="sfx-t-ui sfx-t-secondary">
        学生待办（§21.1）：继续课程、测验、实验、补学、申请补充材料。
        教师待办：审核加入申请、确认知识候选、补充原文引用、处理失败媒体、审核实验提交、发布课程。
        列表字段：任务标题、来源课程或系统、类型、优先级、截止时间、状态、主操作。
      </p>
    </SfxPlannedPanel>
  </div>
</template>
