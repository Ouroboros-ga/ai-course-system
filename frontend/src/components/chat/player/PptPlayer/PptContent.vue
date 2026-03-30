<template>
  <div
    class="page-content markdown-body"
    v-html="renderedContent"
  ></div>
</template>

<script setup>
import { computed } from 'vue'
import { Marked } from 'marked'
import { markedHighlight } from 'marked-highlight'
import hljs from 'highlight.js'
import DOMPurify from 'dompurify'

// 非 scoped 引入高亮主题，避免样式优先级问题
import 'highlight.js/styles/github-dark.css'

const props = defineProps({
  content: {
    type: String,
    default: ''
  }
})

// 1. 正确的新版 marked 初始化方式（兼容 v5+）
const markedInstance = new Marked(
  markedHighlight({
    langPrefix: 'hljs language-',
    highlight(code, lang) {
      // 如果没有指定语言或语言不支持，使用 auto 自动推断
      const language = hljs.getLanguage(lang) ? lang : 'plaintext'
      return hljs.highlight(code, { language }).value
    }
  })
)

// 配置项
markedInstance.setOptions({
  gfm: true,
  breaks: true
})

// 2. 解析 + 防 XSS 清理
const renderedContent = computed(() => {
  if (!props.content) return '<p class="placeholder">等待AI解析内容...</p>'

  // 同步解析（传入 { async: false } 防止新版返回 Promise）
  const rawHtml = markedInstance.parse(props.content, { async: false })

  // 使用 DOMPurify 清理潜在的恶意脚本
  return DOMPurify.sanitize(rawHtml)
})
</script>

<!-- 注意：highlight.js 的全局样式放在非 scoped 块中 -->
<style>
/* 此处留空，仅作为全局样式的挂载点隔离 */
</style>

<style scoped>
/* 基础容器 */
.page-content {
  font-size: 18px;
  line-height: 1.8;
  color: #4b5565;
  max-height: 70vh;
  overflow-y: auto;
  word-wrap: break-word;
  padding: 24px;
  border-radius: 8px;
  background: #fff;
  /* 兼容 Firefox 滚动条 */
  scrollbar-width: thin;
  scrollbar-color: #cbd5e1 transparent;
}

/* 占位提示 */
.placeholder {
  color: #9ca3af;
  text-align: center;
  padding: 60px 0;
}

/* ===== Markdown 元素样式 ===== */

/* 标题 */
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4),
.markdown-body :deep(h5),
.markdown-body :deep(h6) {
  margin-top: 1.6em;
  margin-bottom: 0.8em;
  font-weight: 600;
  line-height: 1.4;
  color: #1f2937;
}

.markdown-body :deep(h1) { font-size: 1.8em; border-bottom: 2px solid #e5e7eb; padding-bottom: 0.3em; }
.markdown-body :deep(h2) { font-size: 1.5em; border-bottom: 1px solid #e5e7eb; padding-bottom: 0.25em; }
.markdown-body :deep(h3) { font-size: 1.25em; }
.markdown-body :deep(h4) { font-size: 1.1em; }

.markdown-body :deep(h1:first-child),
.markdown-body :deep(h2:first-child),
.markdown-body :deep(h3:first-child) {
  margin-top: 0;
}

.markdown-body :deep(p) {
  margin-top: 0;
  margin-bottom: 1em;
}

.markdown-body :deep(a) {
  color: #0ea5e9;
  text-decoration: none;
  border-bottom: 1px solid transparent;
  transition: border-color 0.2s;
}
.markdown-body :deep(a:hover) {
  border-bottom-color: #0ea5e9;
}

/* 行内代码 */
.markdown-body :deep(code:not(pre code)) {
  background: #f1f5f9;
  color: #e11d48;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.9em;
  font-family: 'Menlo', 'Monaco', 'Consolas', monospace;
}

/* 代码块容器 */
.markdown-body :deep(pre) {
  margin: 1em 0;
  border-radius: 8px;
  overflow: hidden;
  position: relative;
  background: #1e293b;
}

.markdown-body :deep(pre code) {
  display: block;
  padding: 20px;
  overflow-x: auto;
  font-size: 14px;
  line-height: 1.6;
  font-family: 'Menlo', 'Monaco', 'Consolas', monospace;
  background: transparent !important;
  color: #e2e8f0;
  /* 美化代码块内部的横向滚动条 */
  scrollbar-width: thin;
  scrollbar-color: #475569 transparent;
}

.markdown-body :deep(pre code::-webkit-scrollbar) {
  height: 6px;
}
.markdown-body :deep(pre code::-webkit-scrollbar-track) {
  background: transparent;
}
.markdown-body :deep(pre code::-webkit-scrollbar-thumb) {
  background: #475569;
  border-radius: 3px;
}

/* 引用块 */
.markdown-body :deep(blockquote) {
  margin: 1em 0;
  padding: 12px 20px;
  border-left: 4px solid #0ea5e9;
  background: #f0f9ff;
  border-radius: 0 6px 6px 0;
  color: #475569;
}
.markdown-body :deep(blockquote p:last-child) {
  margin-bottom: 0;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 0.8em 0;
  padding-left: 2em;
}

.markdown-body :deep(li) {
  margin-bottom: 0.4em;
}

.markdown-body :deep(li > ul),
.markdown-body :deep(li > ol) {
  margin: 0.2em 0;
}

.markdown-body :deep(ul li input[type="checkbox"]) {
  margin-right: 6px;
  accent-color: #0ea5e9;
}

/* 表格 */
.markdown-body :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 1em 0;
  font-size: 0.95em;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid #e5e7eb;
  padding: 10px 14px;
  text-align: left;
}

.markdown-body :deep(th) {
  background: #f8fafc;
  font-weight: 600;
  color: #1f2937;
}

.markdown-body :deep(tr:nth-child(even) td) {
  background: #fafbfc;
}

.markdown-body :deep(hr) {
  border: none;
  height: 1px;
  background: #e5e7eb;
  margin: 2em 0;
}

.markdown-body :deep(img) {
  max-width: 100%;
  border-radius: 8px;
  margin: 1em 0;
}

.markdown-body :deep(strong) {
  color: #1f2937;
  font-weight: 600;
}

.markdown-body :deep(em) {
  color: #64748b;
}

.markdown-body :deep(del) {
  color: #94a3b8;
}

/* ===== 外层容器滚动条美化 ===== */
.page-content::-webkit-scrollbar {
  width: 6px;
}
.page-content::-webkit-scrollbar-track {
  background: transparent;
}
.page-content::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 3px;
}
.page-content::-webkit-scrollbar-thumb:hover {
  background: #94a3b8;
}
</style>
