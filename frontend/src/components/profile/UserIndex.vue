<!-- UserIndex.vue -->
<script setup>
import { ref } from 'vue'
import Login from './Login.vue'
import UsersData from './UsersData.vue' // 引入用户中心主页
import UserInfoCard from "./UserInfoCard.vue"
import api from '@/api/index.js'

import { useCounterStore } from '@/stores/counter.js'
const counter = useCounterStore()

// 控制是否显示设置面板
const showSettingsPanel = ref(false)

// --- 业务逻辑处理 ---

// 1. 登录成功
const handleLoginSend = async (data) => {
  console.log('触发登录发送', data)
  try {
    const res = await api.user.login(data)
    console.log(res)

    localStorage.setItem('token', res.token)
    counter.userData.username = data.username
    counter.userData.id = res.userInfo.id
    console.log('登录成功')
  } catch (error) {
    console.error('登录失败', error)
  }
}

// 2. 注册成功
const handleRegisterSend = async (data) => {
  console.log('触发注册发送', data)
  try {
    const registerData = {
      username: data.username,
      password: data.password
    }
    const res = await api.user.register(registerData)
    console.log(res)

    localStorage.setItem('token', res.token)
    counter.userData.username = data.username
    counter.userData.id = res.userInfo.id
    console.log('注册成功并自动登录')
  } catch (error) {
    console.error('注册失败', error)
  }
}

// 3. 打开设置面板 (由 UsersData 触发)
const handleOpenSettings = () => {
  showSettingsPanel.value = true
}

// 4. 更新用户名 (由 UserInfoCard 触发)
const handleUpdateUsername = (data) => {
  counter.userData = { ...counter.userData, username: data.username }
  showSettingsPanel.value = false // 关闭面板
}

// 5. 更新密码
const handleUpdatePassword = (data) => {
  console.log('密码已更新', data)
  showSettingsPanel.value = false // 关闭面板
}

// 6. 退出登录
const handleLogout = () => {
  localStorage.removeItem('token')
  counter.userData = {
    username: null,
    id: null,
  }
  showSettingsPanel.value = false
}
</script>

<template>
  <div class="user-index-wrapper">

    <!-- 1. 未登录状态：显示 Login 组件 -->
    <!-- Login 组件内部已经有 flex 居中样式，只需父级给高度 -->
    <Login
      v-if="!counter.userData.id"
      class="login-modal"
      @loginSend="handleLoginSend"
      @registerSend="handleRegisterSend"
    />

    <!-- 2. 已登录状态：显示用户中心主页 -->
    <UsersData
      v-else
      @openSettings="handleOpenSettings"
      @logout="handleLogout"
    />

    <!-- 3. 设置面板 (浮层/弹窗) -->
    <Transition name="fade">
      <div v-if="counter.userData.id && showSettingsPanel" class="settings-overlay" @click.self="showSettingsPanel = false">
        <UserInfoCard
          @updateUsername="handleUpdateUsername"
          @updatePassword="handleUpdatePassword"
          @logout="handleLogout"
          @close="showSettingsPanel = false"
        />
      </div>
    </Transition>

  </div>
</template>

<style scoped>
.user-index-wrapper {
  width: 100%;
  /* 关键修改：让容器撑满整个视口高度 */
  height: 100vh;
  position: relative;

  /* 关键修改：使用 Flex 布局 */
  display: flex;
  justify-content: center;
  align-items: center;

  /* 背景美化（可选）：如果 Profile.vue 没有设置背景，可以在这里设置 */
  /* //background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%); */
}
/* 遮罩层样式 */
.settings-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(4px);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 100;
}

/* 简单的淡入淡出动画 */
.fade-enter-active, .fade-leave-active {
  transition: opacity 0.3s ease;
}
.fade-enter-from, .fade-leave-to {
  opacity: 0;
}
</style>
