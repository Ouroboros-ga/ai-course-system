<template>
  <div class="history-sidebar-wrapper" :class="{ open: showHistory }">
    <div class="history-sidebar">
      <div class="history-header">
        <h3>历史对话</h3>
      </div>
      <slot />
      <div class="mobile-profile" v-if="showHistory">
        <img src="https://picsum.photos/200/200" alt="profile" />
      </div>
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
.history-sidebar-wrapper {
  position: absolute;
  top: 0;
  left: 0;
  width: 0;
  height: 0;
  border-radius: 16px;
  overflow: hidden;
  z-index: 21;
  transition: all 0.5s cubic-bezier(0.25, 0.8, 0.25, 1);
  transform-origin: top left;
  background: white;
}

.history-sidebar-wrapper.open {
  width: 100%;
  height: 100%;
  border-radius: 16px;
  top: 0;
  left: 0;
}

.history-sidebar {
  width: 100%;
  height: 100%;
  padding: 0;
  overflow-y: auto;
  opacity: 0;
  transition: opacity 0.3s ease;
  background: white;
  box-sizing: border-box;
}

.history-sidebar-wrapper.open .history-sidebar {
  opacity: 1;
}

.history-header {
  padding: 20px 20px 12px;
  border-bottom: 1px solid #f1f5f9;
}
.history-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #111;
}

.mobile-profile {
  display: none;
  position: absolute;
  bottom: 20px;
  left: 20px;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  overflow: hidden;
}

@media (max-width: 768px) {
  .history-sidebar-wrapper {
    position: absolute !important;
    top: 0 !important;
    left: 0 !important;
    width: 0 !important;
    height: 0 !important;
    border-radius: 16px !important;
    transition: all 0.5s cubic-bezier(0.25, 0.8, 0.25, 1) !important;
    background: white !important;
    z-index: 21 !important;
  }
  .history-sidebar-wrapper.open {
    width: 100% !important;
    height: 100% !important;
    border-radius: 16px !important;
    top: 0 !important;
    left: 0 !important;
    padding: 0 !important;
    max-width: none !important;
  }
  .history-sidebar {
    opacity: 1 !important;
    padding: 0 !important;
  }
  .history-header {
    padding: 20px 20px 12px !important;
  }
}
</style>
