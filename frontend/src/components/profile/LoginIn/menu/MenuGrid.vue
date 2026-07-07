<template>
  <div class="menu-grid-card">
    <div class="menu-grid">
      <div class="menu-item" @click="handleOpenSettings">
        <span class="icon"><Settings :size="24" /></span>
        <span class="text">账户设置</span>
      </div>
      <div class="menu-item" @click="handleOpenPreference">
        <span class="icon"><Palette :size="24" /></span>
        <span class="text">学习偏好</span>
      </div>
      <div class="menu-item" @click="handleMyCourses">
        <span class="icon"><BookOpen :size="24" /></span>
        <span class="text">我的课程</span>
      </div>
      <div class="menu-item" @click="handleLogout">
        <span class="icon"><LogOut :size="24" /></span>
        <span class="text">退出登录</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Settings, Palette, BookOpen, LogOut } from 'lucide-vue-next'

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
  background: var(--color-surface);
  border-radius: var(--radius-xl);
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-lg);
}

.menu-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  grid-template-rows: repeat(2, 1fr);
  gap: var(--space-4);
}

.menu-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-5) var(--space-5);
  background: var(--color-surface-2);
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: all var(--duration-normal) var(--ease);
}

.menu-item:hover {
  background: var(--color-primary-light);
  transform: translateY(-2px);
}

.menu-item .icon {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-primary);
  margin-bottom: var(--space-2);
}

.menu-item .text {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

@media (max-width: 768px) {
  .menu-grid {
    grid-template-columns: 1fr;
    grid-template-rows: auto;
  }

  .menu-grid-card {
    padding: var(--space-5);
  }
}
</style>
