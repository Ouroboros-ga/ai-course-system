<script setup>
/**
 * App Home Page — 自然滚动式首页（仿 DeepSeek 官网）
 *
 * 首屏 Hero：公告栏 + 核心标语 + 双毛玻璃卡片 + 右侧品牌大卡
 * 下滑自动吸附到「继续进行」；课程卡片随数量自然堆叠
 * 页面底部：品牌 / 资源 / 社区 / 关于 页脚
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
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
  Rocket,
} from 'lucide-vue-next'
import ParticleBackground from '@/components/home/ui/ParticleBackground.vue'
import { listFacadeCourses } from '@/api/facade.js'
import SfxButton from '@/app/ui/SfxButton.vue'

const router = useRouter()

// ── 滚轮吸附（Hero ↔ 继续进行） ──────────────────────
const rootRef = ref(null)
const continueRef = ref(null)
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
  if (!scrollEl || !continueRef.value) return
  if (snapLocked) {
    e.preventDefault()
    return
  }
  const continueTop = continueRef.value.offsetTop
  const st = scrollEl.scrollTop
  if (e.deltaY > 12 && st < continueTop - 80) {
    // 首屏内向下滚 → 吸附到「继续进行」
    e.preventDefault()
    snapLocked = true
    scrollEl.scrollTo({ top: continueTop, behavior: 'smooth' })
    setTimeout(() => (snapLocked = false), 800)
  } else if (e.deltaY < -12 && st > 60 && st <= continueTop + 80) {
    // 「继续进行」顶部向上滚 → 吸附回顶部
    e.preventDefault()
    snapLocked = true
    scrollEl.scrollTo({ top: 0, behavior: 'smooth' })
    setTimeout(() => (snapLocked = false), 800)
  }
}

function scrollToContinue() {
  if (!scrollEl || !continueRef.value) return
  scrollEl.scrollTo({ top: continueRef.value.offsetTop, behavior: 'smooth' })
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

onMounted(() => {
  scrollEl = findScrollParent(rootRef.value)
  window.addEventListener('wheel', onWheel, { passive: false })
  loadContinue()
})
onBeforeUnmount(() => {
  window.removeEventListener('wheel', onWheel)
})
</script>

<template>
  <div ref="rootRef" class="sfx-home">
    <!-- 粒子背景（sticky 固定于视口，内容从上方滚过） -->
    <div class="sfx-home-bg" aria-hidden="true">
      <ParticleBackground />
      <div class="sfx-home-bg__glow"></div>
    </div>

    <!-- ── 首屏 Hero（仿 DeepSeek：左内容 + 右品牌卡） ── -->
    <section class="sfx-home-hero">
      <div class="sfx-home-hero__inner">
        <!-- 左侧：公告栏 + 大标题 + 双卡片 -->
        <div class="sfx-home-hero__left">
          <a class="sfx-home-announce" href="#" @click.prevent>
            <Rocket :size="14" aria-hidden="true" />
            <span class="sfx-home-announce__text">
              SmartCarb 全新上线，AI 辅助课程建设与学情分析能力全面升级，欢迎体验和反馈
            </span>
            <ArrowRight :size="13" aria-hidden="true" />
          </a>

          <h1 class="sfx-home-hero__title">
            <span class="glow-text" data-text="让课程回应学习">让课程回应学习</span>
          </h1>

          <div class="sfx-home-hero__cards">
            <button class="sfx-home-glass-card" @click="goLearning">
              <h3>开始学习</h3>
              <p>进入你的学习空间<br />继续未完成的课程</p>
            </button>

            <button class="sfx-home-glass-card" @click="goBuilding">
              <h3>课程建设</h3>
              <p>AI 辅助搭建课程<br />从材料到发布一站式</p>
            </button>
          </div>
        </div>

        <!-- 右侧：品牌大卡（深蓝流光，预留大螃蟹 Logo） -->
        <button class="sfx-home-brand-card" @click="goHall">
          <div class="sfx-home-brand-card__logo" aria-hidden="true">
            <span class="sfx-home-brand-card__crab">🦀</span>
          </div>
          <div class="sfx-home-brand-card__text">
            <h3>SmartCarb</h3>
            <p>探索课程大厅 →</p>
          </div>
        </button>
      </div>

      <!-- 向下滚动提示 -->
      <button class="sfx-home-scroll-hint" aria-label="向下滚动" @click="scrollToContinue">
        <span>继续进行</span>
        <ChevronDown :size="18" />
      </button>
    </section>

    <!-- ── 继续进行（自然高度，卡片多了往下堆叠） ── -->
    <section ref="continueRef" class="sfx-home-continue">
      <div class="sfx-home-continue__inner">
        <header class="sfx-home-continue__head">
          <div>
            <h2 class="sfx-home-continue__title">继续进行</h2>
            <p class="sfx-home-continue__sub">从上次停下的地方接着学</p>
          </div>
          <SfxButton variant="tertiary" size="sm" @click="goLearning">查看全部 →</SfxButton>
        </header>

        <!-- loading -->
        <div v-if="continueStatus === 'loading'" class="sfx-home-continue__loading">
          <Loader2 class="is-spinning" :size="24" />
          <span>正在加载你的课程…</span>
        </div>

        <!-- error -->
        <div v-else-if="continueStatus === 'error'" class="sfx-home-continue__empty">
          <p class="sfx-home-continue__empty-title">加载失败</p>
          <p class="sfx-home-continue__empty-desc">{{ continueError }}</p>
          <SfxButton variant="primary" size="sm" @click="loadContinue">重试</SfxButton>
        </div>

        <!-- empty -->
        <div v-else-if="continueStatus === 'empty'" class="sfx-home-continue__empty">
          <BookOpen :size="36" />
          <p class="sfx-home-continue__empty-title">还没有进行中的课程</p>
          <p class="sfx-home-continue__empty-desc">
            从课程大厅选一门感兴趣的课程开始学习吧。
          </p>
          <SfxButton variant="primary" size="sm" @click="goHall">去课程大厅</SfxButton>
        </div>

        <!-- list -->
        <div v-else class="sfx-home-continue__grid">
          <article
            v-for="course in continueList"
            :key="course.course_id"
            class="sfx-home-continue-card"
            tabindex="0"
            @click="enterCourse(course)"
            @keydown.enter="enterCourse(course)"
          >
            <h3 class="sfx-home-continue-card__title">{{ course.title }}</h3>
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
            <h4>资源</h4>
            <ul>
              <li>
                <a href="#" @click.prevent>
                  <FileText :size="14" /> 用户手册
                </a>
              </li>
              <li>
                <a href="#" @click.prevent>
                  <BookOpen :size="14" /> 教学指南
                </a>
              </li>
              <li>
                <a href="#" @click.prevent>
                  <Sparkles :size="14" /> 更新日志
                </a>
              </li>
            </ul>
          </div>

          <div class="sfx-home-footer__col">
            <h4>社区</h4>
            <ul>
              <li>
                <a href="#" @click.prevent>
                  <Github :size="14" /> GitHub
                </a>
              </li>
              <li>
                <a href="#" @click.prevent>
                  <Compass :size="14" /> 课程大厅
                </a>
              </li>
              <li>
                <a href="#" @click.prevent>
                  <GraduationCap :size="14" /> 教师计划
                </a>
              </li>
            </ul>
          </div>

          <div class="sfx-home-footer__col">
            <h4>关于</h4>
            <ul>
              <li>
                <a href="#" @click.prevent>产品介绍</a>
              </li>
              <li>
                <a href="#" @click.prevent>隐私政策</a>
              </li>
              <li>
                <a href="#" @click.prevent>服务条款</a>
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
   页面容器：自然高度，由 AppShell 滚动容器滚动
   ═══════════════════════════════════════════════════════ */
