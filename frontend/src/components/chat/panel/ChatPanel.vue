<template>
  <div class="chat-section">
    <div class="chat-header">
      <div class="assistant-status">
        <div class="status-dot" :class="{ 'status-disabled': !canChat }"></div>
        <span>AI 助教</span>
        <span v-if="isAnalyzing" class="status-text analyzing">解析中...</span>
        <span v-else-if="!hasFile" class="status-text waiting">等待上传</span>
        <span v-else-if="!hasValidData" class="status-text waiting">等待解析</span>
      </div>
      <button class="btn-more">⋮</button>
    </div>

    <MessageList
      :hasFile="hasFile"
      ref="messageListRef"
    />

    <!-- QA输入框已移除，请使用右下角的数字人助手按钮 -->
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue';
import MessageList from './ChatPanel/MessageList.vue';
import api from '@/api/index.js';
import { showToast } from '@/utils/toast';

const props = defineProps({
  hasFile: {
    type: Boolean,
    default: false
  },
  isAnalyzing: {
    type: Boolean,
    default: false
  },
  hasValidData: {
    type: Boolean,
    default: false
  },
  currentData: {
    type: Object,
    default: () => null
  }
});

const messageListRef = ref(null);
const currentChatId = ref(null);

const canChat = computed(() => {
  return props.hasFile && !props.isAnalyzing && props.hasValidData;
});

watch(() => props.currentData, (newData) => {
  if (newData && newData.chatId) {
    currentChatId.value = newData.chatId;
  }
}, { immediate: true });

watch(() => props.hasFile, (newVal) => {
  if (!newVal) {
    messageListRef.value?.clearMessages();
    currentChatId.value = null;
  }
});

// QA发送功能已移至右下角的数字人助手组件
// 如需恢复底部输入框，请取消注释ChatInput组件和相关代码
</script>

<style scoped>
.chat-section {
  flex: 3.5;
  background: var(--color-surface);
  border-radius: 16px;
  border: 1px solid var(--color-surface-2);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);
  height: 100%;
  min-width: 320px;
  min-height: 0;
}
.chat-header {
  padding: 16px;
  border-bottom: 1px solid var(--color-surface-2);
  background: var(--color-surface-2);
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
}
.assistant-status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: var(--color-text-secondary);
}
.status-dot {
  width: 8px;
  height: 8px;
  background: var(--color-success);
  border-radius: 50%;
  animation: pulse 2s infinite;
}
.status-dot.status-disabled {
  background: var(--color-text-muted);
  animation: none;
}
.status-text {
  font-size: 12px;
  font-weight: normal;
  padding: 2px 8px;
  border-radius: 12px;
}
.status-text.analyzing {
  background: var(--color-warning-light);
  color: var(--color-warning-hover);
}
.status-text.waiting {
  background: var(--color-border);
  color: var(--color-text-secondary);
}
@keyframes pulse {
  0% { opacity: 1; }
  50% { opacity: 0.5; }
  100% { opacity: 1; }
}
.btn-more {
  background: none;
  border: none;
  font-size: 18px;
  color: var(--color-text-muted);
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
}
.btn-more:hover {
  background: var(--color-border);
}

@media (max-width: 768px) {
  .chat-section {
    flex: none;
    width: 100%;
    height: 75vh;
    min-width: auto;
    border-radius: 16px 16px 0 0;
    margin-top: -16px;
    min-height: auto;
  }
}
</style>
