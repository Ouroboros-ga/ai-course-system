<!-- components/chat/login/LoginIndex.vue -->
<template>
  <div class="login-index-wrapper">
    <!-- 给按钮添加 class，方便控制样式 -->
    <UserButton class="login-btn" @click="handleClickLogin" />

    <Transition name="login-modal">
      <!-- 给弹窗添加 class -->
      <Login
        v-if="isLogin"
        class="login-modal"
        @loginSend="handleLoginSend"
        @registerSend="handleRegisterSend"
      />
    </Transition>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import Login from './Login.vue'
import UserButton from './UserButton.vue'
import api from '@/api/index.js'

const isLogin = ref(false)

const handleClickLogin = () => {
  console.log('触发用户球')
  isLogin.value = !isLogin.value
}

const handleLoginSend = (data) => {
  console.log('触发登录发送')
  console.log(data)
  api.user.login(data)
}

const handleRegisterSend = (data) => {
  console.log('触发注册发送')
  console.log(data)
  api.user.register(data)
}
</script>

<style scoped>
/* --- 容器布局 --- */
.login-index-wrapper {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;

  /* 【修改点 1】设置为 none，允许点击穿透到下层 */
  pointer-events: none;

  z-index: 20;
}

/* 【修改点 2】恢复按钮的点击事件 */
.login-btn {
  z-index: 21;
  pointer-events: auto;
  /* 如果按钮有定位需求，请在这里添加，确保它在合适的位置 */
}

/* 【修改点 3】恢复弹窗的点击事件 */
.login-modal {
  pointer-events: auto;
}

/* --- 登录界面动画样式 --- */
.login-modal-enter-active,
.login-modal-leave-active {
  transition: all 0.4s cubic-bezier(0.25, 0.8, 0.25, 1);
}

.login-modal-enter-from {
  opacity: 0;
  transform: scale(0.95);
}

.login-modal-leave-to {
  opacity: 0;
  transform: scale(1.05);
}
</style>
