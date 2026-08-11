<script setup>
import { computed, inject } from 'vue'
import {
  Info, UserRoundPlus, Bot, ShieldCheck, TerminalSquare, Plug,
} from 'lucide-vue-next'
import SfxLocalRail from '@/app/ui/SfxLocalRail.vue'

/**
 * 课程设置布局（page-design §18.1）。
 * Local Rail 固定六项：基础信息 / 加入与发布 / 智能体 / 安全与合规 / 沙箱权限 / 平台集成。
 */
const courseContext = inject('courseContext')
const courseId = computed(() => courseContext.courseId.value)

const railItems = computed(() => {
  const base = `/app/course/${courseId.value}/settings`
  return [
    { key: 'profile', label: '基础信息', to: `${base}/profile`, icon: Info },
    { key: 'access', label: '加入与发布', to: `${base}/access`, icon: UserRoundPlus },
    { key: 'agent', label: '智能体', to: `${base}/agent`, icon: Bot },
    { key: 'safety', label: '安全与合规', to: `${base}/safety`, icon: ShieldCheck },
    { key: 'sandbox', label: '沙箱权限', to: `${base}/sandbox`, icon: TerminalSquare },
    { key: 'integrations', label: '平台集成', to: `${base}/integrations`, icon: Plug },
  ]
})
</script>

<template>
  <div class="sfx-settings-layout">
    <SfxLocalRail :items="railItems" aria-label="课程设置" storage-key="settings" />
    <div class="sfx-settings-main">
      <router-view v-slot="{ Component, route }">
        <Transition name="sfx-page" mode="out-in">
          <component :is="Component" :key="route.path" />
        </Transition>
      </router-view>
    </div>
  </div>
</template>

<style scoped>
.sfx-settings-layout {
  display: flex;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.sfx-settings-main {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
</style>

<style>
.sfx-settings-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-8) var(--space-6) var(--space-12);
  max-width: 860px;
  margin: 0 auto;
  width: 100%;
}

.sfx-settings-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-2);
}

.sfx-settings-head h1 { margin: 0; }
.sfx-settings-head p { margin: var(--space-1) 0 0; }

.sfx-settings-notice {
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  font-size: var(--ui-sm-size);
  line-height: var(--ui-sm-line);
}

.sfx-settings-notice.is-success {
  color: var(--green-700);
  background: var(--green-100);
}

.sfx-settings-notice.is-error {
  color: var(--red-700);
  background: var(--red-100);
}

.sfx-settings-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-2);
}
</style>
