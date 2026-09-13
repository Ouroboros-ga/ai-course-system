import { Marked } from 'marked'
import { markedHighlight } from 'marked-highlight'
import hljs from 'highlight.js'
import DOMPurify from 'dompurify'
import katex from 'katex'
// ⚠️ 必须在这里引 KaTeX 样式：本模块产出 katex 的 HTML，样式却只在两个聊天组件里引过。
// 缺了它，`.katex-mathml`（本该被 CSS 视觉隐藏的无障碍回退层）会直接显示出来 ——
// 页面上的公式会变成「渲染结果 + 原始 TeX 文本」两遍叠在一起。
// 放在产出方，任何消费本模块的页面（OJ 题面、课件、报告…）都自动正确。
import 'katex/dist/katex.min.css'

const markedInstance = new Marked(
  markedHighlight({
    langPrefix: 'hljs language-',
    highlight(code, lang) {
      const language = hljs.getLanguage(lang) ? lang : 'plaintext'
      return hljs.highlight(code, { language }).value
    }
  })
)
markedInstance.setOptions({ gfm: true, breaks: true })

export function renderContent(text) {
  if (!text) return ''

  try {
    const formulas = []
    let index = 0
    let processedText = text.replace(/\$\$([\s\S]+?)\$\$/g, (match, formula) => {
      const placeholder = `%%BLOCK_${index}%%`
      formulas.push({ placeholder, formula: formula.trim(), isBlock: true })
      index++
      return placeholder
    })
    processedText = processedText.replace(/\$([^$\n]+?)\$/g, (match, formula) => {
      const placeholder = `%%INLINE_${index}%%`
      formulas.push({ placeholder, formula: formula.trim(), isBlock: false })
      index++
      return placeholder
    })

    const rawHtml = markedInstance.parse(processedText, { async: false })

    let result = rawHtml
    formulas.forEach(({ placeholder, formula, isBlock }) => {
      try {
        const rendered = katex.renderToString(formula, {
          displayMode: isBlock,
          throwOnError: false,
        })
        const wrappedHtml = isBlock
          ? `<div class="katex-block">${rendered}</div>`
          : `<span class="katex-inline">${rendered}</span>`
        result = result.replace(placeholder, wrappedHtml)
      } catch (e) {
      }
    })

    return DOMPurify.sanitize(result, { ADD_ATTR: ['class'], ADD_TAGS: ['span', 'div'] })
  } catch (e) {
    return `<pre>${text}</pre>`
  }
}
