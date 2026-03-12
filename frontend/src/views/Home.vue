<!-- Parent.vue -->
<template>
  <div class="chat-page">
    <ChatBox class="chat-box" />
    <InputBox
      @send="handleSendMessage"
      @add="handleAddAttachment"
    />
  </div>
</template>

<script setup>
import InputBox from '../components/home/InputBox.vue'
import ChatBox from '../components/home/ChatBox.vue'

const handleSendMessage = (text) => {
  console.log('📤 发送消息:', text)
  // TODO: 调用 API 发送消息
}

const handleAddAttachment = () => {
  console.log('📎 点击添加附件')
  // TODO: 打开文件选择器
}
</script>

<style scoped>
.chat-page {
  height: 75vh;
  display: flex;
  flex-direction: column;
  background-color: rgba(0, 0, 0, 0);
  /* 底部安全区回退值（0 表示没有安全区时的默认值） */
  padding-bottom: env(safe-area-inset-bottom, 80);
}

.chat-box {
  flex: 1;
  overflow-y: auto;
  /* 其余样式由 chatBox 组件自己负责 */
}
</style>
