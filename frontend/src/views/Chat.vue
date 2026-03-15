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
import { useCounterStore } from "@/stores/counter.js";
const counter = useCounterStore()

import InputBox from '../components/home/InputBox.vue'
import ChatBox from '../components/home/ChatBox.vue'

const handleSendMessage = (text) => {
  console.log('📤 发送消息:', text)
  let theId = 0
  if (counter.messages.length !== 0){
    let index = counter.messages.length - 1
    theId = counter.messages[index].id + 1
  }
  counter.addMessage({id: theId, class: 'user', message: text})

  // TODO: 模拟ai回答
  counter.addMessage({id: theId + 1, class: 'ai', message: '模拟ai回答'})
  // console.log(counter.messages)
}

const handleAddAttachment = (file) => {
  console.log('📎 点击添加附件')
  console.log(file)
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
