<!-- Chat.vue -->
<template>
  <div class="chat-page">
    <!-- 使用封装好的 LoginIndex 组件 -->
    <UserIndex />

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

// 引入组件
import InputBox from '@/components/chat/InputBox.vue'
import ChatBox from '@/components/chat/ChatBox.vue'
// 引入封装后的登录组件
import UserIndex from '@/components/chat/User/UserIndex.vue'

// import {ref} from "vue";

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
}

const handleAddAttachment = (file) => {
  console.log('📎 点击添加附件')
  console.log(file)
}
</script>

<style scoped>
.chat-page {
  height: 82vh;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  flex: 1;
  position: relative;
}

/* 原来的登录动画样式已经移动到 LoginIndex.vue 中，这里可以删除 */
</style>
