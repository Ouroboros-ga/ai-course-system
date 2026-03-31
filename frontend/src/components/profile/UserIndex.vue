<script setup>
import { ref, onMounted } from 'vue'
import Login from './LoginIn/login/Login.vue'
import UserInfoCard from "./LoginIn/userinfo/UserInfoCard.vue"
import StatsCard from "./LoginIn/stats/StatsCard.vue"
import PreferenceSettings from "./LoginIn/preference/PreferenceSettings.vue"
import MyCourses from "./LoginIn/courses/MyCourses.vue"
import api from '@/api/index.js'
import { showToast } from '@/utils/toast'

import { useCounterStore } from '@/stores/counter.js'
const counter = useCounterStore()

// 控制是否显示设置面板
const showSettingsPanel = ref(false)
const showPreferencePanel = ref(false)
const showMyCoursesPanel = ref(false)

// 统计数据
const courseCount = ref(0)
const chatCount = ref(0)
const studyMinutes = ref(0)

// --- 页面加载时恢复登录状态 ---
onMounted(() => {
  counter.checkAuth()
  const id = localStorage.getItem('userId')
  const username = localStorage.getItem('username')

  // 如果本地有数据且 Store 为空，则恢复
  if (counter.token && id && !counter.userData.id) {
    counter.userData.id = id
    counter.userData.username = username
    loadUserStats()
  }
})

// 加载统计数据
const loadUserStats = () => {
  if (!counter.userData.id) return
  setTimeout(() => {
    courseCount.value = Math.floor(Math.random() * 30 + 5)
    chatCount.value = Math.floor(Math.random() * 200 + 20)
    studyMinutes.value = Math.floor(Math.random() * 180 + 30)
  }, 300)
}

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
    counter.setAuth({
      token: res.token,
      userInfo: {
        id: res.userInfo.id,
        username: data.username
      }
    })

    showToast("登录成功", "success")
    loadUserStats()
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
    counter.setAuth({
      token: res.token,
      userInfo: {
        id: res.userInfo.id,
        username: data.username
      }
    })

    showToast("注册成功并自动登录", "success")
    loadUserStats()
  } catch (error) {
    console.error('注册失败', error)
    showToast(error || "错误", "error")
  }
}

// 3. 打开设置面板
const handleOpenSettings = () => {
  showSettingsPanel.value = true
}

// 4. 打开偏好设置
const handleOpenPreference = () => {
  showPreferencePanel.value = true
}

// 5. 打开我的课程
const handleMyCourses = () => {
  showMyCoursesPanel.value = true
}

// 6. 关闭偏好设置
const handleClosePreference = () => {
  showPreferencePanel.value = false
}

// 7. 关闭我的课程
const handleCloseMyCourses = () => {
  showMyCoursesPanel.value = false
}

// 8. 保存学习偏好
const handleSavePreference = (prefs) => {
  console.log('保存学习偏好:', prefs)
  localStorage.setItem('userPreferences', JSON.stringify(prefs))
  showPreferencePanel.value = false
}

// 9. 更新用户名 (严格适配接口文档)
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

// 10. 更新密码 (严格适配接口文档)
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

// 11. 退出登录
const handleLogout = () => {
  // 清除所有相关缓存
  localStorage.removeItem('userId')
  localStorage.removeItem('username')
  localStorage.removeItem('userPreferences')

  // 重置 Store
  counter.clearAuth()
  showSettingsPanel.value = false
  showPreferencePanel.value = false
  showMyCoursesPanel.value = false

  // 重置统计数据
  courseCount.value = 0
  chatCount.value = 0
  studyMinutes.value = 0
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

    <!-- 2. 已登录状态：顺序 = 用户 → 统计 → 四个方格 -->
    <div v-else class="profile-content">
      <!-- 1. 用户卡片（只保留头像+ID+退出登录，去掉内部四个格子） -->
      <div class="user-card">
        <div class="user-info">
          <div class="avatar">{{ counter.userData.username[0].toUpperCase() }}</div>
          <div>
            <div class="username">{{ counter.userData.username }}</div>
            <div class="user-id">ID: {{ counter.userData.id }}</div>
          </div>
        </div>
        <button class="logout-btn" @click="handleLogout">退出登录</button>
      </div>

      <!-- 2. 统计卡片（3个数字） -->
      <StatsCard :userStats="{ courseCount, chatCount, studyMinutes }" />

      <!-- 3. 四个方格子菜单（带图标，和你原来的样式一致） -->
      <div class="menu-grid">
        <div class="menu-item" @click="handleOpenSettings">
          <div class="menu-icon">⚙️</div>
          <div>账户设置</div>
        </div>
        <div class="menu-item" @click="handleOpenPreference">
          <div class="menu-icon">🎨</div>
          <div>学习偏好</div>
        </div>
        <div class="menu-item" @click="handleMyCourses">
          <div class="menu-icon">📚</div>
          <div>我的课程</div>
        </div>
        <div class="menu-item" @click="handleLogout">
          <div class="menu-icon">🚪</div>
          <div>退出登录</div>
        </div>
      </div>
    </div>

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

    <!-- 4. 学习偏好 -->
    <Transition name="fade">
      <div v-if="counter.userData.id && showPreferencePanel" class="settings-overlay" @click.self="showPreferencePanel = false">
        <PreferenceSettings
          @close="handleClosePreference"
          @save="handleSavePreference"
        />
      </div>
    </Transition>

    <!-- 5. 我的课程 -->
    <Transition name="fade">
      <div v-if="counter.userData.id && showMyCoursesPanel" class="settings-overlay" @click.self="handleCloseMyCourses">
        <MyCourses @close="handleCloseMyCourses" />
      </div>
    </Transition>

  </div>
</template>

<style scoped>
.user-index-wrapper {
  width: 100%;
  height: 100vh;
  position: relative;
  display: flex;
  justify-content: center;
  align-items: center;
}

.profile-content {
  max-width: 900px;
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 40px 20px;
  box-sizing: border-box;
}

/* 用户卡片样式（替代原来的 UsersData，只保留头像+ID+退出） */
.user-card {
  background: white;
  padding: 24px;
  border-radius: 16px;
  box-shadow: 0 2px 10px rgba(0,0,0,0.05);
}
.user-info {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
}
.avatar {
  width: 60px;
  height: 60px;
  border-radius: 50%;
  background: #6366f1;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  font-weight: bold;
}
.username {
  font-size: 20px;
  font-weight: 600;
}
.user-id {
  font-size: 14px;
  color: #666;
}
.logout-btn {
  width: 100%;
  padding: 12px;
  border: 1px solid #f43f5e;
  border-radius: 12px;
  background: white;
  color: #f43f5e;
  font-size: 16px;
  cursor: pointer;
}

/* 四个方格子菜单（带图标，和你原来的样式一致） */
.menu-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.menu-item {
  background: white;
  padding: 24px 16px;
  border-radius: 16px;
  text-align: center;
  cursor: pointer;
  box-shadow: 0 2px 10px rgba(0,0,0,0.05);
  transition: transform 0.2s;
}
.menu-item:active {
  transform: scale(0.97);
}
.menu-icon {
  font-size: 28px;
  margin-bottom: 8px;
}
.menu-item div:last-child {
  font-size: 15px;
  font-weight: 500;
  color: #333;
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
