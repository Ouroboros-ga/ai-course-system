<template>
  <header class="top-nav">
    <button class="history-btn" @click="toggleHistory">
      <span v-if="showHistory">←</span>
      <span v-else>三</span>
    </button>
    <div class="nav-title">Smartrab 课堂</div>
  </header>
</template>

<script setup>
defineProps({
  showHistory: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['toggle-history'])

const toggleHistory = () => {
  emit('toggle-history')
}
</script>

<style scoped>
.top-nav {
  position: relative;
  height: 48px;
  background: white;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  z-index: 9999;
}
.history-btn {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  border: none;
  background: #f1f5f9;
  font-size: 16px;
  font-weight: bold;
  color: #333;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  z-index: 10000;
  transition: all 0.2s ease;
}
.history-btn:hover {
  background: #e2e8f0;
}
.nav-title {
  flex: 1;
  text-align: center;
  font-size: 16px;
  font-weight: 600;
  color: #111;
}
</style>
