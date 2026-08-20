<script setup>
/**
 * App Home Page — 精致首页（参考 DeepSeek，但更具特色）
 *
 * 特色：
 * - 分层动画进场：元素依次淡入上浮
 * - 精致磨砂卡片：毛玻璃 + 微妙边框光晕
 * - 快捷导航面板：智能显示用户的学习/建设状态
 * - 流畅交互反馈：hover 状态、光标跟随、平滑过渡
 */
import { onBeforeUnmount, onMounted, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useCounterStore } from '@/stores/counter.js'
import {
  BookOpenCheck,
  ArrowRight,
  Sparkles,
  GraduationCap,
  Compass,
  ChevronDown,
  BookOpen,
  Github,
  FileText,
  Loader2,
  Layers,
  Zap,
  Users,
} from 'lucide-vue-next'
import ParticleBackground from '@/components/home/ui/ParticleBackground.vue'
import { listFacadeCourses } from '@/api/facade.js'
import SfxButton from '@/app/ui/SfxButton.vue'

const router = useRouter()
const store = useCounterStore()

// 页脚真实链接：开源项目 / GitHub 外链地址（与仓库 remote 一致）
const GITHUB_URL = 'https://github.com/Ouroboros-ga/ai-course-system'
const GITHUB_ISSUES_URL = `${GITHUB_URL}/issues`

// ── 文档中心链接助手 ──────────────────────────────────────
function docRoute(file, name) {
  return { path: '/docs/view', query: { file, name } }
}

// ── 进场动画控制 ──────────────────────────────────────
const isReady = ref(false)

// ── 滚轮吸附（Hero ↔ 快捷面板） ──────────────────────
const rootRef = ref(null)
const quickAccessRef = ref(null)
let scrollEl = null
let snapLocked = false

function findScrollParent(el) {
  let p = el?.parentElement
  while (p) {
    const ov = getComputedStyle(p).overflowY
    if (ov === 'auto' || ov === 'scroll') return p
    p = p.parentElement
  }
  return document.scrollingElement || document.documentElement
}

function onWheel(e) {
  if (!scrollEl || !quickAccessRef.value) return
  if (snapLocked) {
    e.preventDefault()
    return
  }
  const quickTop = quickAccessRef.value.offsetTop
  const st = scrollEl.scrollTop
  if (e.deltaY > 12 && st < quickTop - 80) {
    e.preventDefault()
    snapLocked = true
    scrollEl.scrollTo({ top: quickTop, behavior: 'smooth' })
    setTimeout(() => (snapLocked = false), 800)
  } else if (e.deltaY < -12 && st > 60 && st <= quickTop + 80) {
    e.preventDefault()
    snapLocked = true
    scrollEl.scrollTo({ top: 0, behavior: 'smooth' })
    setTimeout(() => (snapLocked = false), 800)
  }
}

function scrollToQuickAccess() {
  if (!scrollEl || !quickAccessRef.value) return
  scrollEl.scrollTo({ top: quickAccessRef.value.offsetTop, behavior: 'smooth' })
}

function scrollToTop() {
  scrollEl?.scrollTo({ top: 0, behavior: 'smooth' })
}

// ── 继续学习数据 ──────────────────────────────────────
const continueStatus = ref('loading')
const continueList = ref([])
const continueError = ref('')

async function loadContinue() {
  continueStatus.value = 'loading'
  continueError.value = ''
  try {
    const data = await listFacadeCourses('learning')
    const list = Array.isArray(data?.items) ? data.items : []
    continueList.value = list.filter((c) => {
      const p = c.progress?.overall_progress
      return p != null && p > 0
    })
    continueStatus.value = continueList.value.length ? 'ready' : 'empty'
  } catch (err) {
    continueError.value = err?.message || '加载失败'
    continueStatus.value = 'error'
  }
}

const isLoggedIn = computed(() => store.isLoggedIn)

// ── 标语动态渐变效果 ──────────────────────────────────────
const glowTextRef = ref(null)
let glowGradientX = ref(0)

function onGlowTextMouseMove(e) {
  if (!glowTextRef.value) return
  const rect = glowTextRef.value.getBoundingClientRect()
  const x = e.clientX - rect.left
  const percentage = (x / rect.width) * 100
  glowGradientX.value = Math.max(0, Math.min(100, percentage))
}

function onGlowTextMouseLeave() {
  glowGradientX.value = 50 // 重置到中心
}

function formatLastStudy(iso) {
  if (!iso) return '最近活动未知'
  const time = new Date(iso)
  if (Number.isNaN(time.getTime())) return '最近活动未知'
  const diffDays = Math.floor((Date.now() - time.getTime()) / 86400000)
  if (diffDays <= 0) return '今天学过'
  if (diffDays === 1) return '昨天学过'
  if (diffDays < 30) return `${diffDays} 天前学过`
  return time.toLocaleDateString('zh-CN')
}

