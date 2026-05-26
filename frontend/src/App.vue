<script setup>
  import { onMounted } from 'vue'
  import NavigationBar from "./components/NavigationBar.vue"
  import GradientBackground from "./components/GradientBackground.vue"
  import { useCounterStore } from "@/stores/counter.js"

  const counter = useCounterStore()

  onMounted(() => {
    counter.checkAuth()
  })
</script>

<template>
  <div id="app">
    <NavigationBar />
    <GradientBackground
      :animated="true"
      :interactive="true"
      :parallax="true"
    />
  </div>
</template>

<style>
/* ========== 全局重置样式 ========== */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body {
  width: 100%;
  height: 100%;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', 'Fira Sans', 'Droid Sans', 'Helvetica Neue', sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  overflow: hidden;
}

#app {
  width: 100%;
  height: 100%;
  position: relative;
}

a {
  text-decoration: none;
  color: inherit;
}

button {
  border: none;
  background: none;
  cursor: pointer;
  font-family: inherit;
  font-size: inherit;
}

img {
  max-width: 100%;
  display: block;
}

ul, ol {
  list-style: none;
}

input, textarea {
  border: none;
  outline: none;
  font-family: inherit;
  font-size: inherit;
}

/* 滚动条美化 */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: rgba(0, 0, 0, 0.05);
}

::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.2);
  border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
  background: rgba(0, 0, 0, 0.3);
}
</style>
