<template>
  <div class="message-bubble" :class="role === 'user' ? 'bubble-user' : 'bubble-ai'">
    <div class="message-content markdown-body" v-html="renderedContent"></div>
    <div v-if="showResumeBtn" class="resume-action">
      <button class="btn-resume"> 回到刚才的讲解进度</button>
    </div>
  </div>
  <div v-if="tags" class="tags-row">
    <span v-for="tag in tags" :key="tag" class="tag-item">{{ tag }}</span>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Marked } from 'marked'
import { markedHighlight } from 'marked-highlight'
import hljs from 'highlight.js'
import DOMPurify from 'dompurify'
import katex from 'katex'

import 'highlight.js/styles/github-dark.css'
import 'katex/dist/katex.min.css'

const props = defineProps(['role', 'content', 'tags', 'showResumeBtn'])

const markedInstance = new Marked(
  markedHighlight({
    langPrefix: 'hljs language-',
    highlight(code, lang) {
      const language = hljs.getLanguage(lang) ? lang : 'plaintext'
      return hljs.highlight(code, { language }).value
    }
  })
)

markedInstance.setOptions({
  gfm: true,
  breaks: true
})

function extractFormulas(text) {
  const formulas = []
  let index = 0
  
  let processedText = text.replace(/\$\$([\s\S]+?)\$\$/g, (match, formula) => {
    const placeholder = `%%BLOCK_FORMULA_${index}%%`
    formulas.push({
      placeholder,
      formula: formula.trim(),
      isBlock: true
    })
    index++
    return placeholder
  })
  
  processedText = processedText.replace(/\$([^$\n]+?)\$/g, (match, formula) => {
    const placeholder = `%%INLINE_FORMULA_${index}%%`
    formulas.push({
      placeholder,
      formula: formula.trim(),
      isBlock: false
    })
    index++
    return placeholder
  })
  
  return { text: processedText, formulas }
}

function renderFormulas(html, formulas) {
  let result = html
  
  formulas.forEach(({ placeholder, formula, isBlock }) => {
    try {
      const rendered = katex.renderToString(formula, {
        displayMode: isBlock,
        throwOnError: false,
        output: 'html',
        strict: false,
        trust: true
      })
      
      const wrappedHtml = isBlock
        ? `<div class="katex-block">${rendered}</div>`
        : `<span class="katex-inline">${rendered}</span>`
      
      result = result.replace(placeholder, wrappedHtml)
    } catch (error) {
      console.warn('KaTeX渲染失败:', error.message, '公式:', formula)
      const errorHtml = isBlock
        ? `<div class="katex-error">$$${formula}$$</div>`
        : `<span class="katex-error">$${formula}$</span>`
      result = result.replace(placeholder, errorHtml)
    }
  })
  
  return result
}

const renderedContent = computed(() => {
  if (!props.content) return ''
  
  const { text: textWithoutFormulas, formulas } = extractFormulas(props.content)
  
  const rawHtml = markedInstance.parse(textWithoutFormulas, { async: false })
  
  const htmlWithFormulas = renderFormulas(rawHtml, formulas)
  
  const cleanHtml = DOMPurify.sanitize(htmlWithFormulas, {
    ADD_ATTR: ['class', 'style'],
    ADD_TAGS: ['span', 'div']
  })
  
  return cleanHtml
})

</script>
<style scoped>
.message-bubble {
  padding: 12px 16px;
  border-radius: 16px;
  font-size: 14px;
  line-height: 1.6;
  box-shadow: 0 1px 2px 0 rgba(0,0,0,0.05);
  border: 1px solid transparent;
}

.bubble-ai {
  background: white;
  color: #374151;
  border-top-left-radius: 4px;
  border-color: #f3f4f6;
}

.bubble-user {
  background: #2563eb;
  color: white;
  border-top-right-radius: 4px;
}

.message-content {
  word-wrap: break-word;
  overflow-wrap: break-word;
}

.resume-action {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #eff6ff;
}

