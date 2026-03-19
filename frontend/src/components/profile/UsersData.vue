<!-- UsersData.vue -->
<script setup>
// 接收父组件传递的数据
const props = defineProps({
  userInfo: {
    type: Object,
    default: () => ({ username: 'Guest' })
  }
})

// 定义事件
const emit = defineEmits(['openSettings', 'logout'])

const openSettings = () => {
  emit('openSettings')
}

const handleLogout = () => {
  if(confirm('确定退出登录吗？')) {
    emit('logout')
  }
}
</script>

<template>
  <div class="profile-page">
    <div class="profile-container">
      <!-- 用户信息卡片 (动态数据) -->
      <div class="user-card">
        <div class="avatar">{{ userInfo.username ? userInfo.username.charAt(0).toUpperCase() : 'U' }}</div>
        <div class="user-info">
          <!-- 使用真实数据 -->
          <h2>{{ userInfo.username || '未命名用户' }}</h2>
          <p>系统用户 | ID: {{ userInfo.id }}</p>
          <span class="email">{{ userInfo.username }}@company.com</span>
        </div>

        <!-- 快捷退出按钮 -->
        <button class="logout-mini-btn" @click="handleLogout">退出</button>
      </div>

      <!-- 功能菜单 -->
      <div class="menu-grid">
        <!-- 点击触发打开设置面板 -->
        <div class="menu-card" @click="openSettings">
          <h3>账户设置</h3>
          <p>管理个人资料、修改密码</p>
        </div>

        <div class="menu-card">
          <h3>安全中心</h3>
          <p>双因素认证、登录日志</p>
        </div>

        <div class="menu-card">
          <h3>偏好设置</h3>
          <p>主题、布局、消息通知</p>
        </div>

        <div class="menu-card">
          <h3>开发者选项</h3>
          <p>API 密钥与调试工具</p>
        </div>
      </div>

      <!-- 底部版权 -->
      <div class="footer">
        <p>泛雅智能教学平台 · 企业版 v2.4.1</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 样式保持原样，新增小按钮样式 */
.logout-mini-btn {
  padding: 6px 12px;
  background: rgba(255, 100, 100, 0.1);
  border: 1px solid rgba(255, 100, 100, 0.2);
  border-radius: 6px;
  color: #ff6b6b;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.3s;
}
.logout-mini-btn:hover {
  background: rgba(255, 100, 100, 0.2);
}

/* ... 其他原有样式 ... */
.profile-page {
  width: 100%;
  min-height: 100vh;
  padding: 60px 20px; /* 调整 padding */
  display: flex;
  justify-content: center;
  box-sizing: border-box;
  background: transparent; /* 让背景透出 */
}
/* ... 保持剩余 CSS 不变 ... */
.menu-card {
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
}
.menu-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.08);
}
</style>
