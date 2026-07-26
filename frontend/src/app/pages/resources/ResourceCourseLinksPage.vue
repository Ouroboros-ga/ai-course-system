<script setup>
import SfxPlannedPanel from '@/app/ui/SfxPlannedPanel.vue'

/**
 * 课程引用（page-design §20.2）。
 * planned 契约：按课程查看资源引用关系；区分原文件 / 课程引用 /
 * 课程内派生内容 / 来源已更新 / 引用失效；引用不复制失控版本。
 */
</script>

<template>
  <div class="sfx-page sfx-page--narrow">
    <header class="sfx-page-header">
      <div>
        <h1 class="sfx-t-title1">课程引用</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">按课程查看资源引用关系</p>
      </div>
    </header>

    <SfxPlannedPanel
      contract-key="resources"
      title="课程引用 · 接口契约已冻结"
      available-note="课程内「知识 → 原文引用」已可查看真实的引用记录与失效状态。"
    >
      <p class="sfx-t-ui sfx-t-secondary">
        必须区分（§20.2）：原文件、课程引用、课程内派生内容、来源已更新、引用失效。
        课程引用资源时创建引用关系，不复制多个失控版本。
      </p>
    </SfxPlannedPanel>
  </div>
</template>
