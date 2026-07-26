<script setup>
import SfxPlannedPanel from '@/app/ui/SfxPlannedPanel.vue'

/**
 * 设置 · 平台集成（page-design §18.7）。
 * 泛雅绑定与同步为 planned 契约（§3.8）：显式异步同步，不在页面请求中
 * 隐式调外部平台；同步前必须预览变化（§17.5）。
 */
</script>

<template>
  <div class="sfx-integrations">
    <header class="sfx-integrations-head">
      <div>
        <h1 class="sfx-t-title2">平台集成</h1>
        <p class="sfx-t-ui sfx-t-secondary">泛雅课程绑定与同步</p>
      </div>
    </header>

    <SfxPlannedPanel
      contract-key="fanya-sync"
      title="泛雅集成 · 接口契约已冻结"
    >
      <p class="sfx-t-ui sfx-t-secondary">
        契约实现后可配置（§18.7）：泛雅课程绑定、成员同步、内容同步、回调与任务状态、
        最近同步与冲突处理。外部服务不可用时保留本地课程可用性和错误记录；
        同步前必须预览变化，禁止静默覆盖本地成员关系。
      </p>
    </SfxPlannedPanel>
  </div>
</template>

<style scoped>
.sfx-integrations {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-6);
  max-width: 860px;
}

.sfx-integrations-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-4);
}
</style>
