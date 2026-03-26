<template>
  <div class="mobile-layout">
    <div v-show="activeTab === 'ppt'" class="tab-content">
      <slot name="ppt" />
    </div>
    <div v-show="activeTab === 'chat'" class="tab-content">
      <slot name="chat" />
    </div>

    <div class="mobile-tab">
      <button @click="switchTab('ppt')" :class="{ active: activeTab === 'ppt' }">
        PPT
      </button>
      <button @click="switchTab('chat')" :class="{ active: activeTab === 'chat' }">
        对话
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  defaultTab: {
    type: String,
    default: 'ppt'
  }
})

const emit = defineEmits(['tab-change'])

const activeTab = ref(props.defaultTab)

const switchTab = (tab) => {
  activeTab.value = tab
  emit('tab-change', tab)
}
</script>

<style scoped>
.mobile-layout {
  display: flex;
  flex-direction: column;
  flex: 1;
  height: calc(100vh - 48px - 60px);
}

.tab-content {
  flex: 1;
  overflow-y: auto;
  width: 100%;
  box-sizing: border-box;
  background: white;
  border-radius: 16px;
  padding: 12px;
  margin: 0;
}

.mobile-tab {
  position: fixed;
  bottom: 0;
  left: 0;
  width: 100%;
  height: 60px;
  background: white;
  display: flex;
  box-shadow: 0 -2px 10px rgba(0,0,0,0.1);
  z-index: 20;
}
.mobile-tab button {
  flex: 1;
  border: none;
  background: none;
  font-size: 15px;
  color: #666;
}
.mobile-tab button.active {
  color: #4f46e5;
  font-weight: bold;
}
</style>
