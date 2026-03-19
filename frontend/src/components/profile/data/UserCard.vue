<template>
  <div class="user-card">
    <!-- 顶部装饰渐变条 -->
    <div class="card-header-bg"></div>

    <div class="card-content">
      <div class="avatar-wrapper">
        <div class="avatar">
          <!-- 计算首字母 -->
          {{ userInfo.username ? userInfo.username.charAt(0).toUpperCase() : 'U' }}
        </div>
        <div class="status-dot"></div>
      </div>

      <div class="user-info">
        <h2 class="name">{{ userInfo.username || '未命名用户' }}</h2>
        <p class="role">系统管理员</p>
        <div class="id-badge">
          <span>ID: {{ userInfo.id }}</span>
        </div>
      </div>

      <!-- 退出按钮 -->
      <button class="logout-btn" @click="handleLogout">
        <span class="icon">🔌</span>
        <span>退出</span>
      </button>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  userInfo: {
    type: Object,
    default: () => ({ username: 'Guest', id: '...' })
  }
})

const emit = defineEmits(['logout'])

const handleLogout = () => {
  if(confirm('确定退出登录吗？')) {
    emit('logout')
  }
}
</script>

<style scoped>
/* 用户卡片样式 */
.user-card {
  background: #ffffff;
  border-radius: 20px;
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.05);
  overflow: hidden;
  position: relative;
}

.card-header-bg {
  height: 80px;
  background: linear-gradient(135deg, #a4b3ff 0%, #764ba2 100%);
  width: 100%;
}

.card-content {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  padding: 0 30px 30px 30px;
  margin-top: -40px;
}

.avatar-wrapper {
  position: relative;
}

.avatar {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  background: #fff;
  border: 4px solid #fff;
  color: #764ba2;
  font-size: 32px;
  font-weight: bold;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 5px 15px rgba(0,0,0,0.1);
}

.status-dot {
  position: absolute;
  bottom: 4px;
  right: 4px;
  width: 14px;
  height: 14px;
  background: #4ade80;
  border: 2px solid #fff;
  border-radius: 50%;
}

.user-info {
  flex: 1;
  padding-left: 20px;
  padding-bottom: 8px;
}

.user-info .name { margin: 0; font-size: 22px; font-weight: 700; color: #333; }
.user-info .role { margin: 8px 0 0; color: #666; font-size: 14px; }
.id-badge { margin-top: 8px; display: inline-block; background: #f0f2f5; padding: 2px 8px; border-radius: 4px; font-size: 12px; color: #888; }

.logout-btn {
  align-self: center;
  margin-top: 50px;
  padding: 8px 16px;
  background: transparent;
  border: 3px solid rgba(255, 100, 100, 0.3);
  border-radius: 8px;
  color: #ff6b6b;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.3s;
  display: flex;
  align-items: center;
  gap: 6px;
}
.logout-btn:hover { background: rgba(255, 100, 100, 0.1); border-color: #ff6b6b; }

/* 移动端适配 */
@media (max-width: 768px) {
  .card-content {
    flex-direction: column;
    align-items: center;
    text-align: center;
    padding: 0 20px 30px;
    margin-top: -50px;
  }
  .user-info { padding-left: 0; margin-top: 15px; }
  .logout-btn { margin-top: 20px; }
}
</style>
