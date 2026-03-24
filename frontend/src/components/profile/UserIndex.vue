<script setup>
import { ref, onMounted } from 'vue'
import Login from './LoginIn/Login.vue'
import UserCard from './LoginIn/UserCard.vue'
import StatsCard from './LoginIn/StatsCard.vue'
import MenuGrid from './LoginIn/MenuGrid.vue'
import UserInfoCard from './LoginIn/UserInfoCard.vue'
import PreferenceSettings from './LoginIn/PreferenceSettings.vue'
import MyCourses from './LoginIn/MyCourses.vue'

// 登录状态
const userInfo = ref(null)

// 面板控制
const showSettingsPanel = ref(false)
const showPreferencePanel = ref(false)
const showMyCoursesPanel = ref(false)

// 统计数据（统一数字类型，消除TS警告）
const courseCount = ref(0)
const chatCount = ref(0)
const studyMinutes = ref(0)

// 页面加载时自动恢复登录（刷新不掉态）
onMounted(() => {
  const savedUser = localStorage.getItem('userInfo')
  if (savedUser) {
    userInfo.value = JSON.parse(savedUser)
    loadUserStats()
  }
})

// 加载统计数据
const loadUserStats = () => {
  if (!userInfo.value) return
  setTimeout(() => {
    courseCount.value = Math.floor(Math.random() * 30 + 5)
    chatCount.value = Math.floor(Math.random() * 200 + 20)
    studyMinutes.value = Math.floor(Math.random() * 180 + 30)
  }, 300)
}

// 登录
const handleLoginSend = async (data) => {
  try {
    const mockUser = { id: 1, username: data.username || 'Amq' }
    userInfo.value = mockUser
    localStorage.setItem('userInfo', JSON.stringify(mockUser)) // 持久化
    loadUserStats()
  } catch (error) {
    console.error('登录失败', error)
  }
}

// 注册
const handleRegisterSend = async (data) => {
  try {
    const newUser = { id: Date.now(), username: data.username }
    userInfo.value = newUser
    localStorage.setItem('userInfo', JSON.stringify(newUser))
    loadUserStats()
  } catch (error) {
    console.error('注册失败', error)
  }
}

// 退出登录
const handleLogout = () => {
  userInfo.value = null
  showSettingsPanel.value = false
  showPreferencePanel.value = false
  showMyCoursesPanel.value = false

  courseCount.value = 0
  chatCount.value = 0
  studyMinutes.value = 0

  localStorage.removeItem('userInfo')
  localStorage.removeItem('userPreferences')
}

// 我的课程
const handleOpenMyCourses = () => {
  showMyCoursesPanel.value = true
}
const handleCloseMyCourses = () => {
  showMyCoursesPanel.value = false
}

// 设置面板
const handleOpenSettings = () => showSettingsPanel.value = true
const handleOpenPreference = () => showPreferencePanel.value = true

const handleSavePreference = (prefs) => {
  console.log('保存学习偏好:', prefs)
  localStorage.setItem('userPreferences', JSON.stringify(prefs))
}

const handleUpdateUsername = (data) => {
  userInfo.value.username = data.username
  localStorage.setItem('userInfo', JSON.stringify(userInfo.value))
  showSettingsPanel.value = false
}

const handleUpdatePassword = (data) => {
  console.log('密码已更新', data)
  showSettingsPanel.value = false
}
</script>

<template>
  <div class="user-index-wrapper">
    <!-- 未登录：登录页 -->
    <Login
      v-if="!userInfo"
      class="login-modal"
      @loginSend="handleLoginSend"
      @registerSend="handleRegisterSend"
    />

    <!-- 已登录：主页 -->
    <div v-else class="profile-content">
      <UserCard :userInfo="userInfo" @logout="handleLogout" />
      <StatsCard :userStats="{ courseCount, chatCount, studyMinutes }" />
      <MenuGrid
        @openSettings="handleOpenSettings"
        @openPreference="handleOpenPreference"
        @myCourses="handleOpenMyCourses"
        @logout="handleLogout"
      />
    </div>

    <!-- 账户设置 -->
    <Transition name="fade">
      <div v-if="showSettingsPanel" class="settings-overlay" @click.self="showSettingsPanel = false">
        <UserInfoCard
          :userInfo="userInfo"
          @updateUsername="handleUpdateUsername"
          @updatePassword="handleUpdatePassword"
          @logout="handleLogout"
          @close="showSettingsPanel = false"
        />
      </div>
    </Transition>

    <!-- 学习偏好 -->
    <Transition name="fade">
      <div v-if="showPreferencePanel" class="settings-overlay" @click.self="showPreferencePanel = false">
        <PreferenceSettings
          @close="showPreferencePanel.value = false"
          @save="handleSavePreference"
        />
      </div>
    </Transition>

    <!-- 我的课程 -->
    <Transition name="fade">
      <div v-if="showMyCoursesPanel" class="settings-overlay" @click.self="handleCloseMyCourses">
        <MyCourses @close="handleCloseMyCourses" />
      </div>
    </Transition>
  </div>
</template>

<!-- 动画必须放外面，否则不生效 & 报未使用 -->
<style>
.fade-enter-active, .fade-leave-active {
  transition: opacity 0.3s ease;
}
.fade-enter-from, .fade-leave-to {
  opacity: 0;
}
</style>

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
  gap: 24px;
  padding: 40px 20px;
  box-sizing: border-box;
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
</style>
