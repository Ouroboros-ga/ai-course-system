<template>
  <div class="menu-grid-card">
    <div class="menu-grid">
      <div class="menu-item" @click="handleOpenSettings">
        <span class="icon">⚙️</span>
        <span class="text">账户设置</span>
      </div>
      <div class="menu-item" @click="handleOpenPreference">
        <span class="icon">🎨</span>
        <span class="text">学习偏好</span>
      </div>
      <div class="menu-item" @click="handleMyCourses">
        <span class="icon">📚</span>
        <span class="text">我的课程</span>
      </div>
      <div class="menu-item" @click="handleLogout">
        <span class="icon">🚪</span>
        <span class="text">退出登录</span>
      </div>
    </div>
  </div>
</template>

<script setup>
const emit = defineEmits(['openSettings', 'openPreference', 'myCourses', 'logout'])

const handleOpenSettings = () => emit('openSettings')
const handleOpenPreference = () => emit('openPreference')
const handleMyCourses = () => emit('myCourses')
const handleLogout = () => emit('logout')
</script>

<style scoped>
.menu-grid-card {
  width: 100%;
  padding: 30px;
  background: rgba(255, 255, 255, 0.95);
  border-radius: 24px;
  border: 1px solid rgba(255, 255, 255, 0.6);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
}

.menu-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  grid-template-rows: repeat(2, 1fr);
  gap: 16px;
}

.menu-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 24px 20px;
  background: rgba(0, 0, 0, 0.02);
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.menu-item:hover {
  background: rgba(102, 126, 234, 0.08);
  transform: translateY(-4px);
}

.menu-item .icon {
  font-size: 24px;
  color: #667eea;
  margin-bottom: 8px;
}

.menu-item .text {
  font-size: 14px;
  color: #444;
}
</style>
