<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
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
const route = useRoute()
const mobileMenuOpen = ref(false)

const navItems = computed(() => {
  const baseItems = [
    { path: '/', label: '棣栭〉', icon: HomeIcon },
    { path: '/about', label: '鍏充簬', icon: Info },
  ]

  if (!counter.isLoggedIn) {
    return [
      ...baseItems,
      { path: '/profile', label: '涓汉涓績', icon: User },
    ]
  }

  if (counter.canManageUsers) {
    return [
      ...baseItems,
      { path: '/admin', label: '绯荤粺绠＄悊', icon: Users },
      { path: '/profile', label: '涓汉涓績', icon: User },
    ]
  }

  if (counter.canCreateCourses) {
    return [
      ...baseItems,
      { path: '/teacher', label: '鏅鸿绠＄悊', icon: BookOpen },
      { path: '/profile', label: '涓汉涓績', icon: User },
    ]
  }

  if (!counter.canCreateCourses) {
    return [
      ...baseItems,
      { path: '/student', label: '璇剧▼澶у巺', icon: BookOpen },
      { path: '/profile', label: '涓汉涓績', icon: User },
    ]
  }

  return baseItems
})

const roleLabel = computed(() => counter.canManageUsers ? '管理员' : '用户')

const toggleMobileMenu = () => {
  mobileMenuOpen.value = !mobileMenuOpen.value
}

const closeMobileMenu = () => {
  mobileMenuOpen.value = false
}

// 璺敱鍒囨崲鏃跺叧闂Щ鍔ㄧ鑿滃崟
watch(() => route.path, closeMobileMenu)

// Esc 鍏抽棴绉诲姩绔彍鍗�
function handleEsc(e) {
  if (e.key === 'Escape') closeMobileMenu()
}

onMounted(() => document.addEventListener('keydown', handleEsc))
onBeforeUnmount(() => document.removeEventListener('keydown', handleEsc))
</script>

<template>
  <div class="app-container">
    <nav class="navbar">
      <router-link to="/" class="logo" @click="closeMobileMenu">
        <GraduationCap class="logo-icon" :size="24" />
        <span class="logo-text">Smartrab</span>
      </router-link>

      <!-- 妗岄潰瀵艰埅 -->
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

      <!-- 绉诲姩绔眽鍫℃寜閽?-->
      <button
        class="menu-toggle"
        :aria-label="mobileMenuOpen ? '鍏抽棴鑿滃崟' : '鎵撳紑鑿滃崟'"
        :aria-expanded="mobileMenuOpen"
        @click="toggleMobileMenu"
      >
        <component :is="mobileMenuOpen ? X : Menu" :size="22" />
      </button>

      <!-- 鐢ㄦ埛寰界珷 -->
      <div v-if="counter.isLoggedIn" class="user-badge">
        <span class="role-tag" :class="{ 'admin-tag': counter.canManageUsers }">{{ roleLabel }}</span>
        <span class="username">{{ counter.userData.username }}</span>
      </div>
    </nav>

    <!-- 绉诲姩绔娊灞夎彍鍗?-->
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

/* sticky 鑰岄潪 fixed锛氫笉鑴辩鏂囨。娴侊紝涓嶉渶瑕?padding-top 琛ュ伩锛?   婊氬姩鏃惰嚜鐒跺惛闄勯《閮紝涓斾笉浜х敓鍐呭閬尅 */
.navbar {
  position: sticky;
  top: 0;
  z-index: var(--z-fixed);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-3);
  padding: 0 var(--space-5);
  height: var(--navbar-height);
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border-bottom: 1px solid var(--color-border);
  flex-shrink: 0;
  transition: box-shadow var(--duration-normal) var(--ease);
}

/* 婊氬姩鏃跺姞闃村奖澧炲己灞傜骇鎰?*/
.navbar:hover,
.navbar.is-scrolled {
  box-shadow: var(--shadow-sm);
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
  min-width: 0;
  box-sizing: border-box;
}

/* 绉诲姩绔彍鍗?*/
.mobile-menu {
  position: fixed;
  top: var(--navbar-height);
  left: 0;
  right: 0;
  z-index: var(--z-fixed);
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
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

/* 杩囨浮鍔ㄧ敾 */
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

/* 鍝嶅簲寮?*/
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

  .mobile-menu {
    top: 48px;
  }
}

/* 鏆楄壊妯″紡瀵艰埅鏍?*/
[data-theme="dark"] .navbar {
  background: rgba(30, 41, 59, 0.85);
}
</style>
