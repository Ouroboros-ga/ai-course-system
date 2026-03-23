<!-- UserIndex.vue -->
<script setup>
import { ref, onMounted } from 'vue'
import Login from './Login.vue'
import UsersData from './UsersData.vue'
import UserInfoCard from "./UserInfoCard.vue"
import api from '@/api/index.js'
import { showToast } from '@/utils/toast'

import { useCounterStore } from '@/stores/counter.js'
const counter = useCounterStore()

// 控制是否显示设置面板
const showSettingsPanel = ref(false)

// --- 页面加载时恢复登录状态 ---
onMounted(() => {
  const token = localStorage.getItem('token')
  const id = localStorage.getItem('userId')
  const username = localStorage.getItem('username')

  // 如果本地有数据且 Store 为空，则恢复
  if (token && id && !counter.userData.id) {
    counter.userData.id = id
    counter.userData.username = username
  }
})

// --- 业务逻辑处理 ---

// 1. 登录成功
const handleLoginSend = async (data) => {
  try {
    const res = await api.user.login(data)

    // 持久化存储
    localStorage.setItem('token', res.token)
    localStorage.setItem('userId', res.userInfo.id)
    localStorage.setItem('username', data.username)

    // 更新内存状态
    counter.userData.username = data.username
    counter.userData.id = res.userInfo.id

    showToast("登录成功", "success")
  } catch (error) {
    console.error('登录失败', error)
    showToast(error || "错误", "error")
  }
}

// 2. 注册成功
const handleRegisterSend = async (data) => {
  try {
    const registerData = {
      username: data.username,
      password: data.password
    }
    const res = await api.user.register(registerData)

    // 持久化存储
    localStorage.setItem('token', res.token)
    localStorage.setItem('userId', res.userInfo.id)
    localStorage.setItem('username', data.username)

    // 更新内存状态
    counter.userData.username = data.username
    counter.userData.id = res.userInfo.id

    showToast("注册成功并自动登录", "success")
  } catch (error) {
    console.error('注册失败', error)
    showToast(error || "错误", "error")
  }
}

// 3. 打开设置面板
const handleOpenSettings = () => {
  showSettingsPanel.value = true
}

// 4. 更新用户名 (严格适配接口文档)
const handleUpdateUsername = async (data) => {
  // data 由子组件传入: { username: "新用户名", oldPassword: "当前密码" }
  console.log('准备更新用户名:', data)

  try {
    // 构建符合文档的请求参数
    const params = {
      id: counter.userData.id,              // 必填：当前用户ID
      username: counter.userData.username,  // 必填：当前用户名 (身份校验)
      password: data.oldPassword,              // 必填：当前密码 (身份校验)
      newUsername: data.username,           // 选填：新用户名
      newPassword: "",
    }

    const res = await api.user.modify(params)

    console.log('更新结果:', res)

    // 关键步骤：更新 Token 和 本地状态
    // 接口文档说明：修改成功后返回新 Token，旧 Token 失效
    localStorage.setItem('token', res.token)

    // 更新本地存储的用户名 (注意使用返回的数据，确保一致性)
    localStorage.setItem('username', res.userInfo.username)

    // 更新 Store 内存状态
    counter.userData.username = res.userInfo.username

    showToast("用户名修改成功", "success")
    showSettingsPanel.value = false
  } catch (error) {
    console.error('更新用户名失败', error)
    // 此处可能会捕获到 "用户名已存在(code 409)" 等错误
    showToast(error || "修改失败", "error")
  }
}

// 5. 更新密码 (严格适配接口文档)
const handleUpdatePassword = async (data) => {
  // data 由子组件传入: { oldPassword: "旧密码", newPassword: "新密码" }
  console.log('准备更新密码:', data)

  try {
    // 构建符合文档的请求参数
    const params = {
      id: counter.userData.id,              // 必填：当前用户ID
      username: counter.userData.username,  // 必填：当前用户名 (身份校验)
      password: data.oldPassword,           // 必填：当前密码 (身份校验)
      newPassword: data.newPassword,        // 选填：新密码
      newUsername: "",  // 传入空字符表示不更改
    }

    const res = await api.user.modify(params)

    console.log('密码更新结果:', res)

    // 关键步骤：更新 Token
    // 密码修改成功后，Token 也会刷新，必须更新本地存储
    localStorage.setItem('token', res.token)

    showToast("密码修改成功", "success")
    showSettingsPanel.value = false
  } catch (error) {
    console.error('更新密码失败', error)
    showToast(error || "修改失败", "error")
  }
}

// 6. 退出登录
const handleLogout = () => {
  // 清除所有相关缓存
  localStorage.removeItem('token')
  localStorage.removeItem('userId')
  localStorage.removeItem('username')

  // 重置 Store
  counter.userData = {
    username: null,
    id: null,
  }
  showSettingsPanel.value = false
}
</script>

<template>
  <div class="user-index-wrapper">

    <!-- 1. 未登录状态 -->
    <Login
      v-if="!counter.userData.id"
      class="login-modal"
      @loginSend="handleLoginSend"
      @registerSend="handleRegisterSend"
    />

    <!-- 2. 已登录状态 -->
    <UsersData
      v-else
      @openSettings="handleOpenSettings"
      @logout="handleLogout"
    />

    <!-- 3. 设置面板 -->
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
/* 样式部分保持不变 */
.user-index-wrapper {
  width: 100%;
  height: 100vh;
  position: relative;
  display: flex;
  justify-content: center;
  align-items: center;
}

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

.fade-enter-active, .fade-leave-active {
  transition: opacity 0.3s ease;
}
.fade-enter-from, .fade-leave-to {
  opacity: 0;
}
</style>