function enterCourse(course) {
  router.push(`/app/course/${course.course_id}/learn`)
}

function goLearning() {
  router.push('/app/courses/learning')
}

function goBuilding() {
  router.push('/app/courses/building')
}

function goHall() {
  router.push('/app/courses/hall')
}

function goLab() {
  router.push('/app/lab')
}

function goResources() {
  router.push('/app/resources')
}

onMounted(() => {
  scrollEl = findScrollParent(rootRef.value)
  window.addEventListener('wheel', onWheel, { passive: false })
  loadContinue()
  // 触发进场动画
  requestAnimationFrame(() => {
    isReady.value = true
  })
})
onBeforeUnmount(() => {
  window.removeEventListener('wheel', onWheel)
})
</script>

<template>
  <div ref="rootRef" class="sfx-home" :class="{ 'is-ready': isReady }">
    <!-- 粒子背景（sticky 固定于视口，内容从上方滚过） -->
    <div class="sfx-home-bg" aria-hidden="true">
      <ParticleBackground />
      <div class="sfx-home-bg__glow"></div>
    </div>

    <!-- ── 首屏 Hero ── -->
    <section class="sfx-home-hero">
      <!-- 天空蓝渐变层 -->
      <div class="sfx-home-hero__sky" aria-hidden="true"></div>

      <div class="sfx-home-hero__inner">
        <!-- 左侧：公告栏 + 大标题 + 双卡片 -->
        <div class="sfx-home-hero__left">
          <a class="sfx-home-announce animate-in" style="animation-delay: 0.1s" href="#" @click.prevent>
            <Sparkles class="sfx-home-announce__sparkle" :size="14" aria-hidden="true" />
            <span class="sfx-home-announce__text">
              SmartCarb 全新上线，AI 辅助课程建设与学情分析能力全面升级
            </span>
            <ArrowRight class="sfx-home-announce__arrow" :size="13" aria-hidden="true" />
          </a>

          <h1 class="sfx-home-hero__title animate-in" style="animation-delay: 0.2s">
            <span 
              ref="glowTextRef"
              class="glow-text" 
              :style="{ '--glow-x': glowGradientX + '%' }"
              @mousemove="onGlowTextMouseMove"
              @mouseleave="onGlowTextMouseLeave"
            >
              让课程回应学习
            </span>
          </h1>

          <div class="sfx-home-hero__cards">
            <button class="sfx-home-glass-card animate-in" style="animation-delay: 0.35s" @click="goLearning">
              <BookOpen :size="24" class="sfx-home-glass-card__icon" />
              <h3>开始学习</h3>
              <p>进入你的学习空间，继续未完成的课程</p>
            </button>

            <button class="sfx-home-glass-card animate-in" style="animation-delay: 0.45s" @click="goBuilding">
              <Layers :size="24" class="sfx-home-glass-card__icon" />
              <h3>课程建设</h3>
              <p>AI 辅助搭建课程，从材料到发布一站式</p>
            </button>
          </div>
        </div>

        <!-- 右侧：品牌大卡 -->
        <button class="sfx-home-brand-card animate-in" style="animation-delay: 0.3s" @click="goHall">
          <div class="sfx-home-brand-card__text">
            <h3>SmartCarb</h3>
            <p>
              探索课程大厅
              <span class="sfx-home-brand-card__arrow" aria-hidden="true">→</span>
            </p>
          </div>
        </button>
      </div>

      <!-- 向下滚动提示 -->
      <button class="sfx-home-scroll-hint animate-in" style="animation-delay: 0.6s" aria-label="向下滚动" @click="scrollToQuickAccess">
        <span>快捷面板</span>
        <ChevronDown :size="18" />
      </button>
    </section>

    <!-- ── 快捷导航面板 ── -->
    <section ref="quickAccessRef" class="sfx-home-quick">
      <div class="sfx-home-quick__inner">
        <h2 class="sfx-home-quick__title">快捷面板</h2>
        
        <!-- 主要导航卡片 -->
        <div class="sfx-home-quick__grid">
          <button class="sfx-home-nav-card" @click="goLearning">
            <div class="sfx-home-nav-card__icon" style="background: linear-gradient(135deg, #5E8C61, #3F6B52)">
              <BookOpen :size="28" />
            </div>
            <div class="sfx-home-nav-card__content">
              <h3>我学习的</h3>
              <p>查看正在学习的课程与进度</p>
            </div>
            <ArrowRight :size="20" class="sfx-home-nav-card__arrow" />
          </button>

          <button class="sfx-home-nav-card" @click="goBuilding">
            <div class="sfx-home-nav-card__icon" style="background: linear-gradient(135deg, #355C7D, #203A5F)">
              <Layers :size="28" />
            </div>
            <div class="sfx-home-nav-card__content">
              <h3>我建设的</h3>
              <p>管理正在建设的课程项目</p>
            </div>
            <ArrowRight :size="20" class="sfx-home-nav-card__arrow" />
          </button>

          <button class="sfx-home-nav-card" @click="goHall">
            <div class="sfx-home-nav-card__icon" style="background: linear-gradient(135deg, #C68B2C, #9B6618)">
              <Compass :size="28" />
            </div>
            <div class="sfx-home-nav-card__content">
              <h3>课程大厅</h3>
              <p>探索和加入新的课程</p>
            </div>
            <ArrowRight :size="20" class="sfx-home-nav-card__arrow" />
          </button>

          <button class="sfx-home-nav-card" @click="goLab">
            <div class="sfx-home-nav-card__icon" style="background: linear-gradient(135deg, #B85C5C, #8B3A3A)">
              <Zap :size="28" />
            </div>
            <div class="sfx-home-nav-card__content">
              <h3>实验室</h3>
              <p>访问实验任务与研究工作台</p>
            </div>
            <ArrowRight :size="20" class="sfx-home-nav-card__arrow" />
          </button>

          <button class="sfx-home-nav-card" @click="goResources">
            <div class="sfx-home-nav-card__icon" style="background: linear-gradient(135deg, #8EA7BE, #355C7D)">
              <FileText :size="28" />
            </div>
            <div class="sfx-home-nav-card__content">
              <h3>资源库</h3>
              <p>管理课程材料、笔记和文件</p>
            </div>
            <ArrowRight :size="20" class="sfx-home-nav-card__arrow" />
          </button>

          <button class="sfx-home-nav-card" @click="router.push('/app/courses/create')">
            <div class="sfx-home-nav-card__icon" style="background: linear-gradient(135deg, #78AAFF, #3A65C2)">
              <GraduationCap :size="28" />
            </div>
            <div class="sfx-home-nav-card__content">
              <h3>创建课程</h3>
              <p>开始建设一门新的课程</p>
            </div>
            <ArrowRight :size="20" class="sfx-home-nav-card__arrow" />
          </button>
        </div>

        <!-- 继续学习区域（如果有进行中的课程） -->
        <div v-if="isLoggedIn && continueStatus === 'ready' && continueList.length > 0" class="sfx-home-continue-section">
          <header class="sfx-home-continue__head">
            <div>
              <h3 class="sfx-home-continue__title">继续学习</h3>
              <p class="sfx-home-continue__sub">从上次停下的地方接着学</p>
            </div>
            <SfxButton variant="tertiary" size="sm" @click="goLearning">查看全部 →</SfxButton>
          </header>

          <div class="sfx-home-continue__grid">
            <article
              v-for="course in continueList.slice(0, 3)"
              :key="course.course_id"
              class="sfx-home-continue-card"
              tabindex="0"
              @click="enterCourse(course)"
              @keydown.enter="enterCourse(course)"
            >
              <h4 class="sfx-home-continue-card__title">{{ course.title }}</h4>
              <p class="sfx-home-continue-card__teacher">
                {{ course.teacher_name || '未知教师' }}
              </p>
              <div class="sfx-home-continue-card__progress">
                <div class="sfx-home-continue-card__bar">
                  <div
                    class="sfx-home-continue-card__fill"
                    :style="{ width: `${Math.min(100, (course.progress?.overall_progress || 0) * 100)}%` }"
                  ></div>
                </div>
                <span class="sfx-home-continue-card__pct">
                  {{ Math.round((course.progress?.overall_progress || 0) * 100) }}%
                </span>
              </div>
              <div class="sfx-home-continue-card__foot">
                <span class="sfx-home-continue-card__last">
                  {{ formatLastStudy(course.progress?.last_study_time) }}
                </span>
                <span class="sfx-home-continue-card__enter">
                  继续学习 <ArrowRight :size="14" />
                </span>
              </div>
            </article>
          </div>
        </div>

        <!-- Loading 状态 -->
        <div v-else-if="isLoggedIn && continueStatus === 'loading'" class="sfx-home-continue__loading">
          <Loader2 class="is-spinning" :size="24" />
          <span>正在加载你的课程…</span>
        </div>
      </div>
    </section>

    <!-- ── 页脚 ── -->
    <footer class="sfx-home-footer">
      <div class="sfx-home-footer__inner">
        <div class="sfx-home-footer__brand">
          <div class="sfx-home-brand">
            <div class="sfx-home-brand__mark" aria-hidden="true">
              <BookOpenCheck :size="22" />
            </div>
            <span class="sfx-home-brand__name">SmartCarb</span>
          </div>
          <p class="sfx-home-footer__tagline">让课程回应学习</p>
        </div>

        <div class="sfx-home-footer__cols">
          <div class="sfx-home-footer__col">
            <h4>用户手册</h4>
            <ul>
              <li>
                <router-link :to="docRoute('manual/快速入门指南.md', '快速入门指南')">
                  <FileText :size="14" /> 快速入门指南
                </router-link>
              </li>
              <li>
                <router-link :to="docRoute('manual/学生使用手册.md', '学生使用手册')">
                  <BookOpen :size="14" /> 学生使用手册
                </router-link>
              </li>
              <li>
                <router-link :to="docRoute('manual/教师建设手册.md', '教师建设手册')">
                  <GraduationCap :size="14" /> 教师建设手册
                </router-link>
              </li>
              <li>
                <router-link :to="docRoute('manual/AI功能说明.md', 'AI 功能说明')">
                  <Sparkles :size="14" /> AI 功能说明
                </router-link>
              </li>
            </ul>
          </div>

          <div class="sfx-home-footer__col">
            <h4>资源</h4>
            <ul>
              <li>
                <router-link to="/docs">
                  <Layers :size="14" /> 课程模板库
                </router-link>
              </li>
              <li>
                <router-link to="/docs">
                  <Zap :size="14" /> 实验案例集
                </router-link>
              </li>
              <li>
                <a :href="`${GITHUB_URL}/commits`" target="_blank" rel="noopener">
                  <FileText :size="14" /> 更新日志
                </a>
              </li>
              <li>
                <router-link :to="docRoute('research/面向编程教育智能体的多源认知证据驱动细粒度知识追踪方法研究.md', '研究报告')">
                  <BookOpen :size="14" /> 研究报告
                </router-link>
              </li>
              <li>
                <a :href="GITHUB_URL" target="_blank" rel="noopener">
                  <Github :size="14" /> 开源项目
                </a>
              </li>
            </ul>
          </div>

          <div class="sfx-home-footer__col">
            <h4>社区</h4>
            <ul>
              <li>
                <router-link to="/app/courses/hall">
                  <Compass :size="14" /> 课程大厅
                </router-link>
              </li>
              <li>
                <a :href="GITHUB_ISSUES_URL" target="_blank" rel="noopener">
                  <Users :size="14" /> 教师社区
                </a>
              </li>
              <li>
                <a :href="GITHUB_URL" target="_blank" rel="noopener">
                  <Github :size="14" /> GitHub
                </a>
              </li>
            </ul>
          </div>

          <div class="sfx-home-footer__col">
            <h4>关于</h4>
            <ul>
              <li>
                <router-link :to="docRoute('about/产品介绍.md', '产品介绍')">产品介绍</router-link>
              </li>
              <li>
                <router-link :to="docRoute('about/联系我们.md', '联系我们')">联系我们</router-link>
              </li>
              <li>
                <router-link to="/docs#privacy">隐私政策</router-link>
              </li>
              <li>
                <router-link to="/docs#terms">服务条款</router-link>
              </li>
            </ul>
          </div>
        </div>
      </div>

      <div class="sfx-home-footer__bottom">
        <p>© {{ new Date().getFullYear() }} SmartCarb · 保留所有权利</p>
        <div class="sfx-home-footer__bottom-right">
          <button type="button" class="sfx-home-footer__top-btn" @click="scrollToTop">
            回到顶部 ↑
          </button>
          <a
            class="sfx-home-footer__icp"
            href="https://beian.miit.gov.cn/"
            target="_blank"
            rel="noopener"
          >
            ICP 备案号：京ICP备XXXXXXXX号
          </a>
        </div>
      </div>
    </footer>
  </div>
