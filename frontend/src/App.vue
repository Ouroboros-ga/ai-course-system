<script setup>
  import { computed, onMounted } from 'vue'
  import { useRoute } from 'vue-router'
  import NavigationBar from "./components/NavigationBar.vue"
  import GradientBackground from "./components/GradientBackground.vue"
  import { useCounterStore } from "@/stores/counter.js"

  const counter = useCounterStore()
  const route = useRoute()

  // Shadow frontend (/app/**) renders its own AppShell. The legacy
  // NavigationBar/GradientBackground shell is bypassed for those routes so
  // the two visual systems never mix.
  const isShadowApp = computed(() => route.path === '/app' || route.path.startsWith('/app/'))
  // The authentication entry owns its complete Academic Ink layout.
  const isAuthEntry = computed(() => route.path === '/profile' && !counter.isLoggedIn)
  // 文档中心（/docs 顶层公开页）自带 .docs-nav 顶栏，同样绕过 legacy 壳，
  // 避免老版一级菜单（首页/关于/个人中心）出现在文档中心顶部。
  const isDocsEntry = computed(() => route.path === '/docs' || route.path.startsWith('/docs/'))

  onMounted(() => {
    counter.checkAuth()
  })
</script>

<template>
  <div id="app">
    <router-view v-if="isShadowApp" />
    <router-view v-else-if="isAuthEntry" />
    <router-view v-else-if="isDocsEntry" />
    <template v-else>
      <NavigationBar />
      <GradientBackground
        :animated="true"
      />
    </template>
  </div>
</template>

<style>
/* ========== 全局重置 ========== */

*,
*::before,
*::after {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body {
  width: 100%;
  min-height: 100%;
  font-family: var(--font-sans);
  font-size: var(--text-base);
  line-height: var(--leading-normal);
  color: var(--color-text);
  background: var(--color-bg);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  /* clip 而非 hidden：不创建滚动容器，不破坏 position: sticky */
  overflow-x: clip;
  transition: background-color var(--duration-slow) var(--ease), color var(--duration-slow) var(--ease);
}

#app {
  width: 100%;
  min-height: 100%;
  position: relative;
}

a {
  text-decoration: none;
  color: var(--color-primary);
  transition: color var(--duration-fast) var(--ease);
}

a:hover {
  color: var(--color-primary-hover);
}

button {
  border: none;
  background: none;
  cursor: pointer;
  font-family: inherit;
  font-size: inherit;
  color: inherit;
}

img {
  max-width: 100%;
  display: block;
}

ul, ol {
  list-style: none;
}

input, textarea, select {
  border: none;
  outline: none;
  font-family: inherit;
  font-size: inherit;
  color: inherit;
}

input:focus-visible,
textarea:focus-visible,
select:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

/* 可访问性：尊重减少动画偏好 */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}

/* 滚动条 */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: var(--color-border);
  border-radius: var(--radius-full);
}

::-webkit-scrollbar-thumb:hover {
  background: var(--color-border-hover);
}

/* Firefox */
* {
  scrollbar-width: thin;
  scrollbar-color: var(--color-border) transparent;
}

/* 选中文本 */
::selection {
  background: var(--color-primary-light);
  color: var(--color-primary);
}
</style>
