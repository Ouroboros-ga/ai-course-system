<script setup>
import SfxPlannedPanel from '@/app/ui/SfxPlannedPanel.vue'

/**
 * 我的文件（page-design §20.1）。
 * 资源库全部接口为 planned 契约（§3.9）：通用文件资源与课程资料不同，
 * 删除必须返回下游影响而非静默删除（§3.9/§20.1）。
 */
</script>

<template>
  <div class="sfx-page sfx-page--narrow">
    <header class="sfx-page-header">
      <div>
        <h1 class="sfx-t-title1">我的文件</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">管理上传到平台的资料，不等同于某门课程的资料页</p>
      </div>
    </header>

    <SfxPlannedPanel
      contract-key="resources"
      title="资源库 · 接口契约已冻结"
      available-note="课程内资料已可在「课程 → 建设 → 资料」查看真实解析状态。"
    >
      <p class="sfx-t-ui sfx-t-secondary">
        支持类型（§20.1）：PPT、PDF、Word、图片、音频、视频、代码文件、数据集、教案。
        列表字段：文件名、类型、所有者、解析状态、大小、原文引用数量、被课程引用数量、更新时间。
        删除前必须显示：被哪些课程引用、哪些原文引用会失效、是否可仅移入回收站、
        是否由其他用户共同使用。
      </p>
    </SfxPlannedPanel>
  </div>
</template>
