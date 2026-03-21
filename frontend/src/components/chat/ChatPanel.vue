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

    <!-- 👈 恢复：没文件就禁用，有文件才能用 -->
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

const props = defineProps(['hasFile']);
const messageListRef = ref(null);

const handleSend = async (text) => {
  if (!text) return;

  messageListRef.value?.addMessage({
    role: 'user',
    content: text
  });

  setTimeout(() => {
    messageListRef.value?.addMessage({
      role: 'ai',
      content: `我收到了你的问题：「${text}」，正在为你解答...`,
      showResumeBtn: true
    });
  }, 1000);
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
    height: 50vh;
    min-width: auto;
    border-radius: 16px 16px 0 0;
    margin-top: -16px;
    min-height: auto;
  }
}
</style>