</template>

<style scoped>
/* ═══════════════════════════════════════════════════════
   CSS 自定义属性：旋转流光边框动画
   ═══════════════════════════════════════════════════════ */
@property --border-angle {
  syntax: '<angle>';
  initial-value: 0deg;
  inherits: false;
}

/* ═══════════════════════════════════════════════════════
   页面容器：自然高度，由 AppShell 滚动容器滚动
   ═══════════════════════════════════════════════════════ */
.sfx-home {
  position: relative;
  background: #f9f8f8;
  color: var(--text-primary);
  min-height: 100vh;
}

/* 进场动画：默认不可见，is-ready 后触发淡入上浮 */
.animate-in {
  opacity: 0;
  transform: translateY(20px);
  transition: opacity 0.8s var(--ease-out), transform 0.8s var(--ease-out);
}

.sfx-home.is-ready .animate-in {
  opacity: 1;
  transform: translateY(0);
}

/* 粒子背景：sticky 固定于视口，内容从上方滚过 */
.sfx-home-bg {
  position: sticky;
  top: 0;
  height: 100vh;
  margin-bottom: -100vh;
  z-index: 0;
  pointer-events: none;
  overflow: hidden;
}

.sfx-home-bg__glow {
  position: absolute;
  top: -20%;
  left: 50%;
  transform: translateX(-50%);
  width: 80vw;
  height: 80vh;
  background: radial-gradient(
    ellipse at center,
    rgba(77, 107, 254, 0.08) 0%,
    rgba(53, 92, 125, 0.04) 40%,
    transparent 70%
  );
  filter: blur(40px);
  pointer-events: none;
}

