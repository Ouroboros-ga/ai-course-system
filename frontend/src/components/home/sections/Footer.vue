<template>
  <section class="slide end-page hero-page">
    <div class="content-box">
      <!-- 装饰元素（颜色更明显） -->
      <div class="decoration deco-1"></div>
      <div class="decoration deco-2"></div>

      <h2 class="main-title">立即开启你的 <span class="text-blue">AI 智课</span> 之旅</h2>
      <p class="description">免费试用，无需注册，即刻体验智能教学新方式</p>
      <div class="btn-group">
        <button class="use-btn" @click="$emit('go-chat')">立即使用</button>
      </div>
    </div>
    <!-- 底部版权栏 -->
    <footer class="footer-bar">
      <p>© 2026 Smartrab AI 智课 | 基于泛雅平台的智能教学系统</p>
      <div class="footer-links">
        <a href="#">关于我们</a>
        <a href="#">使用协议</a>
        <a href="#">隐私政策</a>
      </div>
    </footer>
  </section>
</template>

<style scoped>
.slide {
  width: 100%;
  height: calc(100vh - var(--navbar-height));
  scroll-snap-align: start;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 10%;
  position: relative;
  /* 隐藏浏览器自带的滚动指示器 */
  scrollbar-width: none; /* Firefox */
  -ms-overflow-style: none; /* IE/Edge */
}
.slide::-webkit-scrollbar {
  display: none; /* Chrome/Safari */
}
.hero-page {
  background: radial-gradient(circle at 20% 50%, rgba(59, 130, 246, 0.12), transparent 45%),
  radial-gradient(circle at 80% 80%, rgba(124, 58, 237, 0.08), transparent 40%),
  #f8fafc;
}
.content-box {
  text-align: center;
  max-width: 700px;
  position: relative;
}
.main-title {
  font-size: 3.2rem;
  font-weight: 800;
  line-height: 1.2;
  margin-bottom: 1.5rem;
  background: linear-gradient(90deg, #0f172a, #3b82f6, #8b5cf6);
  background-size: 200% 200%;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  animation: flow 6s ease infinite;
}
@keyframes flow {
  0% { background-position: 0 50%; }
  50% { background-position: 100% 50%; }
  100% { background-position: 0 50%; }
}
.text-blue {
  color: #3b82f6;
  -webkit-text-fill-color: #3b82f6;
  background: none;
}
.description {
  font-size: 1.2rem;
  color: #64748b;
  line-height: 1.6;
  margin-bottom: 2rem;
  text-align: center;
}
.btn-group {
  display: flex;
  gap: 1rem;
  justify-content: center;
}
.use-btn {
  padding: 1.2rem 3.2rem;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 14px;
  font-size: 1.15rem;
  font-weight: 600;
  cursor: pointer;
  transition: 0.3s;
  box-shadow: 0 8px 25px rgba(59, 130, 246, 0.25);
  position: relative;
  overflow: hidden;
}
.use-btn::after {
  content: '';
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent);
  transition: 0.5s;
}
.use-btn:hover::after { left: 100%; }
.use-btn:hover {
  background: #2563eb;
  transform: translateY(-3px);
  box-shadow: 0 14px 32px rgba(59, 130, 246, 0.35);
}

/* 装饰元素（颜色加深，更明显） */
.decoration {
  position: absolute;
  border-radius: 50%;
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.25), rgba(124, 58, 237, 0.25));
  z-index: 0;
}
.deco-1 {
  width: 140px;
  height: 140px;
  top: -70px;
  left: -70px;
  animation: float 6s ease-in-out infinite;
}
.deco-2 {
  width: 120px;
  height: 120px;
  bottom: -50px;
  right: -50px;
  animation: float 6s ease-in-out infinite reverse;
}
@keyframes float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-12px); }
}

/* 底部版权栏 */
.footer-bar {
  position: absolute;
  bottom: 2rem;
  left: 0;
  right: 0;
  text-align: center;
  color: #94a3b8;
  font-size: 0.9rem;
}
.footer-links {
  margin-top: 0.5rem;
  display: flex;
  gap: 1.5rem;
  justify-content: center;
}
.footer-links a {
  color: #94a3b8;
  text-decoration: none;
  transition: color 0.3s;
}
.footer-links a:hover { color: #3b82f6; }
</style>
