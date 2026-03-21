<script setup>
import { ref } from 'vue'
import Login from './LoginIn/Login.vue' // 若Login.vue在LoginIn文件夹下
import UserCard from './LoginIn/UserCard.vue'
import StatsCard from './LoginIn/StatsCard.vue'
import MenuGrid from './LoginIn/MenuGrid.vue'
import UserInfoCard from './LoginIn/UserInfoCard.vue'
import PreferenceSettings from './LoginIn/PreferenceSettings.vue'

// 其余逻辑代码保持不变
const userInfo = ref(null)
const showSettingsPanel = ref(false)
const showPreferencePanel = ref(false)

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
  courseCount.value = ''
  chatCount.value = ''
  studyMinutes.value = ''
}

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
        @logout="handleLogout"
      />
    </div>

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

    <Transition name="fade">
      <div v-if="userInfo && showPreferencePanel" class="settings-overlay" @click.self="showPreferencePanel = false">
        <PreferenceSettings
          @close="showPreferencePanel = false"
          @save="handleSavePreference"
        />
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
