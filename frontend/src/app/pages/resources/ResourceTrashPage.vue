<script setup>
import SfxPlannedPanel from '@/app/ui/SfxPlannedPanel.vue'

/**
 * 回收站（page-design §20.4）。
 * planned 契约：显示删除时间、影响范围和恢复期限；永久删除必须二次确认。
 */
</script>

<template>
  <div class="sfx-page sfx-page--narrow">
    <header class="sfx-page-header">
      <div>
        <h1 class="sfx-t-title1">回收站</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">已删除资源的恢复与彻底清理</p>
      </div>
    </header>

    <SfxPlannedPanel
      contract-key="resources"
      title="回收站 · 接口契约已冻结"
    >
      <p class="sfx-t-ui sfx-t-secondary">
        将显示（§20.4）：删除时间、影响范围和恢复期限；支持恢复（restore）与
        永久删除（purge，需更高权限且二次确认）。
      </p>
    </SfxPlannedPanel>
  </div>
</template>
