<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'

/**
 * 平台级空间 L2 布局（page-design §4.3：进入实验室、资源库、任务时显示各自二级导航）。
 * 顶部最多两层菜单；当前项墨蓝文字 + 底部 2px 状态线（design.md 4.6）。
 */
const props = defineProps({
  tabs: { type: Array, required: true }, // [{ key, label, to }]
  ariaLabel: { type: String, default: '空间导航' },
})

const route = useRoute()
const activeKey = computed(() => props.tabs.find((t) => route.path.startsWith(t.to))?.key ?? props.tabs[0]?.key)
</script>

<template>
  <div class="sfx-space-layout">
    <div class="sfx-space-l2nav">
      <div class="sfx-space-l2nav-inner">
        <nav class="sfx-space-l2nav-links" :aria-label="ariaLabel">
          <RouterLink
            v-for="tab in tabs"
            :key="tab.key"
            :to="tab.to"
            class="sfx-space-l2nav-link"
            :class="{ 'is-active': activeKey === tab.key }"
          >{{ tab.label }}</RouterLink>
        </nav>
        <div v-if="$slots.actions" class="sfx-space-l2nav-actions">
          <slot name="actions" />
        </div>
      </div>
    </div>
    <router-view v-slot="{ Component, route }">
      <Transition name="sfx-page" mode="out-in">
        <component :is="Component" :key="route.path" />
      </Transition>
    </router-view>
  </div>
</template>

<style scoped>
.sfx-space-layout {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.sfx-space-l2nav {
  height: var(--nav-l2-height);
  background: var(--surface-panel);
  border-bottom: 1px solid var(--border-default);
  flex-shrink: 0;
  position: sticky;
  top: 0;
  z-index: 30;
}

.sfx-space-l2nav-inner {
  height: 100%;
  max-width: var(--content-max-width);
  margin: 0 auto;
  padding: 0 var(--space-6);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-6);
}

.sfx-space-l2nav-links {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  height: 100%;
}

.sfx-space-l2nav-link {
  position: relative;
  display: inline-flex;
  align-items: center;
  height: 100%;
  padding: 0 var(--space-4);
  color: var(--text-secondary);
  font-size: var(--ui-md-size);
  font-weight: var(--ui-md-weight);
}

.sfx-space-l2nav-link:hover { color: var(--ink-700); }
.sfx-space-l2nav-link.is-active { color: var(--ink-900); }

.sfx-space-l2nav-link.is-active::after {
  content: '';
  position: absolute;
  left: var(--space-4);
  right: var(--space-4);
  bottom: -1px;
  height: 2px;
  background: var(--ink-900);
}

.sfx-space-l2nav-actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
</style>
