<script setup>
import { computed, ref } from 'vue'
import { useCounterStore } from '@/stores/counter.js'
import {
  GraduationCap,
  Users,
  BookOpen,
  Home as HomeIcon,
  Info,
  User,
  Menu,
  X,
} from 'lucide-vue-next'

const counter = useCounterStore()
const mobileMenuOpen = ref(false)

const navItems = computed(() => {
  const baseItems = [
    { path: '/', label: '首页', icon: HomeIcon },
    { path: '/about', label: '关于', icon: Info },
  ]

  if (!counter.isLoggedIn) {
    return [
      ...baseItems,
      { path: '/profile', label: '个人中心', icon: User },
    ]
  }

  if (counter.isAdmin) {
    return [
      ...baseItems,
      // Teacher and student workspaces enforce their respective roles, and
      // their backing APIs do the same. Do not surface links that always
      // redirect an administrator away from the intended destination.
      { path: '/admin', label: '系统管理', icon: Users },
      { path: '/profile', label: '个人中心', icon: User },
    ]
  }

  if (counter.isTeacher) {
    return [
      ...baseItems,
      { path: '/teacher', label: '智课管理', icon: BookOpen },
      { path: '/profile', label: '个人中心', icon: User },
    ]
  }

  if (counter.isStudent) {
    return [
      ...baseItems,
      { path: '/student', label: '课程大厅', icon: BookOpen },
      { path: '/profile', label: '个人中心', icon: User },
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

const toggleMobileMenu = () => {
  mobileMenuOpen.value = !mobileMenuOpen.value
}

const closeMobileMenu = () => {
  mobileMenuOpen.value = false
}
</script>

<template>
  <div class="app-container">
    <nav class="navbar">
      <router-link to="/" class="logo" @click="closeMobileMenu">
        <GraduationCap class="logo-icon" :size="24" />
        <span class="logo-text">Smartrab</span>
      </router-link>

      <!-- 桌面导航 -->
      <div class="nav-links">
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-item"
        >
          <component :is="item.icon" :size="18" class="nav-icon" />
          <span>{{ item.label }}</span>
        </router-link>
      </div>

      <!-- 移动端汉堡按钮 -->
      <button
        class="menu-toggle"
        :aria-label="mobileMenuOpen ? '关闭菜单' : '打开菜单'"
        @click="toggleMobileMenu"
      >
        <component :is="mobileMenuOpen ? X : Menu" :size="22" />
      </button>

      <!-- 用户徽章 -->
      <div v-if="counter.isLoggedIn" class="user-badge">
        <span class="role-tag" :class="{ 'admin-tag': counter.isAdmin }">{{ roleLabel }}</span>
        <span class="username">{{ counter.userData.username }}</span>
      </div>
    </nav>

    <!-- 移动端抽屉菜单 -->
    <Transition name="mobile-menu">
      <div v-if="mobileMenuOpen" class="mobile-menu">
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="mobile-nav-item"
          @click="closeMobileMenu"
        >
          <component :is="item.icon" :size="20" class="mobile-nav-icon" />
          <span>{{ item.label }}</span>
        </router-link>
      </div>
    </Transition>

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
  top: var(--space-2);
  left: var(--space-2);
  right: var(--space-2);
  z-index: var(--z-fixed);
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 var(--space-5);
  height: var(--navbar-height);
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-sm);
  flex-shrink: 0;
  transition: box-shadow var(--duration-normal) var(--ease);
}

.navbar:hover {
  box-shadow: var(--shadow-md);
}

.logo {
  font-size: var(--text-xl);
  font-weight: var(--font-extrabold);
  letter-spacing: -0.03em;
  color: var(--color-text);
  display: flex;
  align-items: center;
  gap: var(--space-2);
  text-decoration: none;
  flex-shrink: 0;
  cursor: pointer;
}

.logo-icon {
  color: var(--color-primary);
  transition: transform var(--duration-normal) var(--ease-spring);
}

.logo:hover .logo-icon {
  transform: scale(1.1) rotate(-5deg);
}

.logo:hover {
  color: var(--color-text);
}

.nav-links {
  display: flex;
  gap: var(--space-1);
  align-items: center;
  margin-left: auto;
}

.nav-item {
  text-decoration: none;
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  transition: var(--transition-color);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  white-space: nowrap;
}

.nav-item:hover {
  color: var(--color-primary);
  background: var(--color-primary-light);
}

.nav-item.router-link-active {
  color: var(--color-primary);
  background: var(--color-primary-light);
  font-weight: var(--font-semibold);
}

.nav-icon {
  flex-shrink: 0;
}

.menu-toggle {
  display: none;
  align-items: center;
  justify-content: center;
  padding: var(--space-2);
  border-radius: var(--radius-md);
  color: var(--color-text);
  cursor: pointer;
  transition: var(--transition-color);
}

.menu-toggle:hover {
  background: var(--color-surface-2);
}

.user-badge {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-3);
  background: var(--color-surface-2);
  border-radius: var(--radius-full);
  font-size: var(--text-sm);
  flex-shrink: 0;
}

.role-tag {
  padding: 2px var(--space-2);
  background: var(--gradient-primary);
  color: var(--color-text-inverse);
  border-radius: var(--radius-full);
  font-weight: var(--font-semibold);
  font-size: var(--text-xs);
}

.role-tag.admin-tag {
  background: var(--gradient-danger);
}

.username {
  color: var(--color-text-secondary);
  font-weight: var(--font-medium);
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.main-content {
  flex: 1;
  width: 100%;
  box-sizing: border-box;
  padding-top: calc(var(--navbar-height) + var(--space-4));
}

/* 移动端菜单 */
.mobile-menu {
  position: fixed;
  top: calc(var(--navbar-height) + var(--space-4));
  left: var(--space-2);
  right: var(--space-2);
  z-index: var(--z-fixed);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-lg);
  padding: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.mobile-nav-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  color: var(--color-text-secondary);
  font-size: var(--text-base);
  font-weight: var(--font-medium);
  text-decoration: none;
  transition: var(--transition-color);
  cursor: pointer;
}

.mobile-nav-item:hover,
.mobile-nav-item.router-link-active {
  color: var(--color-primary);
  background: var(--color-primary-light);
}

.mobile-nav-icon {
  flex-shrink: 0;
}

/* 过渡动画 */
.mobile-menu-enter-active,
.mobile-menu-leave-active {
  transition: opacity var(--duration-normal) var(--ease), transform var(--duration-normal) var(--ease);
}

.mobile-menu-enter-from,
.mobile-menu-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity var(--duration-fast) var(--ease);
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* 响应式 */
@media (max-width: 768px) {
  .navbar {
    padding: 0 var(--space-3);
    height: 48px;
  }

  .nav-links {
    display: none;
  }

  .menu-toggle {
    display: flex;
  }

  .logo-text {
    font-size: var(--text-base);
  }

  .user-badge {
    font-size: var(--text-xs);
    padding: 2px var(--space-2);
  }

  .username {
    max-width: 60px;
  }

  .main-content {
    padding-top: calc(48px + var(--space-3));
  }
}

/* 暗色模式导航栏 */
[data-theme="dark"] .navbar {
  background: rgba(30, 41, 59, 0.85);
}
</style>