/* ═══════════════════════════════════════════════════════
   首屏 Hero
   ═══════════════════════════════════════════════════════ */
.sfx-home-hero {
  position: relative;
  z-index: 1;
  min-height: calc(100vh - var(--nav-l1-height, 56px));
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 天空蓝渐变层 */
.sfx-home-hero__sky {
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background: linear-gradient(180deg, #9cc1e7 0%, rgba(250, 250, 250, 0) 100%);
}

.sfx-home-hero__inner {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 1200px;
  padding: 40px 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 48px;
}

.sfx-home-hero__left {
  flex: 1;
  min-width: 0;
}

/* 公告栏：星光脉冲 + 文本 hover 显隐 + 箭头滑动 */
.sfx-home-announce {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  max-width: 100%;
  padding: 6px 14px;
  border-radius: 999px;
  background: hsla(0, 0%, 100%, 0.5);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid hsla(0, 0%, 100%, 0.3);
  color: var(--text-secondary);
  font-size: 13px;
  text-decoration: none;
  margin-bottom: 40px;
  transition: all 0.25s var(--ease-out);
  cursor: pointer;
}

.sfx-home-announce:hover {
  background: hsla(0, 0%, 100%, 0.7);
  box-shadow: 0 4px 16px rgba(16, 26, 49, 0.06);
  color: var(--ink-500);
}

/* 星光图标：呼吸缩放动画 */
.sfx-home-announce__sparkle {
  color: #4d6bfe;
  flex-shrink: 0;
  animation: ds-sparkle-pulse 2.4s ease-in-out infinite;
}

.sfx-home-announce__text {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 520px;
  opacity: 0.75;
  transition: opacity 0.3s ease;
}

.sfx-home-announce:hover .sfx-home-announce__text {
  opacity: 1;
}

.sfx-home-announce__arrow {
  flex-shrink: 0;
  opacity: 0.6;
  transition: transform 0.2s var(--ease-out), opacity 0.2s ease;
}

.sfx-home-announce:hover .sfx-home-announce__arrow {
  transform: translateX(3px);
  opacity: 1;
}

@keyframes ds-sparkle-pulse {
  0%, 100% { transform: scale(1); opacity: 0.85; }
  50% { transform: scale(1.15); opacity: 1; }
}

/* 主标题：左对齐大字 + hover 发光 + 跟随鼠标的底部渐变光晕 */
.sfx-home-hero__title {
  font-size: clamp(32px, 4vw, 48px);
  font-weight: 500;
  line-height: 1.2;
  letter-spacing: 0.15em;
  color: #152443;
  margin: 0 0 48px;
  text-align: left;
}

.glow-text {
  position: relative;
  display: inline-block;
  transition: filter 0.45s var(--ease-out);
  cursor: default;
  --glow-x: 50%;
}

/* 底部动态渐变光晕 */
.glow-text::after {
  content: '';
  position: absolute;
  bottom: -12px;
  left: 0;
  right: 0;
  height: 8px;
  background: radial-gradient(
    ellipse 120px 8px at var(--glow-x) 50%,
    rgba(77, 107, 254, 0.5) 0%,
    rgba(77, 107, 254, 0.3) 30%,
    transparent 70%
  );
  opacity: 0;
  transition: opacity 0.3s ease;
  pointer-events: none;
}

.glow-text:hover::after {
  opacity: 1;
}

.glow-text:hover {
  filter: drop-shadow(0 0 18px rgba(77, 107, 254, 0.4))
    drop-shadow(0 0 42px rgba(77, 107, 254, 0.18));
}

/* 双毛玻璃卡片：更紧凑的 DeepSeek 风格 */
.sfx-home-hero__cards {
  display: flex;
  gap: 16px;
  max-width: 520px;
}

.sfx-home-glass-card {
  position: relative;
  flex: 1;
  text-align: left;
  padding: 18px 20px;
  border-radius: 12px;
  background: hsla(0, 0%, 100%, 0.45);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1.5px solid hsla(0, 0%, 100%, 0.25);
  box-shadow: 0 2px 16px rgba(16, 26, 49, 0.04);
  cursor: pointer;
  font-family: inherit;
  transition: background-color 0.2s ease, border-color 0.2s ease,
    transform 0.3s var(--ease-out), box-shadow 0.3s var(--ease-out);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* 旋转流光边框：hover 显现 */
.sfx-home-glass-card::before {
  content: '';
  position: absolute;
  inset: -1.5px;
  border-radius: inherit;
  padding: 1.5px;
  background: conic-gradient(
    from var(--border-angle),
    rgba(58, 101, 194, 0.15) 0%,
    rgba(120, 170, 255, 0.7) 25%,
    rgba(58, 101, 194, 0.15) 50%,
    rgba(120, 170, 255, 0.7) 75%,
    rgba(58, 101, 194, 0.15) 100%
  );
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  opacity: 0;
  transition: opacity 0.3s ease;
  animation: rotating-border 6s linear infinite;
  pointer-events: none;
}

.sfx-home-glass-card:hover::before {
  opacity: 1;
}

.sfx-home-glass-card:hover {
  transform: translateY(-2px);
  background: hsla(0, 0%, 100%, 0.68);
  box-shadow: 0 8px 28px rgba(16, 26, 49, 0.08);
}

@keyframes rotating-border {
  to { --border-angle: 360deg; }
}

.sfx-home-glass-card__icon {
  color: #3a65c2;
  opacity: 0.8;
  transition: opacity 0.3s ease, transform 0.3s var(--ease-out);
}

.sfx-home-glass-card:hover .sfx-home-glass-card__icon {
  opacity: 1;
  transform: scale(1.05);
}

.sfx-home-glass-card h3 {
  font-size: 16px;
  font-weight: 600;
  color: #101a31;
  margin: 0;
  letter-spacing: 0;
}

.sfx-home-glass-card p {
  font-size: 13px;
  line-height: 1.5;
  color: rgba(0, 0, 0, 0.6);
  margin: 0;
}

/* 右侧品牌大卡：深蓝流光，参考 DeepSeek 的尺寸比例 */
.sfx-home-brand-card {
  position: relative;
  flex-shrink: 0;
  width: 290px;
  height: 330px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  background:
    radial-gradient(ellipse at 25% 18%, rgba(77, 107, 254, 0.4) 0%, transparent 52%),
    radial-gradient(ellipse at 80% 62%, rgba(53, 92, 125, 0.55) 0%, transparent 58%),
    radial-gradient(ellipse at 45% 95%, rgba(16, 26, 49, 0.7) 0%, transparent 45%),
    linear-gradient(160deg, #20395e 0%, #14213d 100%);
  box-shadow: 0 12px 40px rgba(16, 26, 49, 0.22);
  overflow: hidden;
  cursor: pointer;
  font-family: inherit;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  align-items: flex-start;
  padding: 22px 24px;
  text-align: left;
  transition: transform 0.35s var(--ease-out), box-shadow 0.35s var(--ease-out);
}

.sfx-home-brand-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 20px 56px rgba(16, 26, 49, 0.28);
}

/* 卡内流光层（缓慢漂移） */
.sfx-home-brand-card::before {
  content: '';
  position: absolute;
  inset: -40%;
  background:
    radial-gradient(ellipse 45% 35% at 30% 30%, rgba(142, 167, 190, 0.22), transparent 70%),
    radial-gradient(ellipse 40% 45% at 70% 70%, rgba(77, 107, 254, 0.2), transparent 70%);
  animation: brandFlow 14s ease-in-out infinite alternate;
  pointer-events: none;
}

@keyframes brandFlow {
  0% { transform: translate(0, 0) rotate(0deg); }
  100% { transform: translate(6%, -5%) rotate(8deg); }
}

/* 底部文字 */
.sfx-home-brand-card__text {
  position: relative;
}

.sfx-home-brand-card__text h3 {
  font-size: 18px;
  font-weight: 600;
  color: #fff;
  margin: 0 0 6px;
  letter-spacing: 0.02em;
}

.sfx-home-brand-card__text p {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.68);
  margin: 0;
  transition: color 0.25s var(--ease-out);
}

.sfx-home-brand-card__arrow {
  display: inline-block;
  margin-left: 2px;
  transition: transform 0.25s var(--ease-out);
}

.sfx-home-brand-card:hover .sfx-home-brand-card__text p {
  color: rgba(255, 255, 255, 0.9);
}

.sfx-home-brand-card:hover .sfx-home-brand-card__arrow {
  transform: translateX(4px);
}

/* 滚动提示 */
.sfx-home-scroll-hint {
  position: absolute;
  bottom: 40px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 12px;
  cursor: pointer;
  font-family: inherit;
  z-index: 2;
  animation: bounceHint 2s ease-in-out infinite;
}

@keyframes bounceHint {
  0%, 100% { transform: translateX(-50%) translateY(0); }
  50% { transform: translateX(-50%) translateY(6px); }
}

/* ═══════════════════════════════════════════════════════
   快捷导航面板
   ═══════════════════════════════════════════════════════ */
.sfx-home-quick {
  position: relative;
  z-index: 1;
  padding: 80px 60px;
  background: rgba(255, 255, 255, 0.4);
}

.sfx-home-quick__inner {
  max-width: var(--content-max-width, 1440px);
  margin: 0 auto;
}

.sfx-home-quick__title {
  font-size: 32px;
  font-weight: 700;
  line-height: 1.2;
  letter-spacing: -0.02em;
  margin: 0 0 var(--space-10);
  color: var(--text-primary);
}

/* 导航卡片网格 */
.sfx-home-quick__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
  gap: var(--space-5);
  margin-bottom: var(--space-12);
}

/* 导航卡片 */
.sfx-home-nav-card {
  display: flex;
  align-items: center;
  gap: var(--space-5);
  padding: var(--space-6);
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  cursor: pointer;
  font-family: inherit;
  text-align: left;
  transition: all 0.3s var(--ease-out);
  position: relative;
  overflow: hidden;
}

.sfx-home-nav-card::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, transparent 0%, rgba(255, 255, 255, 0.5) 100%);
  opacity: 0;
  transition: opacity 0.3s ease;
  pointer-events: none;
}

