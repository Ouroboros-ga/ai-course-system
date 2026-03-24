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
const emit = defineEmits(['openSettings', 'openPreference'])

// 👉 替换为贴合你项目的菜单配置
const menuItems = [
  {
    title: '我的课程与课件',
    desc: '快速进入课程AI智课，管理历史上传课件',
    icon: '🧑‍🏫',
    gradient: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
    action: 'courses'
  },
  {
    title: '账户安全',
    desc: '修改密码、查看登录记录，保障账号安全',
    icon: '🔐',
    gradient: 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)',
    action: 'settings' // 沿用原有的 settings 逻辑，触发修改用户名/密码
  },
  {
    title: '学习偏好',
    desc: '自定义语音播报、通知、界面风格',
    icon: '⚙️',
    gradient: 'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)',
    action: 'preference'
  },
  {
    title: '学习数据中心',
    desc: '查看学习进度、问答统计，导出学习报告',
    icon: '📊',
    gradient: 'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)',
    action: 'stats'
  }
]

const handleClick = (action) => {
  if (action === 'settings') {
    emit('openSettings')
  } else if (action === 'preference') {
    emit('openPreference')
  } else {
    console.log(`点击了：${action}`)
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
