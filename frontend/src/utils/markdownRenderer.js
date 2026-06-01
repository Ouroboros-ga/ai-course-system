import { Marked } from 'marked'
import { markedHighlight } from 'marked-highlight'
import hljs from 'highlight.js'
import DOMPurify from 'dompurify'
import katex from 'katex'

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