.sfx-home-nav-card:hover::before {
  opacity: 1;
}

.sfx-home-nav-card:hover {
  border-color: var(--ink-300);
  box-shadow: 0 8px 24px rgba(16, 26, 49, 0.12);
  transform: translateY(-4px);
}

.sfx-home-nav-card__icon {
  flex-shrink: 0;
  width: 56px;
  height: 56px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
  transition: transform 0.3s var(--ease-out), box-shadow 0.3s var(--ease-out);
}

.sfx-home-nav-card:hover .sfx-home-nav-card__icon {
  transform: scale(1.08);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.2);
}

.sfx-home-nav-card__content {
  flex: 1;
  min-width: 0;
}

.sfx-home-nav-card__content h3 {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 4px;
  line-height: 1.3;
}

.sfx-home-nav-card__content p {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0;
  line-height: 1.5;
}

.sfx-home-nav-card__arrow {
  flex-shrink: 0;
  color: var(--text-muted);
  transition: transform 0.3s var(--ease-out), color 0.3s ease;
}

.sfx-home-nav-card:hover .sfx-home-nav-card__arrow {
  transform: translateX(4px);
  color: var(--ink-500);
}

/* 继续学习区域 */
.sfx-home-continue-section {
  margin-top: var(--space-16);
  padding-top: var(--space-12);
  border-top: 1px solid var(--border-subtle);
}

