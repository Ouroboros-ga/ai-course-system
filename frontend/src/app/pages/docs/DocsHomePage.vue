<script setup>
/**
 * Docs Home — 顶层公开文档中心（不挂 AppShell，无需登录）。
 *
 * - 文档文件放在 frontend/public/static/docs/（构建后进 dist，nginx 直接静态服务）。
 * - 项目文档区为第一份文件（技术手册正式稿置顶），点击走 /docs/view 阅读器。
 * - 手册/资源/关于等尚无正文的条目先以"整理中"占位，不伪造内容。
 */
import { BookOpenCheck, Download, ExternalLink, FileText, FileType2, Layers, Zap, Clock3 } from 'lucide-vue-next'
import { useRouter } from 'vue-router'
import SfxButton from '@/app/ui/SfxButton.vue'
import { PRIVACY_SECTIONS, TERMS_SECTIONS } from './legal-content.js'

const router = useRouter()

const GITHUB_URL = 'https://github.com/Ouroboros-ga/ai-course-system'

// 静态文件位于 /static/docs/<file>（与 /docs 路由分目录，避免 nginx 目录索引冲突）
function fileHref(file) {
  return `/static/docs/${file.split('/').map(encodeURIComponent).join('/')}`
}

function openReader(file, name) {
  router.push({ path: '/docs/view', query: { file, name } })
}

function download(file) {
  const a = document.createElement('a')
  a.href = fileHref(file)
  a.download = ''
  document.body.appendChild(a)
  a.click()
  a.remove()
}

const PROJECT_DOCS = [
  {
    name: 'T2606981 项目详细方案',
    file: 'project/T2606981-项目详细方案.pdf',
    format: 'PDF',
    size: '5.2 MB',
    updated: '2026-08',
    desc: 'SmartCarb 项目详细方案：产品设计、技术架构、实施计划与评审材料。',
    featured: true,
  },
]

const MANUAL_DOCS = [
  { name: '快速入门指南', desc: '从注册到完成第一门课程的关键路径' },
  { name: '学生使用手册', desc: '课程学习、提问与实验任务操作说明' },
  { name: '教师建设手册', desc: '九步建课、智能体备课与发布流程' },
  { name: 'AI 功能说明', desc: '教学问答、代码诊断与科研工作台能力说明' },
]

const RESOURCE_DOCS = [
  { name: '课程模板库', desc: '可复用的课程结构与材料模板' },
  { name: '实验案例集', desc: '实验任务样例与运行说明' },
  { name: '更新日志', desc: '版本变更记录与能力演进' },
]

const ABOUT_DOCS = [
  { name: '产品介绍', desc: 'SmartCarb 产品定位与能力概览' },
  { name: '联系我们', desc: '问题反馈与联系渠道（GitHub Issues）' },
  { name: '隐私政策', desc: '数据收集、使用与保护说明', hash: '#privacy' },
  { name: '服务条款', desc: '平台使用条款与约定', hash: '#terms' },
]
</script>

