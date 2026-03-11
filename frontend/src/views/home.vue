<!-- Parent.vue -->
<template>
  <div class="chat-page">
    <!-- 其他内容 -->
    <ChatBox />

    <InputBox
      @send="handleSendMessage"
      @add="handleAddAttachment"
    />
  </div>
</template>

<script setup>
import InputBox from '../components/home/inputBox.vue'
import ChatBox from '../components/home/chatBox.vue'

const handleSendMessage = (text) => {
  console.log('📤 发送消息:', text)
  // TODO: 调用 API 发送消息
}

const handleAddAttachment = () => {
  console.log('📎 点击添加附件')
  // TODO: 打开文件选择器
}
</script>
