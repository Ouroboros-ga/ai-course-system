<script setup>
// 无需额外逻辑
</script>

<template>
  <div class="app-container">
    <!-- 顶部导航栏 -->
    <nav class="navbar">
      <router-link to="/" class="logo">
        <span class="logo-icon">🦀</span>
        Smartarb
      </router-link>

      <div class="nav-links">
        <router-link to="/" class="nav-item">
          Home
        </router-link>
        <router-link to="/chat" class="nav-item">
          Chat
        </router-link>
        <router-link to="/about" class="nav-item">
          About
        </router-link>
        <router-link to="/document" class="nav-item">
          Document
        </router-link>
      </div>
    </nav>

    <!-- 主内容区域 -->
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
/*
  📌 提示：CSS 变量建议定义在全局样式中（如 App.vue 或 main.css）
  为确保本组件开箱即用，此处直接使用具体颜色值
*/


/* 🔷 导航栏样式 - 保持原有增强设计 */
.navbar {
  //position: sticky;
  top: 0;
  z-index: 100;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 2rem;

  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.95)),
    linear-gradient(135deg, rgba(14, 165, 233, 0.04), transparent 60%);

  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border-bottom: 1px solid #e2e8f0;
  position: relative;

  border-radius: 0;

  box-shadow:
    0 1px 3px rgba(0, 0, 0, 0.04),
    0 1px 2px rgba(14, 165, 233, 0.06),
    inset 0 1px 0 rgba(255, 255, 255, 0.6);

  transition: box-shadow 0.3s ease, background 0.3s ease;
}

/* 🌟 顶部渐变装饰线 */
.navbar::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(
    90deg,
    transparent,
    rgba(14, 165, 233, 0.6),
    rgba(56, 189, 248, 0.4),
    rgba(14, 165, 233, 0.6),
    transparent
  );
  opacity: 0.9;
  pointer-events: none;
}

/* 💎 底部边框高光 */
.navbar::after {
  content: '';
  position: absolute;
  bottom: -1px;
  left: 5%;
  right: 5%;
  height: 1px;
  background: linear-gradient(
    90deg,
    transparent,
    rgba(14, 165, 233, 0.5),
    rgba(14, 165, 233, 0.2),
    transparent
  );
  opacity: 0.7;
  border-radius: 2px;
  pointer-events: none;
}

.navbar:hover {
  box-shadow:
    2px 6px 12px rgba(0, 0, 0, 0.05),
    0 2px 4px rgba(14, 165, 233, 0.08),
    inset 0 1px 0 rgba(255, 255, 255, 0.8);
}

/* Logo 样式 */
.logo {
  font-size: 1.5rem;
  font-weight: 800;
  letter-spacing: -0.05em;
  color: #0f172a;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  text-shadow: 0 0 20px rgba(14, 165, 233, 0.1);
  cursor: pointer;

  text-decoration: none;
}

.logo-icon {
  font-size: 1.2rem;
  color: #0ea5e9;
  filter: drop-shadow(0 0 8px rgba(14, 165, 233, 0.4));
  transition: transform 0.3s ease;
  display: inline-block;
}

.logo:hover .logo-icon {
  transform: scale(1.05) rotate(2deg);
}

/* 导航链接容器 */
.nav-links {
  display: flex;
  gap: 0.5rem;
  background: transparent;
  padding: 0.25rem;
  border-radius: 10px;
}

/* 单个链接样式 */
.nav-item {
  text-decoration: none;
  color: #64748b;
  font-size: 0.95rem;
  font-weight: 500;
  padding: 0.5rem 1rem;
  border-radius: 8px;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  border: 1px solid transparent;
  background-clip: padding-box;
  cursor: pointer;
}

.nav-item:hover {
  color: #0ea5e9;
  background: linear-gradient(135deg, rgba(14, 165, 233, 0.06), rgba(14, 165, 233, 0.02));
  border-color: rgba(14, 165, 233, 0.15);
  box-shadow: 0 2px 8px rgba(14, 165, 233, 0.08);
  transform: translateY(-1px);
}

.nav-item.router-link-active {
  color: #0ea5e9;
  background: linear-gradient(135deg, rgba(14, 165, 233, 0.12), rgba(14, 165, 233, 0.05));
  border-color: rgba(14, 165, 233, 0.3);
  font-weight: 600;
  box-shadow:
    0 2px 6px rgba(14, 165, 233, 0.1),
    inset 0 1px 0 rgba(255, 255, 255, 0.4);
}

.nav-item.router-link-active::after {
  content: '';
  position: absolute;
  bottom: -1px;
  left: 1rem;
  right: 1rem;
  height: 2px;
  background: linear-gradient(90deg, #0ea5e9, #0284c7);
  border-radius: 2px;
  opacity: 0.9;
}

/* 主内容区域 */
.main-content {
  flex: 1;
  padding: 2.5rem;
  max-width: 1200px;
  margin: 0 auto;
  width: 100%;
  box-sizing: border-box;
}

/* 路由切换淡入淡出动画 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease, transform 0.3s ease;
}

.fade-enter-from {
  opacity: 0;
  transform: translateY(10px);
}

.fade-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}

/* 移动端适配 */
@media (max-width: 768px) {
  .navbar {
    flex-direction: column;
    gap: 1rem;
    padding: 1rem;
  }

  .nav-links {
    width: 100%;
    justify-content: center;
    flex-wrap: wrap;
  }

  .nav-item {
    padding: 0.4rem 0.8rem;
    font-size: 0.85rem;
  }

  .navbar::after {
    left: 10%;
    right: 10%;
  }
}
</style>