.sfx-home {
  position: relative;
  background: var(--surface-page);
  color: var(--text-primary);
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
   首屏 Hero（仿 DeepSeek：左内容 58% + 右品牌卡 38%）
   ═══════════════════════════════════════════════════════ */
.sfx-home-hero {
  position: relative;
  z-index: 1;
  min-height: calc(100vh - var(--nav-l1-height, 56px));
  display: flex;
  align-items: center;
  justify-content: center;
}

.sfx-home-hero__inner {
  width: 100%;
  max-width: 1200px;
  padding: 48px 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 56px;
}

.sfx-home-hero__left {
  flex: 1;
  min-width: 0;
}

/* 公告栏 */
.sfx-home-announce {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  max-width: 100%;
  padding: 7px 14px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.55);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid rgba(255, 255, 255, 0.4);
  color: var(--text-secondary);
  font-size: 13px;
  text-decoration: none;
  margin-bottom: 48px;
  transition: all 0.25s var(--ease-out);
  cursor: pointer;
}

.sfx-home-announce:hover {
  background: rgba(255, 255, 255, 0.8);
  box-shadow: var(--shadow-sm);
  color: var(--ink-500);
}

.sfx-home-announce__text {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 520px;
}

/* 主标题：左对齐大字 + hover 发光 */
.sfx-home-hero__title {
  font-size: clamp(40px, 4.6vw, 56px);
  font-weight: 500;
  line-height: 1.15;
  letter-spacing: 0.12em;
  color: var(--ink-950);
  margin: 0 0 56px;
  text-align: left;
}

