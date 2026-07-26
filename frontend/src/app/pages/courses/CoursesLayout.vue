<script setup>
import { computed, provide, ref } from 'vue'
import { useRoute } from 'vue-router'
import { UserRoundPlus } from 'lucide-vue-next'
import JoinCourseDrawer from '@/app/components/courses/JoinCourseDrawer.vue'

/**
 * 「我的课程」L2 布局（page-design §2.2/§4.3）。
 * 二级导航：我学习的｜我建设的｜课程大厅；右上角主操作：[加入课程]。
 * 加入课程是右侧聚焦抽屉（§9.4），不是独立页面。
 */
const route = useRoute()

const tabs = [
  { key: 'learning', label: '我学习的', to: '/app/courses/learning' },
  { key: 'building', label: '我建设的', to: '/app/courses/building' },
  { key: 'hall', label: '课程大厅', to: '/app/courses/hall' },
]

const activeKey = computed(() => tabs.find((t) => route.path.startsWith(t.to))?.key ?? 'learning')

const joinOpen = ref(false)
function openJoin() { joinOpen.value = true }
function closeJoin() { joinOpen.value = false }

// 加入成功后子页面可监听该信号刷新列表
const joinRefreshTick = ref(0)
function handleJoined() {
  joinRefreshTick.value += 1
}

provide('coursesContext', { openJoin, joinRefreshTick })
</script>

<template>
  <div class="sfx-courses-layout">
    <div class="sfx-l2nav">
      <div class="sfx-l2nav-inner">
        <nav class="sfx-l2nav-links" aria-label="我的课程导航">
          <RouterLink
            v-for="tab in tabs"
            :key="tab.key"
            :to="tab.to"
            class="sfx-l2nav-link"
            :class="{ 'is-active': activeKey === tab.key }"
          >{{ tab.label }}</RouterLink>
        </nav>
        <button type="button" class="sfx-l2nav-join" @click="openJoin">
          <UserRoundPlus :size="16" /> 加入课程
        </button>
      </div>
    </div>

    <router-view />

    <JoinCourseDrawer :open="joinOpen" @close="closeJoin" @joined="handleJoined" />
  </div>
</template>

<style scoped>
.sfx-courses-layout {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.sfx-l2nav {
  height: var(--nav-l2-height);
  background: var(--surface-panel);
  border-bottom: 1px solid var(--border-default);
  flex-shrink: 0;
}

.sfx-l2nav-inner {
  height: 100%;
  max-width: var(--content-max-width);
  margin: 0 auto;
  padding: 0 var(--space-6);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-6);
}

.sfx-l2nav-links {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  height: 100%;
}

.sfx-l2nav-link {
  position: relative;
  display: inline-flex;
  align-items: center;
  height: 100%;
  padding: 0 var(--space-4);
  color: var(--text-secondary);
  font-size: var(--ui-md-size);
  font-weight: var(--ui-md-weight);
}

.sfx-l2nav-link:hover { color: var(--ink-700); }

.sfx-l2nav-link.is-active { color: var(--ink-900); }

.sfx-l2nav-link.is-active::after {
  content: '';
  position: absolute;
  left: var(--space-4);
  right: var(--space-4);
  bottom: -1px;
  height: 2px;
  background: var(--ink-900);
}

.sfx-l2nav-join {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  height: 34px;
  padding: 0 var(--space-4);
  border-radius: var(--radius-md);
  background: var(--color-brand);
  color: var(--text-inverse);
  font-size: var(--ui-sm-size);
  font-weight: var(--ui-md-weight);
  cursor: pointer;
}

.sfx-l2nav-join:hover { background: var(--color-brand-hover); }
</style>
