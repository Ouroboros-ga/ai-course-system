<script setup>
import { ref } from 'vue'
import Login from './LoginIn/Login.vue'
import UserCard from './LoginIn/UserCard.vue'
import StatsCard from './LoginIn/StatsCard.vue'
import MenuGrid from './LoginIn/MenuGrid.vue'
import UserInfoCard from './LoginIn/UserInfoCard.vue'
import PreferenceSettings from './LoginIn/PreferenceSettings.vue'
import MyCourses from './LoginIn/MyCourses.vue' // 导入我的课程（不是学习偏好）

const userInfo = ref(null)
const showSettingsPanel = ref(false)
const showPreferencePanel = ref(false)
const showMyCoursesPanel = ref(false) // 控制我的课程面板（和学习偏好无关）

const courseCount = ref('')
const chatCount = ref('')
const studyMinutes = ref('')

const loadUserStats = () => {
  if (!userInfo.value) return
  setTimeout(() => {
    courseCount.value = Math.floor(Math.random() * 30 + 5)
    chatCount.value = Math.floor(Math.random() * 200 + 20)
    studyMinutes.value = Math.floor(Math.random() * 180 + 30)
  }, 300)
}

const handleLoginSend = async (data) => {
  try {
    const mockUser = { id: 1, username: data.username || 'Amq' }
    userInfo.value = mockUser
    loadUserStats()
  } catch (error) {
    console.error('登录失败', error)
  }
}

const handleRegisterSend = async (data) => {
  try {
    userInfo.value = { id: Date.now(), username: data.username }
    loadUserStats()
  } catch (error) {
    console.error('注册失败', error)
  }
}

const handleLogout = () => {
  userInfo.value = null
  showSettingsPanel.value = false
  showPreferencePanel.value = false
  showMyCoursesPanel.value = false // 退出时关闭我的课程
  courseCount.value = ''
  chatCount.value = ''
  studyMinutes.value = ''
}

// 打开我的课程（独立方法）
const handleOpenMyCourses = () => {
  showMyCoursesPanel.value = true
}

// 关闭我的课程
const handleCloseMyCourses = () => {
  showMyCoursesPanel.value = false
}

// 原有方法（学习偏好）
const handleOpenSettings = () => showSettingsPanel.value = true
const handleOpenPreference = () => showPreferencePanel.value = true
const handleSavePreference = (prefs) => {
  console.log('保存学习偏好:', prefs)
  localStorage.setItem('userPreferences', JSON.stringify(prefs))
}
const handleUpdateUsername = (data) => {
  userInfo.value = { ...userInfo.value, username: data.username }
  showSettingsPanel.value = false
}
const handleUpdatePassword = (data) => {
  console.log('密码已更新', data)
  showSettingsPanel.value = false
}
</script>

<template>
  <div class="user-index-wrapper">
    <Login
      v-if="!userInfo"
      class="login-modal"
      @loginSend="handleLoginSend"
      @registerSend="handleRegisterSend"
    />

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

    <!-- 账户设置面板 -->
    <Transition name="fade">
      <div v-if="userInfo && showSettingsPanel" class="settings-overlay" @click.self="showSettingsPanel = false">
        <UserInfoCard
          :userInfo="userInfo"
          @updateUsername="handleUpdateUsername"
          @updatePassword="handleUpdatePassword"
          @logout="handleLogout"
          @close="showSettingsPanel = false"
        />
      </div>
    </Transition>

    <!-- 学习偏好面板（原有，和我的课程无关） -->
    <Transition name="fade">
      <div v-if="userInfo && showPreferencePanel" class="settings-overlay" @click.self="showPreferencePanel = false">
        <PreferenceSettings
          @close="showPreferencePanel = false"
          @save="handleSavePreference"
        />
      </div>
    </Transition>

    <!-- 我的课程面板（独立，全新功能） -->
    <Transition name="fade">
      <div v-if="userInfo && showMyCoursesPanel" class="settings-overlay" @click.self="handleCloseMyCourses">
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
.fade-enter-active, .fade-leave-active {
  transition: opacity 0.3s ease;
}
.fade-enter-from, .fade-leave-to {
  opacity: 0;
}
</style>
