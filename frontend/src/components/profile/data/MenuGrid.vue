<template>
  <div class="menu-grid">
    <!-- 循环渲染菜单项 -->
    <div
      v-for="(item, index) in menuItems"
      :key="index"
      class="menu-card"
      @click="handleClick(item.action)"
    >
      <div class="card-icon-box" :style="{ background: item.gradient }">
        <span class="card-icon">{{ item.icon }}</span>
      </div>
      <div class="card-text">
        <h3>{{ item.title }}</h3>
        <p>{{ item.desc }}</p>
      </div>
      <div class="card-arrow">›</div>
    </div>
  </div>
</template>

<script setup>
const emit = defineEmits(['openSettings'])

// 菜单配置数据
const menuItems = [
  {
    title: '账户设置',
    desc: '管理个人资料、修改密码',
    icon: '⚙️',
    gradient: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
    action: 'settings'
  },
  {
    title: '安全中心',
    desc: '双因素认证、登录日志',
    icon: '🛡️',
    gradient: 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)',
    action: 'security'
  },
  {
    title: '偏好设置',
    desc: '主题、布局、消息通知',
    icon: '🎨',
    gradient: 'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)',
    action: 'preference'
  },
  {
    title: '开发者选项',
    desc: 'API 密钥与调试工具',
    icon: '💻',
    gradient: 'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)',
    action: 'dev'
  }
]

const handleClick = (action) => {
  if (action === 'settings') {
    emit('openSettings')
  } else {
    console.log(`点击了：${action}`)
    // 这里可以扩展其他菜单的点击逻辑
  }
}
</script>

<style scoped>
.menu-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 20px;
}

.menu-card {
  background: #fff;
  border-radius: 16px;
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 16px;
  cursor: pointer;
  transition: all 0.25s ease;
  box-shadow: 0 2px 10px rgba(0,0,0,0.03);
  border: 1px solid rgba(0,0,0,0.02);
}

.menu-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 8px 20px rgba(0,0,0,0.08);
}

.card-icon-box {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.card-icon { font-size: 24px; filter: drop-shadow(0 2px 4px rgba(0,0,0,0.1)); }

.card-text { flex: 1; }
.card-text h3 { margin: 0 0 4px; font-size: 16px; color: #333; font-weight: 600; }
.card-text p { margin: 0; font-size: 12px; color: #999; }

.card-arrow { font-size: 20px; color: #ccc; font-weight: 300; }

/* 移动端适配 */
@media (max-width: 768px) {
  .menu-grid {
    grid-template-columns: 1fr;
    gap: 15px;
  }
  .menu-card { padding: 18px; }
}
</style>