.btn-resume {
  width: 100%;
  background: #eff6ff;
  color: #2563eb;
  border: none;
  padding: 8px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

.tags-row {
  display: flex;
  gap: 6px;
  margin-top: 4px;
}

.tag-item {
  font-size: 10px;
  background: #eff6ff;
  color: #2563eb;
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid #dbeafe;
}

/* ===== Markdown 样式 ===== */

.message-bubble :deep(h1),
.message-bubble :deep(h2),
.message-bubble :deep(h3),
.message-bubble :deep(h4),
.message-bubble :deep(h5),
.message-bubble :deep(h6) {
  margin-top: 1em;
  margin-bottom: 0.5em;
  font-weight: 600;
  line-height: 1.3;
}

.message-bubble :deep(h1) { font-size: 1.4em; }
.message-bubble :deep(h2) { font-size: 1.3em; }
.message-bubble :deep(h3) { font-size: 1.2em; }
.message-bubble :deep(h4) { font-size: 1.1em; }

.message-bubble :deep(p) {
  margin: 0.5em 0;
}

.message-bubble :deep(p:first-child) {
  margin-top: 0;
}

.message-bubble :deep(p:last-child) {
  margin-bottom: 0;
}

.message-bubble :deep(a) {
  color: #2563eb;
  text-decoration: none;
  border-bottom: 1px solid transparent;
  transition: border-color 0.2s;
}

.bubble-user :deep(a) {
  color: #bfdbfe;
}

.message-bubble :deep(a:hover) {
  border-bottom-color: currentColor;
}

/* 行内代码 */
.message-bubble :deep(code:not(pre code)) {
  background: #f1f5f9;
  color: #e11d48;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.9em;
  font-family: 'Menlo', 'Monaco', 'Consolas', monospace;
}

.bubble-user :deep(code:not(pre code)) {
  background: rgba(255, 255, 255, 0.2);
  color: #fff;
}

/* 代码块 */
.message-bubble :deep(pre) {
  margin: 0.8em 0;
  border-radius: 8px;
  overflow: hidden;
  background: #1e293b;
}

.message-bubble :deep(pre code) {
  display: block;
  padding: 12px;
  overflow-x: auto;
  font-size: 13px;
  line-height: 1.5;
  font-family: 'Menlo', 'Monaco', 'Consolas', monospace;
  background: transparent !important;
  color: #e2e8f0;
}

/* 引用块 */
.message-bubble :deep(blockquote) {
  margin: 0.8em 0;
  padding: 8px 16px;
  border-left: 3px solid #2563eb;
  background: #f0f9ff;
  border-radius: 0 6px 6px 0;
  color: #475569;
}

.bubble-user :deep(blockquote) {
  border-left-color: rgba(255, 255, 255, 0.5);
  background: rgba(255, 255, 255, 0.1);
  color: #e0e7ff;
}

.message-bubble :deep(blockquote p:last-child) {
  margin-bottom: 0;
}

/* 列表 */
.message-bubble :deep(ul),
.message-bubble :deep(ol) {
  margin: 0.5em 0;
  padding-left: 1.5em;
}

.message-bubble :deep(li) {
  margin-bottom: 0.3em;
}

.message-bubble :deep(li > ul),
.message-bubble :deep(li > ol) {
  margin: 0.2em 0;
}

/* 表格 */
.message-bubble :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 0.8em 0;
  font-size: 0.9em;
}

.message-bubble :deep(th),
.message-bubble :deep(td) {
  border: 1px solid #e5e7eb;
  padding: 6px 10px;
  text-align: left;
}

.message-bubble :deep(th) {
  background: #f8fafc;
  font-weight: 600;
}

.bubble-user :deep(th) {
  background: rgba(255, 255, 255, 0.1);
}

.message-bubble :deep(tr:nth-child(even) td) {
  background: #fafbfc;
}

.bubble-user :deep(tr:nth-child(even) td) {
  background: rgba(255, 255, 255, 0.05);
}

/* 分隔线 */
.message-bubble :deep(hr) {
  border: none;
  height: 1px;
  background: #e5e7eb;
  margin: 1em 0;
}

.bubble-user :deep(hr) {
  background: rgba(255, 255, 255, 0.3);
}

/* 强调 */
.message-bubble :deep(strong) {
  font-weight: 600;
}

.message-bubble :deep(em) {
  font-style: italic;
}

.message-bubble :deep(del) {
  text-decoration: line-through;
  opacity: 0.7;
}

/* ===== KaTeX 数学公式样式 ===== */

/* 行内公式 */
.message-bubble :deep(.katex-inline) {
  display: inline;
  padding: 0 2px;
}

/* 块级公式 */
.message-bubble :deep(.katex-block) {
  display: block;
  text-align: center;
  margin: 1em 0;
  padding: 0.8em;
  background: #f8fafc;
  border-radius: 6px;
  overflow-x: auto;
  overflow-y: hidden;
}

.bubble-user :deep(.katex-block) {
  background: rgba(255, 255, 255, 0.1);
}

/* KaTeX容器 */
.message-bubble :deep(.katex) {
  font-size: 1em;
  color: inherit;
}

.message-bubble :deep(.katex-block .katex) {
  font-size: 1.1em;
}

/* 公式错误 */
.message-bubble :deep(.katex-error) {
  color: #dc2626;
  background: #fee2e2;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'Menlo', 'Monaco', 'Consolas', monospace;
  font-size: 0.9em;
}

.bubble-user :deep(.katex-error) {
  background: rgba(220, 38, 38, 0.2);
  color: #fca5a5;
}
</style>
