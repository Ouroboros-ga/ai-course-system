<template>
  <div class="base-user-card">
    <div class="user-header">
      <div class="avatar">
        <span>{{ userInfo.username ? userInfo.username.charAt(0).toUpperCase() : 'U' }}</span>
      </div>
      <div class="user-info">
        <h3 class="username">{{ userInfo.username || '未登录' }}</h3>
        <p class="user-id">ID: {{ userInfo.id || '...' }}</p>
      </div>
    </div>
    <button class="logout-btn" @click="handleLogout">退出登录</button>
  </div>
</template>

<script setup>
const props = defineProps({
  userInfo: {
    type: Object,
    default: () => ({
      id: '',
      username: 'Guest'
    })
  }
})

const emit = defineEmits(['logout'])

const handleLogout = () => {
  if (confirm('确定要退出登录吗？')) {
    emit('logout')
  }
}
</script>

<style scoped>
.base-user-card {
  width: 100%;
  padding: 30px;
  background: rgba(255, 255, 255, 0.95);
  border-radius: 24px;
  border: 1px solid rgba(255, 255, 255, 0.6);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
}
.user-header {
  display: flex;
  align-items: center;
  margin-bottom: 20px;
}
.avatar {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  display: flex;
  justify-content: center;
  align-items: center;
  color: #fff;
  font-size: 24px;
  font-weight: 600;
  margin-right: 16px;
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
}
.user-info .username {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #333;
}
.user-info .user-id {
  margin: 4px 0 0 0;
  font-size: 12px;
  color: #999;
}
.logout-btn {
  width: 100%;
  padding: 12px;
  background: transparent;
  border: 1px solid rgba(255, 100, 100, 0.3);
  border-radius: 12px;
  color: #ff6b6b;
  font-size: 15px;
  cursor: pointer;
  transition: all 0.3s ease;
}
.logout-btn:hover {
  background: rgba(255, 100, 100, 0.1);
  border-color: rgba(255, 100, 100, 0.5);
}
</style>
