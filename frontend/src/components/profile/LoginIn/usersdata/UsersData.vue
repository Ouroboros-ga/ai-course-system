<template>
  <div>
    <!-- 1. 引入用户卡片组件 -->
    <UserCard
      @logout="handleLogout"
    />

    <!-- 2. 引入菜单网格组件 -->
    <MenuGrid
      @openSettings="handleOpenSettings"
      @openPreference="handleOpenPreference"
      @myCourses="handleMyCourses"
      @logout="handleLogout"
    />
  </div>
</template>

<script setup>
import UserCard from '../usercard/UserCard.vue'
import MenuGrid from '../menu/MenuGrid.vue'

// 定义事件
const emit = defineEmits(['openSettings', 'openPreference', 'myCourses', 'logout'])

const handleOpenSettings = () => {
  emit('openSettings')
}

const handleOpenPreference = () => {
  emit('openPreference')
}

const handleMyCourses = () => {
  emit('myCourses')
}

const handleLogout = () => {
  emit('logout')
}
</script>

<style scoped>
/* 样式由UserIndex.vue中的profile-content控制 */
</style>