<template>
  <div class="sfx docs-standalone">
    <header class="docs-nav">
      <div class="docs-nav__inner">
        <router-link to="/docs" class="docs-brand">
          <span class="docs-brand__mark" aria-hidden="true">
            <BookOpenCheck :size="20" />
          </span>
          <span class="docs-brand__name">SmartCarb</span>
          <span class="docs-brand__divider" aria-hidden="true">/</span>
          <span class="docs-brand__page">文档中心</span>
        </router-link>
        <nav class="docs-nav__actions" aria-label="文档中心导航">
          <router-link to="/app" class="docs-nav__link">返回平台</router-link>
          <a class="docs-nav__link" :href="GITHUB_URL" target="_blank" rel="noopener">
            GitHub <ExternalLink :size="14" aria-hidden="true" />
          </a>
        </nav>
      </div>
    </header>

    <main class="docs-body">
      <div class="docs-container">
        <section class="docs-hero">
          <h1 class="docs-hero__title">文档中心</h1>
          <p class="docs-hero__sub">产品手册 · 项目文档 · 更新日志，一站式可查</p>
        </section>

        <section class="docs-section" aria-labelledby="docs-section-project">
          <div class="docs-section__head">
            <h2 id="docs-section-project" class="docs-section__title">项目文档</h2>
            <span class="docs-section__hint">第一份文件：SmartCarb 项目技术文档正式稿</span>
          </div>
          <div class="docs-grid">
            <article
              v-for="doc in PROJECT_DOCS"
              :key="doc.file"
              class="doc-card"
              :class="{ 'is-featured': doc.featured }"
            >
              <div class="doc-card__head">
                <span class="doc-badge" :class="doc.format === 'PDF' ? 'is-pdf' : 'is-docx'">
                  {{ doc.format }}
                </span>
                <span v-if="doc.featured" class="doc-badge is-first">第一份</span>
                <span class="doc-card__meta">{{ doc.size }} · {{ doc.updated }}</span>
              </div>
              <h3 class="doc-card__name">{{ doc.name }}</h3>
              <p class="doc-card__desc">{{ doc.desc }}</p>
              <div class="doc-card__actions">
                <SfxButton variant="primary" size="sm" @click="openReader(doc.file, doc.name)">
                  在线阅读
                </SfxButton>
                <SfxButton variant="secondary" size="sm" @click="download(doc.file)">
                  <template #icon><Download :size="14" /></template>
                  下载
                </SfxButton>
              </div>
            </article>
          </div>
        </section>

        <section class="docs-section" aria-labelledby="docs-section-manual">
          <div class="docs-section__head">
            <h2 id="docs-section-manual" class="docs-section__title">用户手册</h2>
          </div>
          <ul class="docs-list">
            <li v-for="doc in MANUAL_DOCS" :key="doc.name" class="docs-row">
              <span class="docs-row__icon" aria-hidden="true"><FileText :size="18" /></span>
              <div class="docs-row__main">
                <div class="docs-row__name">{{ doc.name }}</div>
                <div class="docs-row__desc">{{ doc.desc }}</div>
              </div>
              <span class="docs-row__pending">整理中</span>
            </li>
          </ul>
        </section>

        <section class="docs-section" aria-labelledby="docs-section-resource">
          <div class="docs-section__head">
            <h2 id="docs-section-resource" class="docs-section__title">资源</h2>
          </div>
          <ul class="docs-list">
            <li v-for="(doc, i) in RESOURCE_DOCS" :key="doc.name" class="docs-row">
              <span class="docs-row__icon" aria-hidden="true">
                <Layers v-if="i === 0" :size="18" />
                <FileType2 v-else-if="i === 1" :size="18" />
                <Clock3 v-else :size="18" />
              </span>
              <div class="docs-row__main">
                <div class="docs-row__name">{{ doc.name }}</div>
                <div class="docs-row__desc">{{ doc.desc }}</div>
              </div>
              <span class="docs-row__pending">整理中</span>
            </li>
          </ul>
        </section>

        <section class="docs-section" aria-labelledby="docs-section-about">
          <div class="docs-section__head">
            <h2 id="docs-section-about" class="docs-section__title">关于</h2>
          </div>
          <ul class="docs-list">
            <li v-for="doc in ABOUT_DOCS" :key="doc.name" class="docs-row">
              <span class="docs-row__icon" aria-hidden="true"><Zap :size="18" /></span>
              <div class="docs-row__main">
                <div class="docs-row__name">{{ doc.name }}</div>
                <div class="docs-row__desc">{{ doc.desc }}</div>
              </div>
              <router-link v-if="doc.hash" class="docs-row__link" :to="{ path: '/docs', hash: doc.hash }">
                查看全文
              </router-link>
              <span v-else class="docs-row__pending">整理中</span>
            </li>
          </ul>
        </section>

        <!-- ── 隐私政策 / 服务条款全文（登录注册页与本页锚点跳转目标） ── -->
        <section id="privacy" class="legal-section" aria-labelledby="legal-privacy-title">
          <h2 id="legal-privacy-title" class="legal-title">隐私政策</h2>
          <p class="legal-meta">生效日期：2026 年 8 月 20 日 · 主体：SmartCarb 团队</p>
          <div v-for="sec in PRIVACY_SECTIONS" :key="sec.title" class="legal-block">
            <h3 class="legal-block__title">{{ sec.title }}</h3>
            <p v-for="(para, i) in sec.paragraphs" :key="i" class="legal-block__para">{{ para }}</p>
          </div>
        </section>

        <section id="terms" class="legal-section" aria-labelledby="legal-terms-title">
          <h2 id="legal-terms-title" class="legal-title">服务条款</h2>
          <p class="legal-meta">生效日期：2026 年 8 月 20 日 · 主体：SmartCarb 团队</p>
          <div v-for="sec in TERMS_SECTIONS" :key="sec.title" class="legal-block">
            <h3 class="legal-block__title">{{ sec.title }}</h3>
            <p v-for="(para, i) in sec.paragraphs" :key="i" class="legal-block__para">{{ para }}</p>
          </div>
        </section>
      </div>
    </main>

    <footer class="docs-footer">
      <div class="docs-container docs-footer__inner">
        <span>© {{ new Date().getFullYear() }} SmartCarb · 让课程回应学习</span>
        <a class="docs-footer__link" :href="GITHUB_URL" target="_blank" rel="noopener">
          GitHub 开源项目
        </a>
      </div>
    </footer>
  </div>
