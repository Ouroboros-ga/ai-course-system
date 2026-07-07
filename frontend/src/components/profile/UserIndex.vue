<script setup>
import { ref, onMounted } from 'vue'
import Login from './LoginIn/login/Login.vue'
import UserInfoCard from "./LoginIn/userinfo/UserInfoCard.vue"
import StatsCard from "./LoginIn/stats/StatsCard.vue"
import PreferenceSettings from "./LoginIn/preference/PreferenceSettings.vue"
import MyCourses from "./LoginIn/courses/MyCourses.vue"
import TeacherAvatarSetting from './LoginIn/menu/TeacherAvatarSetting.vue'
import api from '@/api/index.js'
import { showToast } from '@/utils/toast'
import { Settings, Palette, BookOpen, LogOut, Bot } from 'lucide-vue-next'

import { useCounterStore } from '@/stores/counter.js'
const counter = useCounterStore()

// 控制是否显示设置面板
const showSettingsPanel = ref(false)
const showPreferencePanel = ref(false)
const showMyCoursesPanel = ref(false)
const avatarModalVisible = ref(false)

// 统计数据
const courseCount = ref(0)
const chatCount = ref(0)
const studyMinutes = ref(0)

// --- 页面加载时恢复登录状态 ---
onMounted(() => {
  counter.checkAuth()
  const id = localStorage.getItem('userId')
  const username = localStorage.getItem('username')

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

// 1. 登录成功
const handleLoginSend = async (data) => {
  try {
    const res = await api.user.login(data)
    localStorage.setItem('token', res.token)
    localStorage.setItem('userId', res.userInfo.id)
    localStorage.setItem('username', res.userInfo.username || data.username)
    localStorage.setItem('userRole', res.userInfo.role)

    counter.setAuth({
      token: res.token,
      userInfo: {
        id: res.userInfo.id,
        username: res.userInfo.username || data.username
      },
      role: res.userInfo.role
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
    localStorage.setItem('token', res.token)
    localStorage.setItem('userId', res.userInfo.id)
    localStorage.setItem('username', res.userInfo.username || data.username)
    localStorage.setItem('userRole', res.userInfo.role)

    counter.setAuth({
      token: res.token,
      userInfo: {
        id: res.userInfo.id,
        username: res.userInfo.username || data.username
      },
      role: res.userInfo.role
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

// 6. 打开教师数字人设置
const handleOpenAvatarSetting = () => {
  avatarModalVisible.value = true
}

// 7. 关闭偏好设置
const handleClosePreference = () => {
  showPreferencePanel.value = false
}

// 8. 关闭我的课程
const handleCloseMyCourses = () => {
  showMyCoursesPanel.value = false
}

// 9. 保存学习偏好
const handleSavePreference = (prefs) => {
  console.log('保存学习偏好:', prefs)
  localStorage.setItem('userPreferences', JSON.stringify(prefs))
  showPreferencePanel.value = false
}

// 10. 更新用户名
const handleUpdateUsername = async (data) => {
  try {
    const params = {
      id: counter.userData.id,
      username: counter.userData.username,
      password: data.oldPassword,
      newUsername: data.username,
      newPassword: "",
    }
    const res = await api.user.modify(params)
    localStorage.setItem('token', res.token)
    localStorage.setItem('username', res.userInfo.username)
    counter.userData.username = res.userInfo.username
    showToast("用户名修改成功", "success")
    showSettingsPanel.value = false
  } catch (error) {
    console.error('更新用户名失败', error)
    showToast(error || "修改失败", "error")
  }
}

// 11. 更新密码
const handleUpdatePassword = async (data) => {
  try {
    const params = {
      id: counter.userData.id,
      username: counter.userData.username,
      password: data.oldPassword,
      newPassword: data.newPassword,
      newUsername: "",
    }
    const res = await api.user.modify(params)
    localStorage.setItem('token', res.token)
    showToast("密码修改成功", "success")
    showSettingsPanel.value = false
  } catch (error) {
    console.error('更新密码失败', error)
    showToast(error || "修改失败", "error")
  }
}

// 12. 退出登录
const handleLogout = () => {
  localStorage.removeItem('userId')
  localStorage.removeItem('username')
  localStorage.removeItem('userPreferences')
  counter.clearAuth()
  showSettingsPanel.value = false
  showPreferencePanel.value = false
  showMyCoursesPanel.value = false
  avatarModalVisible.value = false
  courseCount.value = 0
  chatCount.value = 0
  studyMinutes.value = 0
}
</script>

<template>
  <div class="user-index-wrapper">
    <Login
      v-if="!counter.userData.id"
      class="login-modal"
      @loginSend="handleLoginSend"
      @registerSend="handleRegisterSend"
    />

    <div v-else class="profile-content">
      <div class="user-card">
        <div class="user-info">
          <div class="avatar">{{ counter.userData.username[0].toUpperCase() }}</div>
          <div>
            <div class="username">{{ counter.userData.username }}</div>
            <div class="user-id">ID: {{ counter.userData.id }}</div>
          </div>
        </div>
        <button class="logout-btn" @click="handleLogout">
          <LogOut :size="18" />
          退出登录
        </button>
      </div>

      <StatsCard :userStats="{ courseCount, chatCount, studyMinutes }" />

      <div class="menu-grid">
        <div class="menu-item" @click="handleOpenSettings">
          <div class="menu-icon menu-icon--primary">
            <Settings :size="28" />
          </div>
          <div>账户设置</div>
        </div>
        <div class="menu-item" @click="handleOpenPreference">
          <div class="menu-icon menu-icon--secondary">
            <Palette :size="28" />
          </div>
          <div>学习偏好</div>
        </div>
        <div class="menu-item" @click="handleMyCourses">
          <div class="menu-icon menu-icon--info">
            <BookOpen :size="28" />
          </div>
          <div>我的课程</div>
        </div>
        <div class="menu-item" @click="handleLogout">
          <div class="menu-icon menu-icon--danger">
            <LogOut :size="28" />
          </div>
          <div>退出登录</div>
        </div>
        <div class="menu-item" @click="handleOpenAvatarSetting">
          <div class="menu-icon menu-icon--warning">
            <Bot :size="28" />
          </div>
          <div>教师数字人设置</div>
        </div>
      </div>
    </div>

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

    <Transition name="fade">
      <div v-if="counter.userData.id && showPreferencePanel" class="settings-overlay" @click.self="showPreferencePanel = false">
        <PreferenceSettings
          @close="handleClosePreference"
          @save="handleSavePreference"
        />
      </div>
    </Transition>

    <Transition name="fade">
      <div v-if="counter.userData.id && showMyCoursesPanel" class="settings-overlay" @click.self="handleCloseMyCourses">
        <MyCourses @close="handleCloseMyCourses" />
      </div>
    </Transition>

    <TeacherAvatarSetting
      v-model:visible="avatarModalVisible"
    />
  </div>
</template>

<style scoped>
.user-index-wrapper {
  width: 100%;
  height: calc(100vh - var(--navbar-height));
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
  gap: var(--space-5);
  padding: var(--space-7) var(--space-5);
  box-sizing: border-box;
}

.user-card {
  background: var(--color-surface);
  padding: var(--space-6);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-sm);
  border: 1px solid var(--color-border);
}

.user-info {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  margin-bottom: var(--space-5);
}

.avatar {
  width: 60px;
  height: 60px;
  border-radius: var(--radius-full);
  background: var(--gradient-primary);
  color: var(--color-text-inverse);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-2xl);
  font-weight: var(--font-bold);
  flex-shrink: 0;
}

.username {
  font-size: var(--text-xl);
  font-weight: var(--font-semibold);
  color: var(--color-text);
}

.user-id {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  margin-top: var(--space-1);
}

.logout-btn {
  width: 100%;
  padding: var(--space-3);
  border: 1px solid var(--color-danger);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  color: var(--color-danger);
  font-size: var(--text-base);
  font-family: var(--font-sans);
  font-weight: var(--font-medium);
  cursor: pointer;
  transition: background-color var(--duration-normal) var(--ease),
              border-color var(--duration-normal) var(--ease),
              color var(--duration-normal) var(--ease);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
}

.logout-btn:hover {
  background: var(--color-danger-light);
  border-color: var(--color-danger-hover);
  color: var(--color-danger-hover);
}

.menu-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  grid-template-rows: repeat(3, 1fr);
  gap: var(--space-4);
}

.menu-item {
  background: var(--color-surface);
  padding: var(--space-6) var(--space-4);
  border-radius: var(--radius-xl);
  text-align: center;
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  border: 1px solid var(--color-border);
  transition: transform var(--duration-normal) var(--ease),
              box-shadow var(--duration-normal) var(--ease);
}

.menu-item:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}

.menu-item:active {
  transform: translateY(0);
}

.menu-icon {
  width: 56px;
  height: 56px;
  border-radius: var(--radius-lg);
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto var(--space-2);
}

.menu-icon--primary {
  background: var(--color-primary-light);
  color: var(--color-primary);
}

.menu-icon--secondary {
  background: var(--color-secondary-light);
  color: var(--color-secondary);
}

.menu-icon--info {
  background: var(--color-info-light);
  color: var(--color-info);
}

.menu-icon--danger {
  background: var(--color-danger-light);
  color: var(--color-danger);
}

.menu-icon--warning {
  background: var(--color-warning-light);
  color: var(--color-warning);
}

.menu-item div:last-child {
  font-size: var(--text-base);
  font-weight: var(--font-medium);
  color: var(--color-text);
}

.settings-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: var(--z-modal);
}

.fade-enter-active, .fade-leave-active {
  transition: opacity var(--duration-normal) var(--ease);
}
.fade-enter-from, .fade-leave-to {
  opacity: 0;
}

/* --- 响应式 --- */
@media (max-width: 768px) {
  .profile-content {
    padding: var(--space-5) var(--space-4);
  }

  .menu-grid {
    grid-template-columns: 1fr;
    grid-template-rows: auto;
  }

  .user-card {
    padding: var(--space-5);
  }
}
</style>
