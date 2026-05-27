<script setup>
import { computed } from 'vue'
import { useCounterStore } from '@/stores/counter.js'

const counter = useCounterStore()

const navItems = computed(() => {
  const baseItems = [
    { path: '/', label: '首页' },
    { path: '/about', label: '关于' },
  ]

  if (!counter.isLoggedIn) {
    return [
      ...baseItems,
      { path: '/profile', label: '个人中心' },
    ]
  }

  if (counter.isAdmin) {
    return [
      ...baseItems,
      { path: '/admin', label: '👥 用户管理', icon: '👥' },
      { path: '/teacher', label: '📚 智课管理', icon: '📚' },
      { path: '/student', label: '我的课程', icon: '' },
      { path: '/profile', label: '个人中心' },
    ]
  }

  if (counter.isTeacher) {
    return [
      ...baseItems,
      { path: '/teacher', label: '智课管理', icon: '' },
      { path: '/profile', label: '个人中心' },
    ]
  }

  if (counter.isStudent) {
    return [
      ...baseItems,
      { path: '/student', label: '课程大厅', icon: '' },
      { path: '/profile', label: '个人中心' },
    ]
  }

  return baseItems
})

const roleLabel = computed(() => {
  if (counter.isAdmin) return '管理员'
  if (counter.isTeacher) return '教师'
  if (counter.isStudent) return '学生'
  return ''
})
</script>

<template>
  <div class="app-container">
    <nav class="navbar">
      <router-link to="/" class="logo">
        <span class="logo-icon">🦀</span>
        Smartrab
      </router-link>

      <div class="nav-links">
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-item"
        >
          <span v-if="item.icon" class="nav-icon">{{ item.icon }}</span>
          {{ item.label }}
        </router-link>
      </div>

      <div v-if="counter.isLoggedIn" class="user-badge">
        <span class="role-tag" :class="{ 'admin-tag': counter.isAdmin }">{{ roleLabel }}</span>
        <span class="username">{{ counter.userData.username }}</span>
      </div>
    </nav>

    <main class="main-content">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<style scoped>
.app-container {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.navbar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 100;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 2rem;
  height: 56px;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border-bottom: 1px solid #e2e8f0;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  flex-shrink: 0;
}

.navbar::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: linear-gradient(90deg, #6366f1, #8b5cf6, #0ea5e9, #6366f1);
  pointer-events: none;
}

.logo {
  font-size: 1.4rem;
  font-weight: 800;
  letter-spacing: -0.03em;
  color: #0f172a;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  text-decoration: none;
  flex-shrink: 0;
}

.logo-icon {
  font-size: 1.1rem;
  color: #6366f1;
  transition: transform 0.3s ease;
  display: inline-block;
}

.logo:hover .logo-icon {
  transform: scale(1.1) rotate(5deg);
}

.nav-links {
  display: flex;
  gap: 4px;
  align-items: center;
  margin-left: auto;
}


.nav-item {
  text-decoration: none;
  color: #64748b;
  font-size: 0.9rem;
  font-weight: 500;
  padding: 6px 14px;
  border-radius: 8px;
  transition: all 0.2s ease;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
}

.nav-item:hover {
  color: #6366f1;
  background: rgba(99, 102, 241, 0.06);
}

.nav-item.router-link-active {
  color: #6366f1;
  background: rgba(99, 102, 241, 0.1);
  font-weight: 600;
}

.nav-icon {
  font-size: 0.95rem;
}

.user-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 12px;
  background: #f1f5f9;
  border-radius: 20px;
  font-size: 0.85rem;
  flex-shrink: 0;
}

.role-tag {
  padding: 2px 10px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: white;
  border-radius: 10px;
  font-weight: 600;
  font-size: 0.75rem;
}

.role-tag.admin-tag {
  background: linear-gradient(135deg, #dc2626, #ef4444);
}

.username {
  color: #374151;
  font-weight: 500;
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.main-content {
  flex: 1;
  width: 100%;
  box-sizing: border-box;
  padding-top: var(--navbar-height);
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

@media (max-width: 768px) {
  .navbar {
    flex-wrap: wrap;
    height: auto;
    padding: 8px 12px;
    gap: 8px;
  }

  .nav-links {
    order: 3;
    width: 100%;
    justify-content: center;
    flex-wrap: wrap;
    gap: 2px;
  }

  .nav-item {
    padding: 4px 8px;
    font-size: 0.8rem;
  }

  .user-badge {
    font-size: 0.75rem;
  }
}
</style>
