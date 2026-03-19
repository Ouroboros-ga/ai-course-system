<template>
  <div class="profile-page">
    <div class="profile-container">

      <!-- 1. 引入用户卡片组件 -->
      <UserCard
        :userInfo="userInfo"
        @logout="handleLogout"
      />

      <!-- 2. 引入菜单网格组件 -->
      <MenuGrid
        @openSettings="handleOpenSettings"
      />

      <!-- 3. 底部版权 -->
      <div class="footer">
        <p>泛雅智能教学平台 · 企业版 v2.4.1</p>
        <p class="copyright">© 2026 泛雅科技 保留所有权利</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import UserCard from './data/UserCard.vue'
import MenuGrid from './data/MenuGrid.vue'

// 接收父组件传递的数据
const props = defineProps({
  userInfo: {
    type: Object,
    default: () => ({ username: 'Guest' })
  }
})

// 定义事件
const emit = defineEmits(['openSettings', 'logout'])

const handleOpenSettings = () => {
  emit('openSettings')
}

const handleLogout = () => {
  emit('logout')
}
</script>

<style scoped>
/* --- 基础布局 --- */
.profile-page {
  width: 100%;
  min-height: 100vh;
  padding: 40px 20px;
  box-sizing: border-box;
  display: flex;
  justify-content: center;
  background-color: #f4f6f9; /* 浅灰背景 */
  font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
}

.profile-container {
  max-width: 900px;
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

/* --- 底部样式 --- */
.footer {
  text-align: center;
  padding-top: 20px;
  color: #aaa;
  font-size: 13px;
}

.copyright {
  font-size: 12px;
  margin-top: 5px;
  color: #ccc;
}

/* 移动端适配 */
@media (max-width: 768px) {
  .profile-page {
    padding: 20px 15px;
  }
}
</style>
