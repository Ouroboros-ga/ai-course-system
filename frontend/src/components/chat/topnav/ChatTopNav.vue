<template>
  <header class="top-nav">
    <button class="new-session-btn" @click="createNewSession">
      <span class="icon"><Plus :size="18" /></span>
      <span class="text">新建会话</span>
    </button>
    <button class="history-btn" @click="toggleHistory">
      <ArrowLeft v-if="showHistory" :size="16" />
      <Menu v-else :size="16" />
    </button>
    <div class="nav-title">Smartrab 课堂</div>
    <button class="upload-btn" @click="handleUpload">
      上传智课
    </button>
  </header>
</template>

<script setup>
import { Plus, ArrowLeft, Menu } from 'lucide-vue-next'

defineProps({
  showHistory: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['toggle-history', 'create-new-session', 'open-upload'])

const toggleHistory = () => {
  emit('toggle-history')
}

const createNewSession = () => {
  emit('create-new-session')
}

const handleUpload = () => {
  emit('open-upload')
}
</script>

<style scoped>
.top-nav {
  position: relative;
  height: 48px;
  background: var(--color-surface);
  display: flex;
  align-items: center;
  padding: 0 var(--space-3);
  box-shadow: var(--shadow-sm);
  z-index: var(--z-fixed);
  gap: var(--space-2);
}
.history-btn {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  border: none;
  background: var(--color-surface-2);
  color: var(--color-text);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background var(--duration-normal) var(--ease);
}
.history-btn:hover {
  background: var(--color-border);
}
.nav-title {
  flex: 1;
  text-align: center;
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--color-text);
}
.new-session-btn {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  border: none;
  background: var(--gradient-primary);
  color: var(--color-text-inverse);
  font-size: var(--text-xs);
  font-weight: 500;
  cursor: pointer;
  transition: box-shadow var(--duration-normal) var(--ease), transform var(--duration-normal) var(--ease);
  box-shadow: var(--shadow-primary);
}
.new-session-btn:hover {
  box-shadow: var(--shadow-lg);
  transform: translateY(-1px);
}
.new-session-btn:active {
  transform: translateY(0);
  box-shadow: var(--shadow-sm);
}
.new-session-btn .icon {
  display: flex;
  align-items: center;
  line-height: 1;
}
.new-session-btn .text {
  font-size: var(--text-xs);
}

/* 上传按钮 */
.upload-btn {
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-md);
  border: none;
  background: var(--color-primary);
  color: var(--color-text-inverse);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  transition: background var(--duration-normal) var(--ease), box-shadow var(--duration-normal) var(--ease), transform var(--duration-normal) var(--ease);
  box-shadow: var(--shadow-primary);
}
.upload-btn:hover {
  background: var(--color-primary-hover);
  box-shadow: var(--shadow-lg);
  transform: translateY(-1px);
}
.upload-btn:active {
  transform: translateY(0);
  box-shadow: var(--shadow-sm);
}

/* 移动端适配 */
@media (max-width: 768px) {
  .new-session-btn .text {
    display: none;
  }
  .new-session-btn {
    padding: var(--space-2) var(--space-2);
  }
  .upload-btn {
    padding: var(--space-2) var(--space-3);
    font-size: var(--text-xs);
  }
}
</style>
