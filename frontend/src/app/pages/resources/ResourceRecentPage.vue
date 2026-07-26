<script setup>
import SfxPlannedPanel from '@/app/ui/SfxPlannedPanel.vue'

/**
 * 最近使用（page-design §20.3）。
 * planned 契约：按用户最近打开、编辑、引用排序。
 */
</script>

<template>
  <div class="sfx-page sfx-page--narrow">
    <header class="sfx-page-header">
      <div>
        <h1 class="sfx-t-title1">最近使用</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">最近打开、编辑、引用过的资源</p>
      </div>
    </header>

    <SfxPlannedPanel
      contract-key="resources"
      title="最近使用 · 接口契约已冻结"
    >
      <p class="sfx-t-ui sfx-t-secondary">
        按最近打开、编辑、引用排序（§20.3），帮助你快速回到正在处理的资料。
      </p>
    </SfxPlannedPanel>
  </div>
</template>
