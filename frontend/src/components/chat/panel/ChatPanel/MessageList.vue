<template>
  <div class="message-list" ref="listRef">
    <!-- 没上传文件 → 提示上传 -->
    <div v-if="!hasFile" class="message-row">
      <div class="avatar avatar-ai">
        <span>AI</span>
      </div>
      <div class="bubble-container">
        <MessageBubble
          role="ai"
          content="👋 你好，请上传课件！"
        />
      </div>
    </div>

    <!-- 已上传文件 → 欢迎提问 -->
    <div v-else class="message-row">
      <div class="avatar avatar-ai">
        <span>AI</span>
      </div>
      <div class="bubble-container">
        <MessageBubble
          role="ai"
          content="👋 你好！请向我提问吧！"
        />
      </div>
    </div>

    <!-- 对话记录 -->
    <div
      v-for="(msg, index) in messages"
      :key="index"
      :class="['message-row', msg.role === 'user' ? 'row-user' : '']"
    >
      <div class="avatar" :class="msg.role === 'ai' ? 'avatar-ai' : 'avatar-user'">
        <span v-if="msg.role === 'ai'">AI</span>
        <img v-else src="https://api.dicebear.com/7.x/avataaars/svg?seed=Felix" alt="User">
      </div>
      <div class="bubble-container">
        <MessageBubble v-bind="msg" />
      </div>
    </div>
  </div>
</template>

<script setup>
import MessageBubble from './MessageBubble.vue';
import { ref, watch, nextTick } from 'vue';

const props = defineProps(['hasFile']);
const messages = ref([]);
const listRef = ref(null);

const scrollToBottom = () => {
  nextTick(() => {
    if (listRef.value) {
      listRef.value.scrollTop = listRef.value.scrollHeight;
    }
  });
};

watch(messages, () => scrollToBottom(), { deep: true });

defineExpose({
  addMessage: (msg) => {
    messages.value.push(msg);
  }
});
</script>

<style scoped>
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  background: #fafafa;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.message-row {
  display: flex;
  gap: 12px;
}
.row-user {
  flex-direction: row-reverse;
}
.avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  flex-shrink: 0;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: bold;
}
.avatar-ai {
  background: #dbeafe;
  color: #2563eb;
}
.avatar-user {
  background: #e5e7eb;
}
.avatar-user img {
  width: 100%;
  height: 100%;
}
.bubble-container {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-width: 85%;
}
.row-user .bubble-container {
  align-items: flex-end;
}
</style>
