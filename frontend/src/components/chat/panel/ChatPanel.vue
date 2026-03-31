<template>
  <div class="chat-section">
    <div class="chat-header">
      <div class="assistant-status">
        <div class="status-dot"></div>
        <span>AI 助教</span>
      </div>
      <button class="btn-more">⋮</button>
    </div>

    <MessageList
      :hasFile="hasFile"
      ref="messageListRef"
    />

    <ChatInput
      :disabled="!hasFile"
      :tips="['没听懂，再讲一遍', '这页 PPT 重点是什么？']"
      @send="handleSend"
    />
  </div>
</template>

<script setup>
import { ref } from 'vue';
import MessageList from './ChatPanel/MessageList.vue';
import ChatInput from './ChatPanel/ChatInput.vue';
import api from '@/api/index.js';
import { showToast } from '@/utils/toast';

const props = defineProps(['hasFile', 'courseId', 'chatId']);
const messageListRef = ref(null);
const currentChatId = ref(props.chatId || null);

const handleSend = async (text) => {
  if (!text) return;

  messageListRef.value?.addMessage({
    role: 'user',
    content: text
  });

  try {
    const res = await api.chat.askQuestion({
      question: text,
      chatId: currentChatId.value,
      courseId: props.courseId
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
  min-height: 500px;
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
