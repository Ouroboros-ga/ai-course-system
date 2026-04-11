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
        <!-- 仅AI消息显示跳转按钮 -->
        <button
          v-if="msg.role === 'ai' && msg.slideIndex !== undefined"
          class="jump-btn"
          @click="handleJump(msg.slideIndex)"
        >
          跳转到对应位置
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import MessageBubble from './MessageBubble.vue';
import { ref, watch, nextTick, onMounted } from 'vue';

const MESSAGES_STORAGE_KEY = 'chatMessages';

// 新增：定义跳转事件，父组件可监听
const emit = defineEmits(['jumpToSlide']);
const props = defineProps(['hasFile']);
const messages = ref([]);
const listRef = ref(null);

// 新增：跳转按钮点击事件
const handleJump = (slideIndex) => {
  emit('jumpToSlide', slideIndex);
};

const loadMessagesFromStorage = () => {
  try {
    const saved = localStorage.getItem(MESSAGES_STORAGE_KEY);
    if (saved) {
      const parsed = JSON.parse(saved);
      if (Array.isArray(parsed)) {
        const validMessages = parsed.filter(msg =>
          msg && typeof msg === 'object' &&
          (msg.role === 'user' || msg.role === 'ai') &&
          typeof msg.content === 'string'
        );
        messages.value = validMessages;
      }
    }
  } catch (e) {
    console.error('加载聊天记录失败:', e);
    localStorage.removeItem(MESSAGES_STORAGE_KEY);
  }
};

const saveMessagesToStorage = () => {
  try {
    localStorage.setItem(MESSAGES_STORAGE_KEY, JSON.stringify(messages.value));
  } catch (e) {
    console.error('保存聊天记录失败:', e);
  }
};

watch(messages, () => {
  saveMessagesToStorage();
  scrollToBottom();
}, { deep: true });

const scrollToBottom = () => {
  nextTick(() => {
    if (listRef.value) {
      listRef.value.scrollTop = listRef.value.scrollHeight;
    }
  });
};

onMounted(() => {
  loadMessagesFromStorage();
});

defineExpose({
  addMessage: (msg) => {
    if (msg && typeof msg === 'object' && typeof msg.content === 'string') {
      messages.value.push(msg);
    }
  },
  clearMessages: () => {
    messages.value = [];
    localStorage.removeItem(MESSAGES_STORAGE_KEY);
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
  min-height: 0;
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

/* 新增：跳转按钮样式 */
.jump-btn {
  align-self: flex-start;
  margin-top: 4px;
  padding: 6px 12px;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: #ffffff;
  color: #6b7280;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}
.jump-btn:hover {
  background: #f3f4f6;
  color: #2563eb;
  border-color: #2563eb;
}
</style>
