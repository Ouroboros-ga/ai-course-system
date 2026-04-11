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

    <ChatInput
      :disabled="!canChat"
      :tips="['没听懂，再讲一遍', '这页 PPT 重点是什么？']"
      @send="handleSend"
    />
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue';
import MessageList from './ChatPanel/MessageList.vue';
import ChatInput from './ChatPanel/ChatInput.vue';
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

const handleSend = async (text) => {
  if (!text || !canChat.value) return;

  messageListRef.value?.addMessage({
    role: 'user',
    content: text
  });

  try {
    const res = await api.chat.askQuestion({
      question: text,
      chatId: currentChatId.value,
      courseId: props.currentData?.courseId
    });

    if (res.chatId && !currentChatId.value) {
      currentChatId.value = res.chatId;
    }

    messageListRef.value?.addMessage({
      role: 'ai',
      content: res.answer,
      showResumeBtn: true
    });
  } catch (err) {
    console.error('问答失败', err);
    showToast(err.message || '问答失败，请重试', 'error');
    messageListRef.value?.addMessage({
      role: 'ai',
      content: '抱歉，我遇到了一些问题，请稍后再试。',
      showResumeBtn: false
    });
  }
};
</script>

<style scoped>
.chat-section {
  flex: 3.5;
  background: white;
  border-radius: 16px;
  border: 1px solid #f3f4f6;
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
  border-bottom: 1px solid #f9fafb;
  background: #f9fafb;
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
  color: #374151;
}
.status-dot {
  width: 8px;
  height: 8px;
  background: #22c55e;
  border-radius: 50%;
  animation: pulse 2s infinite;
}
.status-dot.status-disabled {
  background: #9ca3af;
  animation: none;
}
.status-text {
  font-size: 12px;
  font-weight: normal;
  padding: 2px 8px;
  border-radius: 12px;
}
.status-text.analyzing {
  background: #fef3c7;
  color: #d97706;
}
.status-text.waiting {
  background: #e5e7eb;
  color: #6b7280;
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
  color: #9ca3af;
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
}
.btn-more:hover {
  background: #e5e7eb;
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