</template>

<style>
/* 独立公开页：自载 Academic Ink 令牌与基础样式（AppShell 不会为 /docs 挂载） */
@import '../../styles/tokens.css';
@import '../../styles/base.css';
</style>

<style scoped>
.docs-standalone {
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
  background: var(--surface-page);
}

.docs-container {
  width: 100%;
  max-width: 1080px;
  margin: 0 auto;
  padding: 0 var(--space-6);
}

/* ── 顶部导航 ── */
.docs-nav {
  position: sticky;
  top: 0;
  z-index: 10;
  background: var(--surface-panel);
  border-bottom: 1px solid var(--border-default);
}

.docs-nav__inner {
  max-width: 1080px;
  margin: 0 auto;
  height: var(--nav-l1-height);
  padding: 0 var(--space-6);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-6);
}

.docs-brand {
  display: inline-flex;
  align-items: center;
  gap: var(--space-3);
  color: var(--text-primary);
}

.docs-brand__mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: var(--radius-md);
  background: var(--ink-100);
  color: var(--ink-900);
}

.docs-brand__name {
  font-weight: var(--title-2-weight);
  font-size: var(--ui-md-size);
}

.docs-brand__divider {
  color: var(--text-disabled);
}

.docs-brand__page {
  color: var(--text-secondary);
}

.docs-nav__actions {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

.docs-nav__link {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--ui-md-size);
  font-weight: var(--ui-md-weight);
  color: var(--text-secondary);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  transition: background var(--duration-fast) var(--ease-out), color var(--duration-fast) var(--ease-out);
}

.docs-nav__link:hover {
  color: var(--ink-900);
  background: var(--ink-100);
}

/* ── 正文 ── */
.docs-body {
  flex: 1;
}

.docs-hero {
  padding: var(--space-16) 0 var(--space-8);
  border-bottom: 1px solid var(--border-subtle);
  margin-bottom: var(--space-12);
}

.docs-hero__title {
  font-family: var(--font-serif);
  font-size: var(--display-lg-size);
  line-height: var(--display-lg-line);
  font-weight: var(--display-lg-weight);
  color: var(--ink-900);
}

.docs-hero__sub {
  margin-top: var(--space-3);
  color: var(--text-secondary);
  font-size: var(--body-md-size);
}

/* ── 区块 ── */
.docs-section {
  margin-bottom: var(--space-12);
}

.docs-section__head {
  display: flex;
  align-items: baseline;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--border-default);
}

.docs-section__title {
  font-size: var(--title-2-size);
  line-height: var(--title-2-line);
  font-weight: var(--title-2-weight);
  color: var(--ink-900);
}

