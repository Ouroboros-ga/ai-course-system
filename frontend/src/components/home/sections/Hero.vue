<template>
  <div class="hero-page slide">
    <div class="split-content">
      <div class="text-side">
        <h1 class="main-title">
          AI 智课
          <br />
          <span class="text-blue">
            <span style="animation-delay: 0.2s">实</span>
            <span style="animation-delay: 0.4s">时</span>
            <span style="animation-delay: 0.6s">互</span>
            <span style="animation-delay: 0.8s">动</span>
          </span>
        </h1>
        <p class="description">
          免费试用·重构课堂体验·智能课件·AI 答疑·一站式教学平台
        </p>
        <div class="btn-group">
          <button class="use-btn" @click="$emit('go-chat')">免费使用</button>
        </div>
      </div>

      <div class="visual-side">
        <div class="glass-hero">
          <div class="glass-card">
            <div class="glass-icon a">
              <div class="icon-file"></div>
            </div>
            <div class="glass-icon b">
              <div class="icon-chat"></div>
            </div>
            <div class="glass-icon c">
              <div class="icon-robot"></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
</script>

<style scoped>
.slide {
  width: 100%;
  height: calc(100vh - var(--navbar-height));
  scroll-snap-align: start;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 10%;
}

.hero-page {
  background: radial-gradient(circle at 20% 50%, rgba(59, 130, 246, 0.12), transparent 45%),
  radial-gradient(circle at 80% 80%, rgba(124, 58, 237, 0.08), transparent 40%),
  #f8fafc;
}

.split-content {
  display: flex;
  align-items: center;
  gap: 4rem;
  width: 100%;
  max-width: 1200px;
}

.text-side { flex:1; text-align:left; }
.visual-side { flex:1; display:flex; justify-content: center; }

.main-title {
  font-size: 3.5rem;
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
  0%{background-position:0 50%}
  50%{background-position:100% 50%}
  100%{background-position:0 50%}
}

.text-blue {
  color: #3b82f6 !important;
  -webkit-text-fill-color: #3b82f6 !important;
  background: none !important;
  display: inline-block;
}
.text-blue span {
  display: inline-block;
  opacity: 0;
  transform: translateY(12px);
  animation: wordFade 1.2s cubic-bezier(0.22, 0.46, 0.28, 1) forwards;
}
@keyframes wordFade {
  to { opacity: 1; transform: translateY(0); }
}

.description { font-size:1.2rem; color:#64748b; line-height:1.6; margin-bottom:2rem; }
.btn-group { display:flex; gap:1rem; justify-content: flex-start; }

.use-btn {
  padding: 1.2rem 3.2rem; background: #3b82f6; color: white; border:none; border-radius:14px;
  font-size:1.15rem; font-weight:600; cursor:pointer; transition:0.3s;
  box-shadow:0 8px 25px rgba(59,130,246,0.25); position:relative; overflow:hidden;
}
.use-btn::after { content:''; position:absolute; top:0; left:-100%; width:100%; height:100%;
  background:linear-gradient(90deg,transparent,rgba(255,255,255,0.2),transparent); transition:0.5s; }
.use-btn:hover::after { left:100%; }
.use-btn:hover { background:#2563eb; transform:translateY(-3px); box-shadow:0 14px 32px rgba(59,130,246,0.35); }

/* === 右侧玻璃卡片 入场 + 永久循环呼吸动画 === */
.glass-hero {
  width:100%; max-width:500px; height:380px; position:relative;
  display:flex; align-items:center; justify-content:center;
}
.glass-card {
  width:320px; height:320px; border-radius:24px;
  background:rgba(255,255,255,0.6); backdrop-filter:blur(10px);
  border:1px solid rgba(255,255,255,0.4);
  box-shadow:0 20px 60px rgba(59,130,246,0.1);
  display:flex; align-items:center; justify-content:center; gap:24px;

  /* 入场 → 结束后自动循环呼吸 */
  animation: glassEnter 1.2s ease forwards, floatBreath 6s ease-in-out infinite;
}

/* 小图标：入场 + 轻微浮动 */
.glass-icon {
  width:56px; height:56px; border-radius:14px;
  background:linear-gradient(135deg,#3b82f6,#8b5cf6);
  display: flex; align-items: center; justify-content: center;
  animation: iconPop 0.8s ease forwards, iconFloat 3s ease-in-out infinite;
}
.glass-icon.a { animation-delay:0.2s, 1.2s; }
.glass-icon.b { animation-delay:0.4s, 1.4s; }
.glass-icon.c { animation-delay:0.6s, 1.6s; }

/* 入场动画 */
@keyframes glassEnter {
  0%{transform:translateY(40px) scale(0.9); opacity:0;}
  100%{transform:translateY(0) scale(1); opacity:1;}
}
@keyframes iconPop {
  0%{transform:scale(0); opacity:0;}
  100%{transform:scale(1); opacity:1;}
}

/* 永久循环：卡片呼吸浮动 */
@keyframes floatBreath {
  0%,100%{ transform: translateY(0px) rotate(0deg); }
  50%{ transform: translateY(-6px) rotate(0.5deg); }
}

/* 永久循环：小图标上下微动 */
@keyframes iconFloat {
  0%,100%{ transform: translateY(0px); }
  50%{ transform: translateY(-4px); }
}

.icon-file {
  width: 24px; height: 30px; background:#fff; border-radius:3px;
  position:relative;
}
.icon-file::before {
  content:''; width:14px; height:2px; background:#fff;
  position:absolute; top:8px; left:5px;
}
.icon-file::after {
  content:''; width:14px; height:2px; background:#fff;
  position:absolute; top:16px; left:5px;
}

.icon-chat {
  width: 28px; height: 24px; background:#fff;
  border-radius:6px 6px 2px 6px;
  position:relative;
}
.icon-chat::after {
  content:''; position:absolute; bottom:-6px; right:10px;
  width:0; height:0;
  border-left:6px solid transparent;
  border-right:2px solid transparent;
  border-top:6px solid #fff;
}

.icon-robot {
  width: 26px; height: 26px; background:#fff; border-radius:6px;
  position:relative;
}
.icon-robot::before {
  content:''; width:6px; height:6px; background:#3b82f6; border-radius:50%;
  position:absolute; top:8px; left:5px;
}
.icon-robot::after {
  content:''; width:6px; height:6px; background:#3b82f6; border-radius:50%;
  position:absolute; top:8px; right:5px;
}

@media (max-width:768px) {
  .slide{height:auto; min-height:calc(100vh - var(--navbar-height)); padding:140px 20px 80px;}
  .split-content{flex-direction:column; gap:2.5rem; text-align:center;}
  .text-side{text-align:center;}
  .main-title{font-size:2.2rem; line-height:1.3;}
  .description{font-size:1rem; line-height:1.7;}
  .btn-group{justify-content:center;}
  .glass-hero{height:260px;}
  .glass-card{width:220px; height:220px;}
}
</style>
