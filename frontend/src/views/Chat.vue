<!-- Chat.vue -->
<template>
  <div class="chat-page">
    <!-- 使用 Transition 包裹 Login 组件 -->
    <Transition name="login-modal">
      <Login v-if="isLogin" />
    </Transition>

    <!-- 注意：LoginButton 建议放在 Login 组件内部或者按需显示 -->
    <!-- 这里保留您的原始逻辑，如果想在登录后隐藏按钮可以加 v-else -->
    <LoginButton @click="handleClickLogin" />

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

import InputBox from '@/components/chat/InputBox.vue'
import ChatBox from '@/components/chat/ChatBox.vue'
import Login from '@/components/chat/login/Login.vue'
import LoginButton from '@/components/chat/login/LoginButton.vue'

import {ref} from "vue";

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

const isLogin = ref(false)
const handleClickLogin = () => {
  console.log('登录球')
  isLogin.value = !isLogin.value
}
</script>

<style scoped>
.chat-page {
  height: 82vh;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  flex: 1;
  position: relative; /* 确保相对定位，虽然 Login 是 fixed，但这是个好习惯 */
}

/* --- 登录界面动画样式 --- */

/* 1. 进场/离场 动画过程 */
.login-modal-enter-active,
.login-modal-leave-active {
  transition: all 0.4s cubic-bezier(0.25, 0.8, 0.25, 1);
}

/* 2. 进场 初始状态 */
.login-modal-enter-from {
  opacity: 0;         /* 透明 */
  transform: scale(0.95); /* 稍微小一点 */
}

/* 3. 离场 结束状态 */
.login-modal-leave-to {
  opacity: 0;
  transform: scale(1.05); /* 离开时稍微放大一点点，产生“远去”感 */
}

</style>
