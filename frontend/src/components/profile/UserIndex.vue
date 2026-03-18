<!-- components/chat/login/LoginIndex.vue -->
<template>
  <div class="user-index-wrapper">
    <!-- 1. 未登录状态：显示登录/注册组件 -->
    <Login
      v-if="!userInfo"
      class="login-modal"
      @loginSend="handleLoginSend"
      @registerSend="handleRegisterSend"
    />

    <!-- 2. 已登录状态：显示用户信息卡片 -->
    <UserInfoCard
      v-else
      :userInfo="userInfo"
      @updateUsername="handleUpdateUsername"
      @updatePassword="handleUpdatePassword"
      @logout="handleLogout"
    />
  </div>
</template>

<script setup>
import { ref } from 'vue'
import Login from './Login.vue'
// 引入用户信息卡片组件 (请确认路径是否正确，这里假设放在同级目录或指定目录)
import UserInfoCard from "@/components/profile/UserInfoCard.vue";
import api from '@/api/index.js'

// 用户信息状态，初始为 null 表示未登录
const userInfo = ref({
  id: 1,
  username: 'Amq',
})

/**
 * 处理登录逻辑
 */
const handleLoginSend = async (data) => {
  console.log('触发登录发送', data)
  try {
    // 调用登录接口
    const res = await api.user.login(data)

    // 假设 res.data 包含用户信息 (根据你的实际接口结构调整)
    if (res.data) {
      // 1. 保存用户信息到状态
      userInfo.value = res.data
      // 2. 可以选择存入 localStorage 持久化 (可选)
      // localStorage.setItem('user', JSON.stringify(res.data))
      console.log('登录成功，已切换至用户卡片')
    }
  } catch (error) {
    console.error('登录失败', error)
    // 可以在这里添加错误提示
  }
}

/**
 * 处理注册逻辑
 */
const handleRegisterSend = async (data) => {
  console.log('触发注册发送', data)
  try {
    const res = await api.user.register(data)
    // 注册成功后的逻辑：
    // 选项A: 提示注册成功，请登录 (不切换视图)
    // 选项B: 注册成功后自动登录 (如下所示)
    if (res.data) {
      userInfo.value = res.data
      console.log('注册成功并自动登录')
    }
  } catch (error) {
    console.error('注册失败', error)
  }
}

/**
 * 处理修改用户名
 */
const handleUpdateUsername = async (data) => {
  console.log('请求修改用户名:', data)
  // await api.user.updateName(data)
  // 乐观更新：直接更新本地状态，无需重新请求用户信息
  userInfo.value = { ...userInfo.value, username: data.username }
}

/**
 * 处理修改密码
 */
const handleUpdatePassword = async (data) => {
  console.log('请求修改密码:', data)
  // await api.user.updatePwd(data)
  // 通常修改密码后不需要切换视图，提示成功即可
}

/**
 * 处理退出登录
 */
const handleLogout = () => {
  // 1. 清空状态，视图会自动切回登录页
  userInfo.value = null
  // 2. 清除持久化数据 (如果有)
  // localStorage.removeItem('user')
  // 3. 可能需要调用后端的 logout 接口
  console.log('已退出登录')
}
</script>

<style scoped>
.user-index-wrapper {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 60vh;  /* 最小高度保障 */
  display: flex;
  justify-content: center;
  align-items: center;
}
</style>