.glow-text {
  transition: filter 0.45s var(--ease-out), text-shadow 0.45s var(--ease-out);
  cursor: default;
}

.glow-text:hover {
  filter: drop-shadow(0 0 18px rgba(77, 107, 254, 0.4))
    drop-shadow(0 0 42px rgba(77, 107, 254, 0.18));
}

/* 双毛玻璃卡片 */
.sfx-home-hero__cards {
  display: flex;
  gap: 20px;
  max-width: 560px;
}

.sfx-home-glass-card {
  flex: 1;
  text-align: left;
  padding: 22px 24px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.65);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.5);
  box-shadow: 0 4px 24px rgba(16, 26, 49, 0.04);
  cursor: pointer;
  font-family: inherit;
  transition: all 0.3s var(--ease-out);
}

.sfx-home-glass-card:hover {
  transform: translateY(-4px);
  background: rgba(255, 255, 255, 0.85);
  box-shadow: 0 12px 36px rgba(16, 26, 49, 0.1);
}

.sfx-home-glass-card h3 {
  font-size: 15px;
  font-weight: 600;
  color: #4d6bfe;
  margin: 0 0 10px;
  letter-spacing: 0.02em;
}

.sfx-home-glass-card p {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary);
  margin: 0;
}

/* 右侧品牌大卡：深蓝流光 */
.sfx-home-brand-card {
  position: relative;
  flex-shrink: 0;
  width: 330px;
  height: 380px;
  border-radius: 20px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  background:
    radial-gradient(ellipse at 25% 18%, rgba(77, 107, 254, 0.4) 0%, transparent 52%),
    radial-gradient(ellipse at 80% 62%, rgba(53, 92, 125, 0.55) 0%, transparent 58%),
    radial-gradient(ellipse at 45% 95%, rgba(16, 26, 49, 0.7) 0%, transparent 45%),
    linear-gradient(160deg, #20395e 0%, #14213d 100%);
  box-shadow: 0 20px 60px rgba(16, 26, 49, 0.28);
  overflow: hidden;
  cursor: pointer;
  font-family: inherit;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  align-items: flex-start;
  padding: 28px;
  text-align: left;
  transition: transform 0.35s var(--ease-out), box-shadow 0.35s var(--ease-out);
}

.sfx-home-brand-card:hover {
  transform: translateY(-6px);
  box-shadow: 0 28px 72px rgba(16, 26, 49, 0.38);
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

/* Logo 位（大螃蟹占位） */
.sfx-home-brand-card__logo {
  position: relative;
  width: 72px;
  height: 72px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.22);
  backdrop-filter: blur(6px);
  display: flex;
  align-items: center;
  justify-content: center;
}

.sfx-home-brand-card__crab {
  font-size: 38px;
  line-height: 1;
  filter: drop-shadow(0 4px 12px rgba(0, 0, 0, 0.3));
}

/* 底部文字 */
.sfx-home-brand-card__text {
  position: relative;
}

.sfx-home-brand-card__text h3 {
  font-size: 20px;
  font-weight: 600;
  color: #fff;
  margin: 0 0 8px;
  letter-spacing: 0.04em;
}

.sfx-home-brand-card__text p {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.65);
  margin: 0;
  transition: color 0.25s var(--ease-out);
}

