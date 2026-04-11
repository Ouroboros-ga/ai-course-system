<template>
  <div class="desktop-layout">
    <div class="main-content">
      <slot name="main" />
    </div>
    <div class="chat-sidebar" :class="{ hidden: showHistory }">
      <slot name="sidebar" />
    </div>
  </div>
</template>

<script setup>
defineProps({
  showHistory: {
    type: Boolean,
    default: false
  }
})
</script>

<style scoped>
.desktop-layout {
  display: flex;
  gap: 16px;
  flex: 1;
  position: relative;
  width: 100%;
  box-sizing: border-box;
  min-height: 0;
  overflow: hidden;
}

.main-content {
  flex: 2;
  min-width: 300px;
  background: white;
  border-radius: 16px;
  overflow: hidden;
  box-sizing: border-box;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.chat-sidebar {
  flex: 1;
  min-width: 280px;
  max-width: 450px;
  background: white;
  border-radius: 16px;
  overflow: hidden;
  transition: all 0.5s cubic-bezier(0.25, 0.8, 0.25, 1);
  opacity: 1;
  transform: translateX(0);
  box-sizing: border-box;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.chat-sidebar.hidden {
  opacity: 0;
  transform: translateX(50px);
  pointer-events: none;
}
</style>
