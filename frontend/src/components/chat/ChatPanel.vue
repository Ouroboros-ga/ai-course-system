<template>
  <div class="chat-section">
    <!-- 头部 -->
    <div class="chat-header">
      <div class="assistant-status">
        <div class="status-dot"></div>
        <span>AI 助教</span>
      </div>
      <button class="btn-more">⋮</button>
    </div>

    <!-- 消息列表 -->
    <MessageList :hasFile="hasFile" />

    <!-- 输入框 -->
    <ChatInput
      :disabled="!hasFile"
      :tips="['没听懂，再讲一遍', '这页 PPT 重点是什么？']"
      @send="handleSend"
    />
  </div>
</template>

<script setup>
// ✅ 修正路径：假设 MessageList 和 ChatInput 在同一级目录下
import MessageList from './ChatPanel/MessageList.vue';
import ChatInput from './ChatPanel/ChatInput.vue';

defineProps(['hasFile']);

const handleSend = (text) => {
  console.log('发送:', text);
  // 这里后续可以对接真实的发送逻辑
};
</script>

<style scoped>
/* ================= PC 端样式 ================= */
.chat-section {
  flex: 3.5; /* 右侧占比，与左侧 6.5 对应 */
  background: white;
  border-radius: 16px;
  border: 1px solid #f3f4f6;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);
  height: 100%; /* 关键：填满父容器高度 */
  min-width: 320px; /* 防止太窄 */

  /* ✅ 核心修改：设置最小高度，保证即使没消息也不会太矮，从而能和左边对齐 */
  min-height: 500px;
}

.chat-header {
  padding: 16px;
  border-bottom: 1px solid #f9fafb;
  background: #f9fafb;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0; /* 防止头部被压缩 */
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

/* ================= 📱 移动端适配 ================= */
@media (max-width: 768px) {
  .chat-section {
    flex: none; /* 取消 flex 占比 */
    width: 100%; /* 占满整行 */
    height: 50vh; /* 高度设为屏幕一半 */
    min-width: auto;
    border-radius: 16px 16px 0 0; /* 底部圆角去掉，贴合屏幕 */
    margin-top: -16px; /* 稍微往上提，消除间隙 */
    min-height: auto; /* 移动端由 50vh 控制，不需要 min-height */
  }
}
</style>