.sfx-home-continue__head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: var(--space-7);
}

.sfx-home-continue__title {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 var(--space-1);
  line-height: 1.3;
}

.sfx-home-continue__sub {
  font-size: 14px;
  color: var(--text-secondary);
  margin: 0;
  line-height: 1.5;
}

.sfx-home-continue__loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  padding: var(--space-16) var(--space-5);
  color: var(--text-muted);
  font-size: 14px;
}

.is-spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.sfx-home-continue__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: var(--space-5);
}

/* 继续学习卡片 */
.sfx-home-continue-card {
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  padding: var(--space-6);
  cursor: pointer;
  transition: all 0.3s var(--ease-out);
  outline: none;
}

.sfx-home-continue-card:hover,
.sfx-home-continue-card:focus-visible {
  border-color: var(--ink-300);
  box-shadow: 0 8px 24px rgba(16, 26, 49, 0.1);
  transform: translateY(-3px);
}

.sfx-home-continue-card__title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 var(--space-2);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.sfx-home-continue-card__teacher {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0 0 var(--space-5);
  line-height: 1.4;
}

.sfx-home-continue-card__progress {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.sfx-home-continue-card__bar {
  flex: 1;
  height: 6px;
  background: var(--ink-100);
  border-radius: 999px;
  overflow: hidden;
}

.sfx-home-continue-card__fill {
  height: 100%;
  background: linear-gradient(90deg, #5E8C61 0%, #3F6B52 100%);
  border-radius: 999px;
  transition: width 0.6s var(--ease-out);
}

.sfx-home-continue-card__pct {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  min-width: 38px;
  text-align: right;
}

.sfx-home-continue-card__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.sfx-home-continue-card__last {
  font-size: 12px;
  color: var(--text-muted);
}

.sfx-home-continue-card__enter {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  font-weight: 500;
  color: #5E8C61;
  transition: gap 0.2s var(--ease-out);
}

.sfx-home-continue-card:hover .sfx-home-continue-card__enter {
  gap: 6px;
}

/* ═══════════════════════════════════════════════════════
   页脚（自然高度）
   ═══════════════════════════════════════════════════════ */
.sfx-home-footer {
  position: relative;
  z-index: 1;
  border-top: 1px solid var(--border-subtle);
  background: rgba(249, 248, 248, 0.65);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
}

.sfx-home-footer__inner {
  max-width: var(--content-max-width, 1440px);
  padding: var(--space-12) 60px var(--space-8);
  margin: 0 auto;
  display: grid;
  grid-template-columns: 1fr 2fr;
  gap: var(--space-16);
}

.sfx-home-brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.sfx-home-brand__mark {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: linear-gradient(135deg, var(--ink-700), var(--ink-500));
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 14px rgba(53, 92, 125, 0.3);
}

.sfx-home-brand__name {
  font-size: 15px;
  font-weight: 600;
  color: var(--ink-700);
  letter-spacing: 0.02em;
}

.sfx-home-footer__tagline {
  margin-top: var(--space-4);
  font-size: 14px;
  color: var(--text-secondary);
}

.sfx-home-footer__cols {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-8);
  max-width: 1200px;
}

.sfx-home-footer__col h4 {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 var(--space-4);
}

.sfx-home-footer__col ul {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.sfx-home-footer__col a {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-secondary);
  text-decoration: none;
  transition: color 0.2s var(--ease-out);
}

.sfx-home-footer__col a:hover {
  color: var(--ink-500);
}

.sfx-home-footer__bottom {
  border-top: 1px solid var(--border-subtle);
  padding: var(--space-5) 60px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-4);
  font-size: 12px;
  color: var(--text-muted);
}

