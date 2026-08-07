<script setup>
import { nextTick, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import PrimaryNav from './PrimaryNav.vue'
import { getMyInfo } from '@/api/user.js'
import { useCounterStore } from '@/stores/counter.js'

const route = useRoute()
const mainRef = ref(null)
const counter = useCounterStore()

async function hydratePlatformPermissions() {
  if (!counter.isLoggedIn) return
  try {
    const data = await getMyInfo()
    counter.userData.username = data.username || counter.userData.username
    counter.userData.id = data.user_id || counter.userData.id
    counter.userData.role = data.role || 'user'
    counter.setPlatformPermissions(data.platform_permissions)
  } catch {
    // Visibility is advisory; backend permissions remain authoritative.
  }
}

hydratePlatformPermissions()

// Reset scroll position on route change (replaces vue-router scrollBehavior
// which only works on window, not on our nested scroll container).
watch(() => route.path, () => {
  nextTick(() => {
    if (mainRef.value) mainRef.value.scrollTo({ top: 0 })
  })
})
</script>

<template>
  <!-- .sfx 是影子前端令牌作用域根：design.md Academic Ink 体系只在此生效 -->
  <div class="sfx sfx-shell">
    <PrimaryNav />
    <main ref="mainRef" class="sfx-shell-main">
      <router-view v-slot="{ Component }">
        <Transition name="sfx-page" mode="out-in">
          <component :is="Component" />
        </Transition>
      </router-view>
    </main>
  </div>
</template>

<style>
/* 令牌与基础样式随 AppShell 懒加载 chunk 一起分包，legacy 页面永远不会加载 */
@import '../styles/tokens.css';
@import '../styles/base.css';
</style>

<style scoped>
.sfx-shell {
  display: flex;
  flex-direction: column;
  height: 100dvh;
  overflow: hidden;
}

.sfx-shell-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}
</style>