.docs-section__hint {
  font-size: var(--caption-size);
  color: var(--text-muted);
}

/* ── 项目文档卡片 ── */
.docs-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: var(--space-4);
}

.doc-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-6);
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  transition: border-color var(--duration-fast) var(--ease-out), box-shadow var(--duration-fast) var(--ease-out);
}

.doc-card:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-xs);
}

.doc-card.is-featured {
  border-color: var(--color-focus);
}

.doc-card__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.doc-card__meta {
  margin-left: auto;
  font-size: var(--caption-size);
  color: var(--text-muted);
}

.doc-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--caption-size);
  font-weight: var(--caption-weight);
}

.doc-badge.is-pdf {
  background: var(--red-100);
  color: var(--red-700);
}

.doc-badge.is-docx {
  background: var(--ink-100);
  color: var(--ink-700);
}

.doc-badge.is-first {
  background: var(--green-100);
  color: var(--green-700);
}

.doc-card__name {
  font-size: var(--title-3-size);
  line-height: var(--title-3-line);
  font-weight: var(--title-3-weight);
  color: var(--text-primary);
}

.doc-card__desc {
  font-size: var(--ui-md-size);
  line-height: var(--ui-md-line);
  color: var(--text-secondary);
}

.doc-card__actions {
  margin-top: auto;
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

/* ── 普通文档行（整理中占位） ── */
.docs-list {
  display: flex;
  flex-direction: column;
}

.docs-row {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-3);
  border-bottom: 1px solid var(--border-subtle);
}

.docs-row__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  border-radius: var(--radius-md);
  background: var(--surface-cool);
  color: var(--ink-500);
}

.docs-row__main {
  min-width: 0;
}

.docs-row__name {
  font-size: var(--ui-md-size);
  font-weight: var(--ui-md-weight);
  color: var(--text-primary);
}

.docs-row__desc {
  margin-top: 2px;
  font-size: var(--caption-size);
  color: var(--text-muted);
}

.docs-row__pending {
  margin-left: auto;
  flex-shrink: 0;
  padding: 2px var(--space-3);
  border-radius: var(--radius-full);
  background: var(--surface-soft);
  color: var(--text-muted);
  font-size: var(--caption-size);
  font-weight: var(--caption-weight);
}

.docs-row__link {
  margin-left: auto;
  flex-shrink: 0;
  padding: 2px var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--ui-sm-size);
  font-weight: var(--ui-sm-weight);
  color: var(--text-link);
}

.docs-row__link:hover {
  background: var(--ink-100);
  color: var(--ink-900);
}

/* ── 隐私政策 / 服务条款全文 ── */
.legal-section {
  scroll-margin-top: 72px;
  margin-top: var(--space-12);
  padding-top: var(--space-8);
  border-top: 1px solid var(--border-default);
}

.legal-title {
  font-size: var(--title-2-size);
  line-height: var(--title-2-line);
  font-weight: var(--title-2-weight);
  color: var(--ink-900);
}

.legal-meta {
  margin-top: var(--space-2);
  margin-bottom: var(--space-8);
  font-size: var(--caption-size);
  color: var(--text-muted);
}

.legal-block {
  margin-bottom: var(--space-6);
}

.legal-block__title {
  margin-bottom: var(--space-3);
  font-size: var(--title-3-size);
  line-height: var(--title-3-line);
  font-weight: var(--title-3-weight);
  color: var(--text-primary);
}

.legal-block__para {
  margin-bottom: var(--space-3);
  font-size: var(--body-md-size);
  line-height: var(--body-md-line);
  color: var(--text-primary);
}

/* ── 页脚 ── */
.docs-footer {
  border-top: 1px solid var(--border-default);
  background: var(--surface-panel);
}

.docs-footer__inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding-top: var(--space-4);
  padding-bottom: var(--space-4);
  font-size: var(--caption-size);
  color: var(--text-muted);
}

.docs-footer__link {
  color: var(--text-link);
}
</style>