.sfx-home-brand-card:hover .sfx-home-brand-card__text p {
  color: rgba(255, 255, 255, 0.9);
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

@media (prefers-reduced-motion: reduce) {
  .sfx-home-scroll-hint { animation: none; }
  .sfx-home-brand-card::before { animation: none; }
}

/* ═══════════════════════════════════════════════════════
   继续进行（自然高度，卡片多了往下堆叠）
   ═══════════════════════════════════════════════════════ */
.sfx-home-continue {
  position: relative;
  z-index: 1;
  padding: 88px 60px 72px;
}

.sfx-home-continue__inner {
  max-width: var(--content-max-width, 1440px);
  margin: 0 auto;
}

.sfx-home-continue__head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: var(--space-8);
}

.sfx-home-continue__title {
  font-size: 36px;
  font-weight: 700;
  line-height: 1.2;
  letter-spacing: -0.02em;
  margin: 0 0 var(--space-2);
  color: var(--text-primary);
}

.sfx-home-continue__sub {
  font-size: 14px;
  color: var(--text-secondary);
  margin: 0;
}

/* 卡片网格：随数量自然堆叠 */
.sfx-home-continue__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: var(--space-5);
}

.sfx-home-continue-card {
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  padding: var(--space-6);
  cursor: pointer;
  text-align: left;
  transition: all 0.3s var(--ease-out);
  font-family: inherit;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.sfx-home-continue-card:hover {
  border-color: var(--ink-300);
  box-shadow: var(--shadow-sm);
  transform: translateY(-3px);
}

.sfx-home-continue-card__title {
  font-size: 17px;
  font-weight: 600;
  margin: 0;
  color: var(--text-primary);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.sfx-home-continue-card__teacher {
  font-size: 12px;
  color: var(--text-muted);
  margin: 0;
}

.sfx-home-continue-card__progress {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-top: var(--space-2);
}

.sfx-home-continue-card__bar {
  flex: 1;
  height: 6px;
  background: var(--surface-soft);
  border-radius: 999px;
  overflow: hidden;
}

.sfx-home-continue-card__fill {
  height: 100%;
  background: linear-gradient(90deg, var(--ink-500), var(--ink-700));
  border-radius: 999px;
  transition: width 0.6s var(--ease-out);
}

.sfx-home-continue-card__pct {
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-500);
  min-width: 36px;
  text-align: right;
}

.sfx-home-continue-card__foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: auto;
  padding-top: var(--space-3);
  border-top: 1px solid var(--border-subtle);
}

.sfx-home-continue-card__last {
  font-size: 12px;
  color: var(--text-muted);
}

.sfx-home-continue-card__enter {
  display: flex;
  align-items: center;
  gap: 2px;
  font-size: 12px;
  font-weight: 500;
  color: var(--ink-500);
  transition: gap 0.2s var(--ease-out);
}

.sfx-home-continue-card:hover .sfx-home-continue-card__enter {
  gap: 6px;
}

/* loading / empty */
.sfx-home-continue__loading,
.sfx-home-continue__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-4);
  padding: var(--space-20) 0;
  color: var(--text-secondary);
}

.sfx-home-continue__loading {
  color: var(--text-muted);
  font-size: 14px;
}

.sfx-home-continue__empty-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.sfx-home-continue__empty-desc {
  font-size: 14px;
  color: var(--text-secondary);
  margin: 0;
}

/* ═══════════════════════════════════════════════════════
   页脚（自然高度）
   ═══════════════════════════════════════════════════════ */
.sfx-home-footer {
  position: relative;
  z-index: 1;
  border-top: 1px solid var(--border-subtle);
  background: rgba(255, 255, 255, 0.5);
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
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-8);
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