.sfx-home-footer__bottom p {
  margin: 0;
}

.sfx-home-footer__bottom-right {
  display: flex;
  align-items: center;
  gap: var(--space-5);
}

.sfx-home-footer__top-btn {
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  padding: 4px 0;
  transition: color 0.2s var(--ease-out);
}

.sfx-home-footer__top-btn:hover {
  color: var(--ink-500);
}

.sfx-home-footer__icp {
  color: var(--text-muted);
  text-decoration: none;
  transition: color 0.2s var(--ease-out);
}

.sfx-home-footer__icp:hover {
  color: var(--ink-500);
}

/* ═══════════════════════════════════════════════════════
   响应式
   ═══════════════════════════════════════════════════════ */
@media (max-width: 1080px) {
  .sfx-home-hero__inner {
    flex-direction: column;
    gap: 40px;
    padding: 32px 24px;
  }

  .sfx-home-hero__left {
    width: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
  }

  .sfx-home-hero__title {
    margin-bottom: 40px;
    letter-spacing: 0.08em;
  }

  .sfx-home-announce__text {
    max-width: 480px;
    white-space: normal;
    text-align: left;
  }

  .sfx-home-brand-card {
    width: min(330px, 90vw);
    height: 280px;
  }

  .sfx-home-continue {
    padding: 64px 24px 56px;
  }

  .sfx-home-footer__inner {
    padding-left: 24px;
    padding-right: 24px;
  }

  .sfx-home-footer__bottom {
    padding-left: 24px;
    padding-right: 24px;
  }
}

@media (max-width: 900px) {
  .sfx-home-hero__title {
    font-size: clamp(30px, 8vw, 44px);
  }

  .sfx-home-hero__cards {
    width: 100%;
    max-width: 560px;
  }

  .sfx-home-continue__title {
    font-size: 28px;
  }

  .sfx-home-continue__grid {
    grid-template-columns: 1fr;
  }

  .sfx-home-footer__inner {
    grid-template-columns: 1fr;
    gap: var(--space-8);
  }

  .sfx-home-footer__cols {
    grid-template-columns: repeat(2, 1fr);
    gap: var(--space-6);
  }
}

@media (max-width: 560px) {
  .sfx-home-hero__cards {
    flex-direction: column;
  }

  .sfx-home-announce__text {
    max-width: 200px;
    white-space: nowrap;
  }

  .sfx-home-brand-card {
    height: 220px;
    padding: 20px;
  }

  .sfx-home-footer__cols {
    grid-template-columns: 1fr;
  }

  .sfx-home-footer__bottom {
    flex-direction: column;
    text-align: center;
  }
}
</style>
